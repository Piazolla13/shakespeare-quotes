import json
import urllib.error
import urllib.request

import pytest

import menubar
import shakespeare_wallpaper as sw
from manager import QuoteManager

QUOTE = {"quote": "The rest is silence.", "play": "Hamlet", "character": "Hamlet"}


@pytest.fixture
def server(project, fake_screens):
    manager = QuoteManager().start()
    yield manager
    manager.stop()


def call(manager, method, path, token=True, host=None):
    """(status, decoded JSON or text) for a request to the test server."""
    headers = {"X-Token": manager.token if token is True else (token or "")}
    if host:
        headers["Host"] = host
    request = urllib.request.Request(f"http://127.0.0.1:{manager.port}{path}", method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, body = response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode()
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


# History and stats (shakespeare_wallpaper)

def test_show_quote_records_history_but_redraws_do_not(project, fake_screens):
    sw.show_quote(QUOTE, reason="new-quote")
    sw.apply_quote(QUOTE)  # a redraw (wake, theme change): same quote, not a new entry
    sw.next_quote(reason="daily")
    history = sw.load_history()
    assert [e["reason"] for e in history] == ["new-quote", "daily"]
    assert history[0]["quote"] == QUOTE["quote"] and history[0]["play"] == "Hamlet"


def test_dry_run_records_no_history(project, fake_screens):
    sw.next_quote(dry_run=True)
    assert sw.load_history() == []


def test_launchd_is_detected_from_environment(monkeypatch):
    monkeypatch.setenv("XPC_SERVICE_NAME", "com.shakespeare.wallpaper")
    assert sw.launched_by_launchd()
    monkeypatch.setenv("XPC_SERVICE_NAME", "com.apple.Terminal")
    assert not sw.launched_by_launchd()


def test_quote_id_is_stable_and_ignores_case_and_spacing():
    a = sw.quote_id({"quote": "The rest is silence."})
    assert a == sw.quote_id({"quote": "  the REST is   silence. "})
    assert a != sw.quote_id({"quote": "The rest is noise."})
    assert len(a) == 10


def test_history_from_logs_keeps_known_quotes_only(tmp_path):
    log = tmp_path / "out.log"
    log.write_text(
        "2026-10-18 15:22:59,357 INFO Quote: The rest is silence. (Hamlet, Hamlet)\n"
        "2026-10-18 15:23:00,001 INFO Rendered /x.png\n"
        "2026-10-18 15:29:15,348 INFO Quote: Test (test, test)\n", encoding="utf-8")
    entries = sw.history_from_logs([log, tmp_path / "missing.log"], [QUOTE])
    assert entries == [{"at": "2026-10-18T15:22:59", "reason": "log", "quote": QUOTE["quote"],
                        "play": "Hamlet", "character": "Hamlet"}]


def test_import_history_only_fills_an_empty_history(project):
    sw.LOG_DIR.mkdir()
    (sw.LOG_DIR / "out.log").write_text(
        "2026-10-18 15:22:59,357 INFO Quote: Brevity is the soul of wit. (Polonius, Hamlet)\n", encoding="utf-8")
    assert sw.import_history_from_logs() == 1
    assert sw.import_history_from_logs() == 0  # already has entries
    assert len(sw.load_history()) == 1


def test_collection_stats():
    quotes = [QUOTE, {"quote": "x", "play": "Sonnets", "character": "Shakespeare", "sonnet": 1, "tags": ["love"]},
              {"quote": "y", "play": "Macbeth", "character": "Macbeth", "tags": ["love", "time"]}]
    state = {"recent": ["x"], "filter": {"tag": "love"}}
    history = [{"quote": "x", "reason": "daily"}, {"quote": "x", "reason": "cli"}]
    stats = sw.collection_stats(quotes, state, history)
    assert stats["total"] == 3 and stats["plays"] == 2 and stats["sonnet_quotes"] == 1
    assert stats["round"] == {"shown": 1, "pool": 2, "filter": {"tag": "love"}}
    assert stats["never_shown"] == 2
    assert stats["most_shown"] == [{"quote": "x", "count": 2}]
    assert dict(stats["by_tag"]) == {"love": 2, "time": 1}


# Web server

def test_page_is_served(server):
    status, body = call(server, "GET", "/", token=None)
    assert status == 200 and "<title>Quote Manager</title>" in body


@pytest.mark.parametrize("token, host", [(None, None), ("wrong", None), (True, "evil.example:80")])
def test_api_rejects_missing_token_and_foreign_host(server, token, host):
    status, _ = call(server, "GET", "/api/quotes", token=token, host=host)
    assert status == 403


def test_page_rejects_foreign_host(server):
    assert call(server, "GET", "/", token=None, host="evil.example")[0] == 403


def test_list_quotes(server):
    sw.show_quote(QUOTE, reason="new-quote")
    status, rows = call(server, "GET", "/api/quotes")
    assert status == 200 and len(rows) == len(sw.load_quotes(sw.QUOTES_PATH))
    row = next(r for r in rows if r["quote"] == QUOTE["quote"])
    assert row["id"] == sw.quote_id(QUOTE) and row["is_current"] and row["shown_count"] == 1
    assert row["last_shown"] and row["shown_this_round"]
    assert sum(r["is_current"] for r in rows) == 1


def test_stats_and_history(server):
    sw.show_quote(QUOTE, reason="new-quote")
    sw.next_quote(reason="daily")
    status, stats = call(server, "GET", "/api/stats")
    assert status == 200 and stats["total"] == len(sw.load_quotes(sw.QUOTES_PATH)) and stats["history_total"] == 2
    status, history = call(server, "GET", "/api/history")
    assert [e["reason"] for e in history] == ["daily", "new-quote"]  # newest first


def test_remove_a_quote_that_is_not_on_screen(server):
    sw.show_quote(QUOTE)
    other = next(q for q in sw.load_quotes(sw.QUOTES_PATH) if q["quote"] != QUOTE["quote"])
    status, body = call(server, "DELETE", f"/api/quotes/{sw.quote_id(other)}")
    assert status == 200 and body == {"removed": other["quote"], "new_quote_shown": False}
    assert sw.find_quote(sw.quote_id(other)) is None
    assert sw.current_quote()["quote"] == QUOTE["quote"]


def test_removing_the_current_quote_shows_a_new_one(server, fake_screens):
    sw.show_quote(QUOTE)
    fake_screens.clear()
    status, body = call(server, "DELETE", f"/api/quotes/{sw.quote_id(QUOTE)}")
    assert status == 200 and body["new_quote_shown"]
    assert sw.current_quote()["quote"] != QUOTE["quote"] and fake_screens
    assert sw.load_history()[-1]["reason"] == "remove"


def test_remove_errors(server):
    assert call(server, "DELETE", "/api/quotes/0000000000")[0] == 404
    sw.write_json(sw.QUOTES_PATH, [QUOTE])
    status, body = call(server, "DELETE", f"/api/quotes/{sw.quote_id(QUOTE)}")
    assert status == 409 and "last remaining" in body["error"]


def test_show_now(server, fake_screens):
    quote = sw.load_quotes(sw.QUOTES_PATH)[5]
    status, _ = call(server, "POST", f"/api/show/{sw.quote_id(quote)}")
    assert status == 200 and sw.current_quote() == quote and len(fake_screens) == 2
    assert sw.load_history()[-1]["reason"] == "manager"


def test_changes_run_through_the_hosts_main_thread_hook(project, fake_screens):
    ran, changed = [], []
    manager = QuoteManager(run_on_main=lambda fn: (ran.append(fn), fn()), on_change=lambda: changed.append(1)).start()
    try:
        call(manager, "POST", f"/api/show/{sw.quote_id(sw.load_quotes(sw.QUOTES_PATH)[0])}")
    finally:
        manager.stop()
    assert len(ran) == 1 and changed == [1]


# Menu bar

def test_menubar_all_quotes_shows_total_and_manage_opens_browser(project, fake_screens, monkeypatch):
    opened = []
    monkeypatch.setattr("manager.webbrowser.open", opened.append)
    app = menubar.ShakespeareApp()
    assert app.filter_items[None].title == f"All Quotes ({len(sw.load_quotes(sw.QUOTES_PATH))})"
    try:
        app.manage_quotes(None)
        app.manage_quotes(None)  # second time reuses the running server
        assert len(opened) == 2 and opened[0] == opened[1] == app.manager.url
        assert call(app.manager, "GET", "/api/stats")[0] == 200
    finally:
        app.manager.stop()


def test_menubar_actions_record_their_reason(project, fake_screens):
    app = menubar.ShakespeareApp()
    app.new_quote(None)
    app.choose_filter(app.filter_items[("tag", "love")])
    assert [e["reason"] for e in sw.load_history()] == ["new-quote", "filter"]
