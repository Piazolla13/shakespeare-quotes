"""
Runs on regular intervals (1/day, via launchd) to update Mac's wallpaper with a new Shakespeare quote.
The lock screen shows the main display's wallpaper, so the quote appears there too.

# 1. Read JSON file to get set of quotes
# 2. Select quote randomly, skipping recently shown ones (tracked in state.json)
# 3. Generate a high-res wallpaper per display using Pillow
# 4. Format quote, play, attribution with elegant typography
# 5. Save image to ~/Pictures/ShakespeareDaily/ under a new filename each run
#    (macOS caches wallpapers by path) and set it as the wallpaper via NSWorkspace


# GUI
# -> menubar.py: menu bar app to show, add and remove quotes (uses the functions below)
"""

import argparse
import hashlib
import json
import logging
import os
import random
import re
import tempfile
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_DIR = Path(__file__).resolve().parent
QUOTES_PATH = PROJECT_DIR / "quotes.json"
STATE_PATH = PROJECT_DIR / "state.json"
HISTORY_PATH = PROJECT_DIR / "history.json"
LOG_DIR = PROJECT_DIR / "logs"
OUTPUT_DIR = Path.home() / "Pictures" / "ShakespeareDaily"
FILE_PREFIX = "shakespeare_"

# (path, index into .ttc collection) in order of preference
QUOTE_FONTS = [
    ("/System/Library/Fonts/Supplemental/Hoefler Text.ttc", 2),  # Italic
    ("/System/Library/Fonts/Supplemental/Baskerville.ttc", 2),   # Italic
    ("/System/Library/Fonts/Supplemental/Georgia Italic.ttf", 0),
]
ATTRIBUTION_FONTS = [
    ("/System/Library/Fonts/Supplemental/Hoefler Text.ttc", 0),  # Regular
    ("/System/Library/Fonts/Supplemental/Baskerville.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
]

# Background gradient (top, bottom), quote text, accent (rule and attribution)
THEMES = {
    "ink": {"top": (28, 30, 38), "bottom": (8, 9, 12), "text": (238, 228, 206), "accent": (176, 150, 102)},
    "parchment": {"top": (243, 234, 213), "bottom": (225, 210, 178), "text": (52, 38, 28),
                  "accent": (122, 42, 34)},
    "midnight": {"top": (24, 36, 62), "bottom": (6, 10, 24), "text": (226, 232, 242), "accent": (148, 168, 200)},
}
AUTO_THEMES = {"dark": "ink", "light": "parchment"}  # "auto" follows the macOS appearance
THEME_CHOICES = ["auto", *THEMES]
DEFAULT_THEME = "ink"

# Quote block is kept in the middle band, clear of the lock-screen clock (top)
# and the avatar / password field (bottom).
BLOCK_CENTER_Y = 0.55
BLOCK_MAX_WIDTH = 0.70
BLOCK_MAX_HEIGHT = 0.36

log = logging.getLogger("shakespeare")


def load_quotes(path):
    with open(path, encoding="utf-8") as f:
        quotes = json.load(f)
    for i, q in enumerate(quotes):
        missing = {"quote", "play", "character"} - q.keys()
        if missing:
            raise ValueError(f"Quote #{i} in {path} is missing {sorted(missing)}")
        tags = q.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) and t for t in tags):
            raise ValueError(f"Quote #{i} in {path}: tags must be a list of words")
    if not quotes:
        raise ValueError(f"No quotes in {path}")
    return quotes


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"recent": []}


