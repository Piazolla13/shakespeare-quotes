import shutil

import pytest

import shakespeare_wallpaper as sw

REAL_QUOTES = sw.QUOTES_PATH


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Point the module at a temp copy of quotes.json and empty state/history/output locations."""
    quotes = tmp_path / "quotes.json"
    shutil.copy(REAL_QUOTES, quotes)
    monkeypatch.setattr(sw, "QUOTES_PATH", quotes)
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sw, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(sw, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(sw, "LOG_DIR", tmp_path / "logs")
    return tmp_path


@pytest.fixture
def fake_screens(monkeypatch):
    """Two fake displays; records set_wallpaper calls instead of changing the real wallpaper."""
    screens = [("external", 1920, 1080), ("retina", 2880, 1800)]
    calls = []
    monkeypatch.setattr(sw, "get_screens", lambda: screens)
    monkeypatch.setattr(sw, "set_wallpaper", lambda screen, path: calls.append((screen, path)))
    return calls
