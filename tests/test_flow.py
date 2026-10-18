import menubar
import shakespeare_wallpaper as sw

QUOTE = {"quote": "The rest is silence.", "play": "Hamlet", "character": "Hamlet"}


def pngs(directory):
    return sorted(p.name for p in directory.glob("*.png"))


def test_apply_quote_renders_and_sets_each_screen(project, fake_screens):
    written = sw.apply_quote(QUOTE)

    assert [p.name.endswith(suffix) for p, suffix in zip(written, ["_0_1920x1080.png", "_1_2880x1800.png"])] \
        == [True, True]
    assert fake_screens == [("external", written[0]), ("retina", written[1])]
    assert pngs(sw.OUTPUT_DIR) == sorted(p.name for p in written)


def test_apply_quote_uses_new_names_and_removes_old_files(project, fake_screens):
    first = sw.apply_quote(QUOTE)
    second = sw.apply_quote(QUOTE)

    assert not set(first) & set(second)  # macOS caches wallpapers by path
    assert pngs(sw.OUTPUT_DIR) == sorted(p.name for p in second)


def test_dry_run_writes_files_but_sets_nothing(project, fake_screens):
    sw.apply_quote(QUOTE, dry_run=True)
    sw.next_quote(dry_run=True)

    assert fake_screens == []
    assert not sw.STATE_PATH.exists()


def test_next_quote_records_current_and_recent(project, fake_screens):
    shown = sw.next_quote()

    state = sw.load_state(sw.STATE_PATH)
    assert state["current"] == shown == sw.current_quote()
    assert state["recent"] == [shown["quote"]]


def test_show_quote_does_not_duplicate_recent(project, fake_screens):
    sw.show_quote(QUOTE)
    sw.show_quote(QUOTE)

    assert sw.load_state(sw.STATE_PATH)["recent"] == [QUOTE["quote"]]


def test_menubar_truncate():
    assert menubar.truncate("short") == "short"
    long_text = "word " * 30
    result = menubar.truncate(long_text)
    assert len(result) <= menubar.MAX_ITEM_CHARS and result.endswith("…")


# Themes

def test_auto_theme_follows_appearance(monkeypatch):
    monkeypatch.setattr(sw, "dark_mode", lambda: True)
    assert sw.resolve_theme("auto") == "ink"
    monkeypatch.setattr(sw, "dark_mode", lambda: False)
    assert sw.resolve_theme("auto") == "parchment"
    assert sw.resolve_theme("midnight") == "midnight"
    assert sw.resolve_theme("removed-theme") == sw.DEFAULT_THEME


def test_set_theme_saves_choice_and_rejects_unknown(project):
    assert sw.get_theme() == sw.DEFAULT_THEME
    sw.set_theme("parchment")
    assert sw.get_theme() == "parchment"
    try:
        sw.set_theme("neon")
        raise AssertionError("should fail")
    except ValueError as e:
        assert "Unknown theme" in str(e)
    assert sw.get_theme() == "parchment"


def test_apply_quote_uses_saved_theme_unless_overridden(project, fake_screens, monkeypatch):
    used = []
    real_render = sw.render
    monkeypatch.setattr(sw, "render", lambda q, w, h, theme: used.append(theme) or real_render(q, w, h, theme))
    sw.set_theme("midnight")
    sw.apply_quote(QUOTE)
    sw.apply_quote(QUOTE, theme="parchment")
    assert used == ["midnight", "midnight", "parchment", "parchment"]


def test_menubar_theme_menu_saves_and_redraws(project, fake_screens):
    sw.show_quote(QUOTE)
    fake_screens.clear()
    app = menubar.ShakespeareApp()

    app.choose_theme(app.theme_items["parchment"])

    assert sw.get_theme() == "parchment"
    assert len(fake_screens) == 2  # current quote redrawn on both screens
    assert [n for n, item in app.theme_items.items() if item.state] == ["parchment"]
    assert sw.current_quote() == QUOTE