def write_json(path, data):
    """Atomic write: the daily job and the menu bar app may both write these files."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def save_state(path, state):
    write_json(path, state)


def add_quote(quote, path=None):
    """Validate and append a quote dict; raises ValueError with a user-facing message."""
    path = path or QUOTES_PATH
    tags = parse_tags(quote.get("tags", []))
    quote = {key: str(quote.get(key, "")).strip() for key in ("quote", "play", "character")}
    empty = [key for key, value in quote.items() if not value]
    if empty:
        raise ValueError(f"Please fill in: {', '.join(empty)}")
    if tags:
        quote["tags"] = tags
    quotes = load_quotes(path)
    if any(q["quote"].casefold() == quote["quote"].casefold() for q in quotes):
        raise ValueError("That quote is already in the list.")
    write_json(path, quotes + [quote])
    return quote


def remove_quote(text, path=None, state_path=None):
    path = path or QUOTES_PATH
    state_path = state_path or STATE_PATH
    quotes = load_quotes(path)
    remaining = [q for q in quotes if q["quote"] != text]
    if len(remaining) == len(quotes):
        raise ValueError("Quote not found in the list.")
    if not remaining:
        raise ValueError("Can't remove the last remaining quote.")
    write_json(path, remaining)
    state = load_state(state_path)
    state["recent"] = [t for t in state.get("recent", []) if t != text]
    save_state(state_path, state)


def parse_tags(tags):
    """Tags from a list or a comma-separated string, lower-cased, without duplicates."""
    if isinstance(tags, str):
        tags = tags.split(",")
    return list(dict.fromkeys(t.strip().lower() for t in tags if t.strip()))


def matches_filter(quote, quote_filter):
    if not quote_filter:
        return True
    if "tag" in quote_filter:
        return quote_filter["tag"] in quote.get("tags", [])
    return quote["play"] == quote_filter.get("play")


def get_filter():
    """Saved "quotes from" filter: None (all quotes), {"tag": ...} or {"play": ...}."""
    return load_state(STATE_PATH).get("filter")


def set_filter(quote_filter):
    if quote_filter is not None and (len(quote_filter) != 1 or not {"tag", "play"} & quote_filter.keys()):
        raise ValueError(f"Invalid filter {quote_filter!r}")
    state = load_state(STATE_PATH)
    if quote_filter:
        state["filter"] = quote_filter
    else:
        state.pop("filter", None)
    save_state(STATE_PATH, state)


def pick_quote(quotes, state):
    """Random quote not shown since every quote (that matches the filter) was last shown."""
    pool = [q for q in quotes if matches_filter(q, state.get("filter"))] or quotes
    recent = set(state.get("recent", []))
    candidates = [q for q in pool if q["quote"] not in recent]
    if not candidates:
        candidates = pool
        pool_texts = {q["quote"] for q in pool}
        state["recent"] = [t for t in state.get("recent", []) if t not in pool_texts]
    quote = random.choice(candidates)
    state["recent"] = state.get("recent", []) + [quote["quote"]]
    return quote


def load_font(candidates, size):
    for path, index in candidates:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    log.warning("No preferred font found, using Pillow default")
    return ImageFont.load_default(size)


def wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=font) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def gradient_background(width, height, palette):
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(palette["top"], palette["bottom"])))
    return column.resize((width, height))


def layout(draw, text, width, height):
    """Largest font size at which the wrapped quote fits the block."""
    max_w = width * BLOCK_MAX_WIDTH
    max_h = height * BLOCK_MAX_HEIGHT
    size = round(height * 0.05)
    min_size = max(round(height * 0.018), 12)
    while True:
        font = load_font(QUOTE_FONTS, size)
        lines = wrap(draw, text, font, max_w)
        line_height = size * 1.35
        if len(lines) * line_height <= max_h or size <= min_size:
            return font, lines, line_height
        size = round(size * 0.92)


def work_title(quote):
    """"Hamlet", or "Sonnet 18" for a sonnet."""
    return f"Sonnet {quote['sonnet']}" if quote.get("sonnet") else quote["play"]


def attribution_text(quote):
    # Name it once when the character is the title role (Hamlet, Macbeth, ...)
    if quote["character"] == quote["play"]:
        text = f"— {quote['play']}"
    else:
        text = f"— {quote['character']}, {work_title(quote)}"
    if quote.get("act"):
        text += f" · Act {quote['act']}"
        if quote.get("scene"):
            text += f", Scene {quote['scene']}"
    return text.upper()


def render(quote, width, height, theme=DEFAULT_THEME):
    palette = THEMES[theme]
    image = gradient_background(width, height, palette)
    draw = ImageDraw.Draw(image)

    text = f"“{quote['quote'].strip().replace(chr(39), '’')}”"
    font, lines, line_height = layout(draw, text, width, height)
    attr_font = load_font(ATTRIBUTION_FONTS, round(font.size * 0.5))
    attribution = attribution_text(quote)

    gap = font.size * 0.9
    rule_gap = font.size * 0.6
    attr_height = attr_font.getmetrics()[0]
    block_height = len(lines) * line_height + gap + rule_gap + attr_height
    y = height * BLOCK_CENTER_Y - block_height / 2

    for line in lines:
        draw.text((width / 2, y + line_height / 2), line, font=font, fill=palette["text"], anchor="mm")
        y += line_height

    y += gap
    rule_half = width * 0.03
    draw.line([(width / 2 - rule_half, y), (width / 2 + rule_half, y)],
              fill=palette["accent"], width=max(1, round(height / 900)))
    y += rule_gap + attr_height

    # Letter-spaced small-caps style attribution, drawn on a shared baseline
    spacing = attr_font.size * 0.12
    char_widths = [draw.textlength(c, font=attr_font) for c in attribution]
    x = width / 2 - (sum(char_widths) + spacing * (len(attribution) - 1)) / 2
    for c, w in zip(attribution, char_widths):
        draw.text((x, y), c, font=attr_font, fill=palette["accent"], anchor="ls")
        x += w + spacing

    return image


def get_screens():
    from AppKit import NSScreen

    screens = []
    for screen in NSScreen.screens():
        size = screen.frame().size
        scale = screen.backingScaleFactor()
        screens.append((screen, round(size.width * scale), round(size.height * scale)))
    return screens


def set_wallpaper(screen, path):
    from AppKit import NSWorkspace
    from Foundation import NSURL

    ok, error = NSWorkspace.sharedWorkspace().setDesktopImageURL_forScreen_options_error_(
        NSURL.fileURLWithPath_(str(path)), screen, {}, None
    )
    if not ok:
        raise RuntimeError(f"Failed to set wallpaper: {error}")


def cleanup(output_dir, keep):
    for old in output_dir.glob(f"{FILE_PREFIX}*.png"):
        if old not in keep:
            old.unlink()


def dark_mode():
    from Foundation import NSUserDefaults

    return NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle") == "Dark"


def resolve_theme(name):
    """Palette name to draw with; "auto" picks by the current macOS appearance."""
    if name == "auto":
        return AUTO_THEMES["dark" if dark_mode() else "light"]
    return name if name in THEMES else DEFAULT_THEME


def get_theme():
    return load_state(STATE_PATH).get("theme", DEFAULT_THEME)


def set_theme(name):
    if name not in THEME_CHOICES:
        raise ValueError(f"Unknown theme {name!r}; choose from {', '.join(THEME_CHOICES)}")
    state = load_state(STATE_PATH)
    state["theme"] = name
    save_state(STATE_PATH, state)


def apply_quote(quote, output_dir=None, dry_run=False, theme=None):
    """Render the quote for every connected screen and set it as the wallpaper."""
    output_dir = Path(output_dir or OUTPUT_DIR)
    theme = resolve_theme(theme or get_theme())
    output_dir.mkdir(parents=True, exist_ok=True)
    # Microseconds keep filenames unique across quick re-renders (macOS caches by path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    written = []
    for i, (screen, width, height) in enumerate(get_screens()):
        path = output_dir / f"{FILE_PREFIX}{stamp}_{i}_{width}x{height}.png"
        render(quote, width, height, theme).save(path)
        written.append(path)
        log.info("Rendered %s", path)
        if not dry_run:
            set_wallpaper(screen, path)
    if not dry_run:
        cleanup(output_dir, written)
    return written


def show_quote(quote, output_dir=None, dry_run=False, state=None, theme=None, reason="manual"):
    """Set the quote as wallpaper and record it as current, recently shown and in the history.

    reason says what triggered the change ("daily", "new-quote", "filter", ...) for the history.
    """
    log.info("Quote: %s (%s, %s)", quote["quote"], quote["character"], quote["play"])
    apply_quote(quote, output_dir, dry_run, theme)
    if not dry_run:
        if state is None:
            state = load_state(STATE_PATH)
        recent = state.setdefault("recent", [])
        if quote["quote"] not in recent:
            recent.append(quote["quote"])
        state["current"] = quote
        save_state(STATE_PATH, state)
        record_history(quote, reason)
    return quote


def next_quote(output_dir=None, dry_run=False, theme=None, quote_filter=None, reason="manual"):
    """Pick a fresh quote and show it; quote_filter overrides the saved filter for this pick."""
    state = load_state(STATE_PATH)
    if quote_filter is not None:
        state["filter"] = quote_filter or None
    quote = pick_quote(load_quotes(QUOTES_PATH), state)
    return show_quote(quote, output_dir, dry_run, state, theme, reason)


def current_quote():
    return load_state(STATE_PATH).get("current")


# History and statistics

def quote_id(quote):
    """Stable short id from the quote text (quote texts are unique, see add_quote)."""
    text = " ".join(quote["quote"].casefold().split())
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def find_quote(qid, quotes=None):
    for q in quotes if quotes is not None else load_quotes(QUOTES_PATH):
        if quote_id(q) == qid:
            return q
    return None


def load_history():
    """Display history, oldest first: [{"at", "quote", "play", "character", "reason", ...}]."""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)
        return history if isinstance(history, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def history_entry(quote, reason, at=None):
    # A snapshot of the quote, so entries still make sense after the quote is removed
    entry = {"at": at or datetime.now().isoformat(timespec="seconds"), "reason": reason}
    entry.update({k: quote[k] for k in ("quote", "play", "character", "sonnet") if k in quote})
    return entry


def record_history(quote, reason):
    write_json(HISTORY_PATH, load_history() + [history_entry(quote, reason)])


def launched_by_launchd():
    # launchd sets XPC_SERVICE_NAME to the job label for the processes it starts
    return os.environ.get("XPC_SERVICE_NAME") == "com.shakespeare.wallpaper"


LOG_QUOTE_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO Quote: (.*)$")


def history_from_logs(log_paths, quotes):
    """Past changes from the "Quote:" log lines, for quotes still in the list (oldest first)."""
    by_prefix = {f"{q['quote']} (": q for q in quotes}
    entries = []
    for path in log_paths:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            m = LOG_QUOTE_LINE.match(line)
            if not m:
                continue
            quote = next((q for prefix, q in by_prefix.items() if m.group(2).startswith(prefix)), None)
            if quote:
                entries.append(history_entry(quote, "log", at=m.group(1).replace(" ", "T")))
    return sorted(entries, key=lambda e: e["at"])


def import_history_from_logs():
    """One-off: fill an empty history from the logs. Returns the number of entries imported."""
    if load_history():
        return 0
    entries = history_from_logs([LOG_DIR / "out.log", LOG_DIR / "menubar.out.log"], load_quotes(QUOTES_PATH))
    if entries:
        write_json(HISTORY_PATH, entries)
    return len(entries)


def collection_stats(quotes, state, history):
    """Numbers for the manager page."""
    shown = Counter(e["quote"] for e in history)
    pool = [q for q in quotes if matches_filter(q, state.get("filter"))] or quotes
    recent = set(state.get("recent", []))
    plays = Counter(q["play"] for q in quotes)
    return {
        "total": len(quotes),
        "plays": len([p for p in plays if p != "Sonnets"]),
        "sonnet_quotes": plays.get("Sonnets", 0),
        "by_play": plays.most_common(),
        "by_tag": Counter(t for q in quotes for t in q.get("tags", [])).most_common(),
        "top_characters": Counter(q["character"] for q in quotes).most_common(15),
        "round": {"shown": sum(q["quote"] in recent for q in pool), "pool": len(pool),
                  "filter": state.get("filter")},
        "never_shown": sum(q["quote"] not in shown for q in quotes),
        "most_shown": [{"quote": text, "count": n} for text, n in shown.most_common(10)],
        "history_total": len(history),
        "changes_by_reason": Counter(e.get("reason", "?") for e in history).most_common(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="render images only; don't set wallpaper or update state")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="directory for images")
    parser.add_argument("--theme", choices=THEME_CHOICES,
                        help="use this theme from now on (with --dry-run: for this render only)")
    parser.add_argument("--only", metavar="FILTER",
                        help='from now on pick quotes from "tag:NAME", "play:NAME" or "all" '
                             "(with --dry-run: for this pick only)")
    args = parser.parse_args()

    quote_filter = None
    if args.only:
        kind, _, value = args.only.partition(":")
        if args.only == "all":
            quote_filter = {}
        elif kind in ("tag", "play") and value:
            quote_filter = {kind: value.lower() if kind == "tag" else value}
            if not any(matches_filter(q, quote_filter) for q in load_quotes(QUOTES_PATH)):
                parser.error(f"no quotes match {args.only!r}")
        else:
            parser.error('--only takes "tag:NAME", "play:NAME" or "all"')

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.theme and not args.dry_run:
        set_theme(args.theme)
    if quote_filter is not None and not args.dry_run:
        set_filter(quote_filter or None)
    next_quote(args.output, args.dry_run, args.theme, quote_filter,
               reason="daily" if launched_by_launchd() else "cli")


if __name__ == "__main__":
    main()
