"""
Menu bar app for the Shakespeare wallpaper: show the current quote, switch to a new one,
add or remove quotes, and redraw the wallpaper when displays are connected or removed.

The daily change is still done by the com.shakespeare.wallpaper LaunchAgent; this app is optional UI.
"""

import functools
import logging
import subprocess
import sys
from collections import Counter

import objc
import rumps
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationDidChangeScreenParametersNotification,
    NSButton,
    NSButtonTypeSwitch,
    NSControlStateValueOn,
    NSMakeRect,
    NSTextField,
    NSView,
)
from Foundation import NSDistributedNotificationCenter, NSNotificationCenter, NSObject

import shakespeare_wallpaper as sw

MENU_TITLE = "❦"
MAX_ITEM_CHARS = 60
SCREEN_CHANGE_DELAY = 2.0  # seconds; displays report several changes while settling
THEME_TITLES = {"auto": "Automatic (Light / Dark)", "ink": "Ink", "parchment": "Parchment", "midnight": "Midnight"}

log = logging.getLogger("shakespeare.menubar")


def truncate(text, limit=MAX_ITEM_CHARS):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def alert(title, message="", buttons=("OK",)):
    """Modal alert; returns the index of the clicked button."""
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    a = NSAlert.alloc().init()
    a.setMessageText_(title)
    a.setInformativeText_(message)
    for b in buttons:
        a.addButtonWithTitle_(b)
    return a.runModal() - NSAlertFirstButtonReturn


