"""
Menu bar app for the Shakespeare wallpaper: show the current quote, switch to a new one,
add or remove quotes, and redraw the wallpaper when displays are connected or removed.

The daily change is still done by the com.shakespeare.wallpaper LaunchAgent; this app is optional UI.
"""

import functools
import logging
import subprocess
import sys

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
from Foundation import NSNotificationCenter, NSObject

import shakespeare_wallpaper as sw

MENU_TITLE = "❦"
MAX_ITEM_CHARS = 60
SCREEN_CHANGE_DELAY = 2.0  # seconds; displays report several changes while settling

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
    """Ask for quote, play and character. Returns (dict, show_now) or None if cancelled."""
    width = 360
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 200))

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

    label("Quote", 182)
    quote_field = entry("quote", 124, 56)
    label("Play", 101)
    play_field = entry("play", 75, 24)
    label("Character", 52)
    character_field = entry("character", 26, 24)
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
    }
    return quote, show_now.state() == NSControlStateValueOn


class ScreenObserver(NSObject):
    """Debounces display-change notifications and calls back once things settle."""

    def initWithCallback_(self, callback):
        self = objc.super(ScreenObserver, self).init()
        if self is not None:
            self.callback = callback
        return self

    def screensChanged_(self, notification):
        NSObject.cancelPreviousPerformRequestsWithTarget_(self)
        self.performSelector_withObject_afterDelay_("fire:", None, SCREEN_CHANGE_DELAY)

    def fire_(self, _):
        self.callback()


class ShakespeareApp(rumps.App):
    def __init__(self):
        super().__init__("Shakespeare Wallpaper", title=MENU_TITLE, quit_button="Quit")
        self.quote_item = rumps.MenuItem("No quote yet")
        self.attribution_item = rumps.MenuItem("")
        self.menu = [
            self.quote_item,
            self.attribution_item,
            None,
            rumps.MenuItem("New Quote Now", callback=self.new_quote),
            rumps.MenuItem("Add Quote…", callback=self.add_quote),
            rumps.MenuItem("Remove Current Quote…", callback=self.remove_quote),
            None,
            rumps.MenuItem("Edit quotes.json…", callback=self.edit_quotes),
            rumps.MenuItem("Open Wallpaper Folder", callback=self.open_folder),
            None,
        ]
        self.state_mtime = None

        self.screen_observer = ScreenObserver.alloc().initWithCallback_(self.screens_changed)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.screen_observer, "screensChanged:",
            NSApplicationDidChangeScreenParametersNotification, None,
        )
        # Picks up quote changes made by the daily LaunchAgent; fires once immediately.
        # Keep a reference: rumps only holds timers weakly.
        self.refresh_timer = rumps.Timer(self.refresh, 60)
        self.refresh_timer.start()

    def refresh(self, _=None):
        try:
            mtime = sw.STATE_PATH.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime == self.state_mtime:
            return
        self.state_mtime = mtime
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

    def screens_changed(self):
        try:
            quote = sw.current_quote()
            log.info("Displays changed, redrawing wallpaper")
            if quote:
                sw.apply_quote(quote)
            else:
                sw.next_quote()
            self.refresh()
        except Exception:
            log.exception("Redraw after display change failed")


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ShakespeareApp().run()


if __name__ == "__main__":
    main()
