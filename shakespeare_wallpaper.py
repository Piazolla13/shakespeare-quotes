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
import json
import logging
import os
import random
import tempfile
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_DIR = Path(__file__).resolve().parent
QUOTES_PATH = PROJECT_DIR / "quotes.json"
STATE_PATH = PROJECT_DIR / "state.json"
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

BG_TOP = (28, 30, 38)
BG_BOTTOM = (8, 9, 12)
TEXT_COLOR = (238, 228, 206)
ACCENT_COLOR = (176, 150, 102)

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
    quote = {key: str(quote.get(key, "")).strip() for key in ("quote", "play", "character")}
    empty = [key for key, value in quote.items() if not value]
    if empty:
        raise ValueError(f"Please fill in: {', '.join(empty)}")
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


def pick_quote(quotes, state):
    """Random quote not shown since the list was last exhausted."""
    recent = set(state.get("recent", []))
    candidates = [q for q in quotes if q["quote"] not in recent]
    if not candidates:
        candidates = quotes
        state["recent"] = []
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


def gradient_background(width, height):
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
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


def attribution_text(quote):
    # Name it once when the character is the title role (Hamlet, Macbeth, ...)
    if quote["character"] == quote["play"]:
        return f"— {quote['play']}".upper()
    return f"— {quote['character']}, {quote['play']}".upper()


def render(quote, width, height):
    image = gradient_background(width, height)
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
        draw.text((width / 2, y + line_height / 2), line, font=font, fill=TEXT_COLOR, anchor="mm")
        y += line_height

    y += gap
    rule_half = width * 0.03
    draw.line([(width / 2 - rule_half, y), (width / 2 + rule_half, y)],
              fill=ACCENT_COLOR, width=max(1, round(height / 900)))
    y += rule_gap + attr_height

    # Letter-spaced small-caps style attribution, drawn on a shared baseline
    spacing = attr_font.size * 0.12
    char_widths = [draw.textlength(c, font=attr_font) for c in attribution]
    x = width / 2 - (sum(char_widths) + spacing * (len(attribution) - 1)) / 2
    for c, w in zip(attribution, char_widths):
        draw.text((x, y), c, font=attr_font, fill=ACCENT_COLOR, anchor="ls")
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


def apply_quote(quote, output_dir=None, dry_run=False):
    """Render the quote for every connected screen and set it as the wallpaper."""
    output_dir = Path(output_dir or OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Microseconds keep filenames unique across quick re-renders (macOS caches by path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    written = []
    for i, (screen, width, height) in enumerate(get_screens()):
        path = output_dir / f"{FILE_PREFIX}{stamp}_{i}_{width}x{height}.png"
        render(quote, width, height).save(path)
        written.append(path)
        log.info("Rendered %s", path)
        if not dry_run:
            set_wallpaper(screen, path)
    if not dry_run:
        cleanup(output_dir, written)
    return written


def show_quote(quote, output_dir=None, dry_run=False, state=None):
    """Set the quote as wallpaper and record it as current (and recently shown)."""
    log.info("Quote: %s (%s, %s)", quote["quote"], quote["character"], quote["play"])
    apply_quote(quote, output_dir, dry_run)
    if not dry_run:
        if state is None:
            state = load_state(STATE_PATH)
        recent = state.setdefault("recent", [])
        if quote["quote"] not in recent:
            recent.append(quote["quote"])
        state["current"] = quote
        save_state(STATE_PATH, state)
    return quote


def next_quote(output_dir=None, dry_run=False):
    """Pick a fresh quote and show it."""
    state = load_state(STATE_PATH)
    quote = pick_quote(load_quotes(QUOTES_PATH), state)
    return show_quote(quote, output_dir, dry_run, state)


def current_quote():
    return load_state(STATE_PATH).get("current")


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="render images only; don't set wallpaper or update state")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="directory for images")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")

    next_quote(args.output, args.dry_run)


if __name__ == "__main__":
    main()