def guarded(func):
    """Log and show errors from menu callbacks instead of crashing the app."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.exception("%s failed", func.__name__)
            alert("Shakespeare Wallpaper", f"Something went wrong: {e}")
    return wrapper


def quote_dialog(values):
    """Ask for quote, play, character and tags. Returns (dict, show_now) or None if cancelled."""
    width = 360
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 250))

    def label(text, y):
        field = NSTextField.labelWithString_(text)
        field.setFrame_(NSMakeRect(0, y, width, 17))
        view.addSubview_(field)

    def entry(key, y, height):
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, y, width, height))
        field.setStringValue_(values.get(key, ""))
        if height > 24:
            field.setUsesSingleLineMode_(False)
            field.cell().setWraps_(True)
            field.cell().setScrollable_(False)
        view.addSubview_(field)
        return field

    label("Quote", 231)
    quote_field = entry("quote", 173, 56)
    label("Play", 150)
    play_field = entry("play", 124, 24)
    label("Character", 101)
    character_field = entry("character", 75, 24)
    label("Tags (optional, comma-separated, e.g. love, time)", 52)
    tags_field = entry("tags", 26, 24)
    show_now = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, width, 18))
    show_now.setButtonType_(NSButtonTypeSwitch)
    show_now.setTitle_("Show it now")
    view.addSubview_(show_now)

    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    a = NSAlert.alloc().init()
    a.setMessageText_("Add Quote")
    a.addButtonWithTitle_("Add")
    a.addButtonWithTitle_("Cancel")
    a.setAccessoryView_(view)
    a.window().setInitialFirstResponder_(quote_field)
    if a.runModal() != NSAlertFirstButtonReturn:
        return None
    quote = {
        "quote": quote_field.stringValue(),
        "play": play_field.stringValue(),
        "character": character_field.stringValue(),
        "tags": tags_field.stringValue(),
    }
    return quote, show_now.state() == NSControlStateValueOn


class DebouncedObserver(NSObject):
    """Debounces notifications (displays and appearance report several changes while settling)."""

    def initWithCallback_(self, callback):
        self = objc.super(DebouncedObserver, self).init()
        if self is not None:
            self.callback = callback
        return self

    def changed_(self, notification):
        NSObject.cancelPreviousPerformRequestsWithTarget_(self)
        self.performSelector_withObject_afterDelay_("fire:", None, SCREEN_CHANGE_DELAY)

    def fire_(self, _):
        self.callback()


class ShakespeareApp(rumps.App):
    def __init__(self):
        super().__init__("Shakespeare Wallpaper", title=MENU_TITLE, quit_button="Quit")
        self.quote_item = rumps.MenuItem("No quote yet")
        self.attribution_item = rumps.MenuItem("")
        self.theme_items = {name: rumps.MenuItem(title, callback=self.choose_theme)
                            for name, title in THEME_TITLES.items()}
        theme_menu = rumps.MenuItem("Theme")
        for item in self.theme_items.values():
            theme_menu.add(item)
        self.filter_menu = rumps.MenuItem("Quotes From")
        self.filter_items = {}  # None (all), ("tag", name) or ("play", name) -> menu item
        self.quotes_mtime = None
        self.build_filter_menu()
        self.menu = [
            self.quote_item,
            self.attribution_item,
            None,
            rumps.MenuItem("New Quote Now", callback=self.new_quote),
            rumps.MenuItem("Add Quote…", callback=self.add_quote),
            rumps.MenuItem("Remove Current Quote…", callback=self.remove_quote),
            self.filter_menu,
            theme_menu,
            None,
            rumps.MenuItem("Edit quotes.json…", callback=self.edit_quotes),
            rumps.MenuItem("Open Wallpaper Folder", callback=self.open_folder),
            None,
        ]
        self.state_mtime = None

        self.screen_observer = DebouncedObserver.alloc().initWithCallback_(self.screens_changed)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.screen_observer, "changed:", NSApplicationDidChangeScreenParametersNotification, None,
        )
        # Posted when macOS switches between light and dark
        self.appearance_observer = DebouncedObserver.alloc().initWithCallback_(self.appearance_changed)
        NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.appearance_observer, "changed:", "AppleInterfaceThemeChangedNotification", None,
        )
        # Picks up quote changes made by the daily LaunchAgent; fires once immediately.
        # Keep a reference: rumps only holds timers weakly.
        self.refresh_timer = rumps.Timer(self.refresh, 60)
        self.refresh_timer.start()

    def build_filter_menu(self):
        """(Re)build "Quotes From": All Quotes, tags by how often they're used, then plays."""
        quotes = sw.load_quotes(sw.QUOTES_PATH)
        self.quotes_mtime = sw.QUOTES_PATH.stat().st_mtime
        tags = Counter(t for q in quotes for t in q.get("tags", []))
        plays = Counter(q["play"] for q in quotes)

        if self.filter_items:
            self.filter_menu.clear()
        self.filter_items = {None: rumps.MenuItem("All Quotes", callback=self.choose_filter)}
        for tag, count in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])):
            self.filter_items[("tag", tag)] = rumps.MenuItem(f"{tag.capitalize()} ({count})",
                                                             callback=self.choose_filter)
        play_menu = rumps.MenuItem("Play")
        for play in sorted(plays, key=lambda p: p.removeprefix("The ").removeprefix("A ")):
            item = rumps.MenuItem(f"{play} ({plays[play]})", callback=self.choose_filter)
            self.filter_items[("play", play)] = item
            play_menu.add(item)

        for key, item in self.filter_items.items():
            if key is None or key[0] == "tag":
                self.filter_menu.add(item)
            if key is None:
                self.filter_menu.add(None)
        self.filter_menu.add(None)
        self.filter_menu.add(play_menu)

    def refresh(self, _=None):
        if sw.QUOTES_PATH.stat().st_mtime != self.quotes_mtime:
            self.build_filter_menu()
            self.state_mtime = None  # re-apply checkmarks to the new items
        try:
            mtime = sw.STATE_PATH.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime == self.state_mtime:
            return
        self.state_mtime = mtime
        theme = sw.get_theme()
        for name, item in self.theme_items.items():
            item.state = int(name == theme)
        quote_filter = sw.get_filter()
        selected = next(iter(quote_filter.items())) if quote_filter else None
        for key, item in self.filter_items.items():
            item.state = int(key == selected)
        quote = sw.current_quote()
        if quote:
            self.quote_item.title = truncate(f"“{quote['quote']}”")
            self.attribution_item.title = f"— {quote['character']}, {quote['play']}"
        else:
            self.quote_item.title = "No quote yet"
            self.attribution_item.title = ""

    @guarded
    def new_quote(self, _):
        sw.next_quote()
        self.refresh()

    @guarded
    def add_quote(self, _):
        values = {}
        while True:
            result = quote_dialog(values)
            if result is None:
                return
            values, show_now = result
            try:
                quote = sw.add_quote(values)
            except ValueError as e:
                alert("Couldn’t add quote", str(e))
                continue
            break
        log.info("Added quote: %s", quote["quote"])
        if show_now:
            sw.show_quote(quote)
            self.refresh()

    @guarded
    def remove_quote(self, _):
        quote = sw.current_quote()
        if not quote:
            alert("No current quote to remove.")
            return
        choice = alert("Remove this quote?", f"“{quote['quote']}”\n— {quote['character']}, {quote['play']}",
                       buttons=("Remove", "Cancel"))
        if choice != 0:
            return
        try:
            sw.remove_quote(quote["quote"])
        except ValueError as e:
            alert("Couldn’t remove quote", str(e))
            return
        log.info("Removed quote: %s", quote["quote"])
        sw.next_quote()
        self.refresh()

    def edit_quotes(self, _):
        subprocess.run(["open", "-t", str(sw.QUOTES_PATH)])

    def open_folder(self, _):
        sw.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(sw.OUTPUT_DIR)])

    @guarded
    def choose_filter(self, sender):
        key = next(k for k, item in self.filter_items.items() if item is sender)
        sw.set_filter(dict([key]) if key else None)
        log.info("Quotes from %s", key or "all")
        sw.next_quote()
        self.refresh()

    @guarded
    def choose_theme(self, sender):
        name = next(n for n, item in self.theme_items.items() if item is sender)
        sw.set_theme(name)
        log.info("Theme set to %s", name)
        self.redraw()

    def redraw(self):
        quote = sw.current_quote()
        if quote:
            sw.apply_quote(quote)
        else:
            sw.next_quote()
        self.refresh()

    def screens_changed(self):
        try:
            log.info("Displays changed, redrawing wallpaper")
            self.redraw()
        except Exception:
            log.exception("Redraw after display change failed")

    def appearance_changed(self):
        try:
            if sw.get_theme() == "auto":
                log.info("Appearance changed, redrawing wallpaper")
                self.redraw()
        except Exception:
            log.exception("Redraw after appearance change failed")


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ShakespeareApp().run()


if __name__ == "__main__":
    main()
