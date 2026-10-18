import pytest
from PIL import Image, ImageChops, ImageDraw

import shakespeare_wallpaper as sw
from conftest import REAL_QUOTES

SHORT = {"quote": "The rest is silence.", "play": "Hamlet", "character": "Hamlet"}
LONG = {
    "quote": "Life's but a walking shadow, a poor player that struts and frets his hour upon "
             "the stage, and then is heard no more. It is a tale told by an idiot, full of sound "
             "and fury, signifying nothing.",
    "play": "Macbeth",
    "character": "Macbeth",
}

# The lock screen draws the clock near the top and the avatar / password field near the
# bottom; everything drawn must stay inside this band (fractions of width / height).
SAFE_TOP, SAFE_BOTTOM = 0.25, 0.85
SAFE_SIDE = 0.10


def text_bbox(quote, width, height, theme=sw.DEFAULT_THEME):
    """Bounding box of everything drawn on top of the plain background."""
    image = sw.render(quote, width, height, theme)
    background = sw.gradient_background(width, height, sw.THEMES[theme])
    return ImageChops.difference(image, background).getbbox()


def assert_in_safe_zone(quote, width, height, theme=sw.DEFAULT_THEME):
    left, top, right, bottom = text_bbox(quote, width, height, theme)
    assert top >= SAFE_TOP * height, f"text starts at {top / height:.0%} of height"
    assert bottom <= SAFE_BOTTOM * height, f"text ends at {bottom / height:.0%} of height"
    assert left >= SAFE_SIDE * width and right <= (1 - SAFE_SIDE) * width


@pytest.mark.parametrize("theme", sw.THEMES)
@pytest.mark.parametrize("size", [(1920, 1080), (2880, 1800)])
def test_render_size_and_safe_zone_for_every_theme(size, theme):
    assert sw.render(SHORT, *size, theme).size == size
    assert_in_safe_zone(LONG, *size, theme)


def contrast(a, b):
    """WCAG contrast ratio between two RGB colours."""
    def luminance(rgb):
        c = [v / 255 for v in rgb]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted([luminance(a), luminance(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", sw.THEMES)
def test_theme_text_is_readable(theme):
    palette = sw.THEMES[theme]
    for background in (palette["top"], palette["bottom"]):
        assert contrast(palette["text"], background) >= 7     # WCAG AAA
        assert contrast(palette["accent"], background) >= 4.5  # WCAG AA


@pytest.mark.parametrize("quote", [SHORT, LONG], ids=["short", "long"])
@pytest.mark.parametrize("size", [(1920, 1080), (2880, 1800)])
def test_text_stays_in_lock_screen_safe_zone(quote, size):
    assert_in_safe_zone(quote, *size)


@pytest.mark.parametrize("quote", sw.load_quotes(REAL_QUOTES), ids=lambda q: q["quote"][:30])
def test_every_real_quote_fits_safe_zone(quote):
    assert_in_safe_zone(quote, 1920, 1080)


def test_layout_shrinks_long_quotes_but_not_below_minimum():
    width, height = 1920, 1080
    draw = ImageDraw.Draw(Image.new("RGB", (width, height)))
    short_font, _, _ = sw.layout(draw, SHORT["quote"], width, height)
    # LONG alone still fits at full size; doubling it forces the font to shrink
    long_font, _, _ = sw.layout(draw, LONG["quote"] * 2, width, height)
    huge_font, _, _ = sw.layout(draw, LONG["quote"] * 10, width, height)

    assert long_font.size < short_font.size
    assert huge_font.size >= max(round(height * 0.018), 12)


def test_attribution_names_title_role_once():
    assert sw.attribution_text(SHORT) == "— HAMLET"
    assert sw.attribution_text({"quote": "x", "play": "Twelfth Night", "character": "Malvolio"}) \
        == "— MALVOLIO, TWELFTH NIGHT"


def test_attribution_includes_act_and_scene():
    quote = {"quote": "x", "play": "Twelfth Night", "character": "Malvolio", "act": "II", "scene": "V"}
    assert sw.attribution_text(quote) == "— MALVOLIO, TWELFTH NIGHT · ACT II, SCENE V"
    assert sw.attribution_text({**SHORT, "act": "V"}) == "— HAMLET · ACT V"
