import json
import random

import pytest

import shakespeare_wallpaper as sw
from conftest import REAL_QUOTES


def quote(text, play="Hamlet", character="Hamlet"):
    return {"quote": text, "play": play, "character": character}


# load_quotes

def test_load_quotes_rejects_missing_keys(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([{"quote": "x", "play": "y"}]))
    with pytest.raises(ValueError, match="missing"):
        sw.load_quotes(path)


def test_load_quotes_rejects_empty_list(tmp_path):
    path = tmp_path / "q.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="No quotes"):
        sw.load_quotes(path)


def test_real_quotes_file_is_valid():
    quotes = sw.load_quotes(REAL_QUOTES)
    for q in quotes:
        assert all(q[key].strip() for key in ("quote", "play", "character")), q
    texts = [q["quote"].casefold() for q in quotes]
    assert len(texts) == len(set(texts)), "duplicate quotes in quotes.json"


# pick_quote

def test_pick_quote_shows_every_quote_before_repeating():
    random.seed(0)
    quotes = [quote(f"q{i}") for i in range(10)]
    state = {"recent": []}
    first_round = [sw.pick_quote(quotes, state)["quote"] for _ in quotes]
    assert sorted(first_round) == sorted(q["quote"] for q in quotes)

    sw.pick_quote(quotes, state)
    assert len(state["recent"]) == 1  # new round started


# add_quote / remove_quote

def test_add_quote_strips_and_appends(project):
    added = sw.add_quote({"quote": "  A line the Bard never wrote. ",
                          "play": " Julius Caesar", "character": "Cassius "})
    assert added == quote("A line the Bard never wrote.", "Julius Caesar", "Cassius")
    assert sw.load_quotes(sw.QUOTES_PATH)[-1] == added


@pytest.mark.parametrize("bad, message", [
    ({"quote": "x", "play": "", "character": " "}, "Please fill in: play, character"),
    ({"quote": "BREVITY IS THE SOUL OF WIT.", "play": "a", "character": "b"}, "already in the list"),
])
def test_add_quote_rejects_bad_input_and_leaves_file_unchanged(project, bad, message):
    before = sw.QUOTES_PATH.read_bytes()
    with pytest.raises(ValueError, match=message):
        sw.add_quote(bad)
    assert sw.QUOTES_PATH.read_bytes() == before


def test_remove_quote_updates_quotes_and_recent(project):
    text = "Brevity is the soul of wit."
    sw.save_state(sw.STATE_PATH, {"recent": [text, "other"]})
    count = len(sw.load_quotes(sw.QUOTES_PATH))

    sw.remove_quote(text)

    remaining = sw.load_quotes(sw.QUOTES_PATH)
    assert len(remaining) == count - 1
    assert text not in [q["quote"] for q in remaining]
    assert sw.load_state(sw.STATE_PATH)["recent"] == ["other"]


def test_remove_quote_rejects_unknown_quote(project):
    with pytest.raises(ValueError, match="not found"):
        sw.remove_quote("Not by Shakespeare.")


def test_remove_quote_keeps_last_quote(project):
    sw.write_json(sw.QUOTES_PATH, [quote("Only one.")])
    with pytest.raises(ValueError, match="last remaining"):
        sw.remove_quote("Only one.")


# write_json

def test_write_json_leaves_no_temp_files(tmp_path):
    sw.write_json(tmp_path / "data.json", {"a": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]
    assert json.loads((tmp_path / "data.json").read_text()) == {"a": 1}


def test_write_json_failure_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    sw.write_json(path, {"a": 1})

    def broken_dump(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(sw.json, "dump", broken_dump)
    with pytest.raises(RuntimeError):
        sw.write_json(path, {"a": 2})
    monkeypatch.undo()

    assert json.loads(path.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


# tags and filters

def test_load_quotes_rejects_bad_tags(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([{**quote("x"), "tags": "love"}]))
    with pytest.raises(ValueError, match="tags"):
        sw.load_quotes(path)


def test_parse_tags():
    assert sw.parse_tags(" Love, time ,love,, ") == ["love", "time"]
    assert sw.parse_tags(["Grief"]) == ["grief"]
    assert sw.parse_tags("") == []


def test_add_quote_saves_tags_only_when_given(project):
    tagged = sw.add_quote({**quote("Tagged line."), "tags": "Love, time"})
    untagged = sw.add_quote({**quote("Untagged line."), "tags": " "})
    assert tagged["tags"] == ["love", "time"]
    assert "tags" not in untagged


def test_pick_quote_respects_filter_and_its_own_rounds():
    random.seed(1)
    quotes = [{**quote(f"love {i}"), "tags": ["love"]} for i in range(3)] + [quote(f"other {i}") for i in range(3)]
    state = {"recent": ["other 0"], "filter": {"tag": "love"}}
    picks = [sw.pick_quote(quotes, state)["quote"] for _ in range(3)]
    assert sorted(picks) == ["love 0", "love 1", "love 2"]

    sw.pick_quote(quotes, state)  # love quotes exhausted: new round for them only
    assert "other 0" in state["recent"] and len(state["recent"]) == 2

    state["filter"] = {"play": "Macbeth"}  # matches nothing: fall back to all quotes
    assert sw.pick_quote(quotes, state) in quotes


def test_set_filter(project):
    sw.set_filter({"play": "Hamlet"})
    assert sw.get_filter() == {"play": "Hamlet"}
    sw.set_filter(None)
    assert sw.get_filter() is None
    with pytest.raises(ValueError):
        sw.set_filter({"colour": "red"})


def test_real_quotes_tags_are_lowercase_words():
    for q in sw.load_quotes(REAL_QUOTES):
        assert all(t == t.lower() and t.isalpha() for t in q.get("tags", [])), q
