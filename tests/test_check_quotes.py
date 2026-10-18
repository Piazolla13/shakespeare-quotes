import importlib.util

import pytest

import shakespeare_wallpaper as sw

spec = importlib.util.spec_from_file_location("check_quotes", sw.PROJECT_DIR / "tools" / "check_quotes.py")
cq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cq)

# Miniature of the Gutenberg layout: header, contents list, then the plays
SOURCE = """\
The Project Gutenberg eBook
*** START OF THE PROJECT GUTENBERG EBOOK ***
                    Contents
    THE SONNETS
    THE TRAGEDY OF MACBETH
    TWELFTH NIGHT; OR, WHAT YOU WILL

THE SONNETS

                    18

Shall I compare thee to a summer’s day?
Thou art more lovely and more temperate:

                    19

Devouring Time, blunt thou the lion’s paws,

THE TRAGEDY OF MACBETH

ACT I

SCENE V. Inverness. A Room in Macbeth’s Castle.

LADY MACBETH.
[_Aside._] Your hand, your tongue: look like the innocent flower,
But be the serpent under’t.

ACT V

SCENE V. Dunsinane. Within the castle.

MACBETH.
Life’s but a walking shadow; a poor player,
That struts and frets his hour upon the stage.

TWELFTH NIGHT; OR, WHAT YOU WILL

ACT I

SCENE I. An Apartment in the Duke’s Palace.

DUKE.
If music be the food of love, play on,
Give me excess of it.
*** END OF THE PROJECT GUTENBERG EBOOK ***
"""


@pytest.fixture(scope="module")
def works():
    return cq.index_works(SOURCE)


def run(quotes, works, capsys):
    problems = cq.check(quotes, *works)
    return problems, capsys.readouterr().out


def test_normalize_handles_elisions_and_spelling():
    assert cq.normalize_words("Th’ innocent flower, under’t; strain’d") == \
        ["the", "innocent", "flower", "under", "it", "strained"]


def test_index_skips_contents_and_tracks_location(works):
    words, where = works
    play, act, scene, speaker, _, sonnet = where[words.index("serpent")]
    assert (play, act, scene, speaker) == ("Macbeth", "I", "V", "LADY MACBETH")
    assert "aside" not in words  # stage directions are dropped


def test_matching_quotes_pass(works, capsys):
    quotes = [
        {"quote": "Look like the innocent flower, but be the serpent under it.",
         "play": "Macbeth", "character": "Lady Macbeth"},
        {"quote": "If music be the food of love, play on.", "play": "Twelfth Night", "character": "Orsino"},
    ]
    problems, out = run(quotes, works, capsys)
    assert problems == 0
    assert "Macbeth I.V — LADY MACBETH" in out


@pytest.mark.parametrize("quote, expected", [
    ({"quote": "Life's but a walking shadow, a poor player.", "play": "Macbeth", "character": "Banquo"},
     "spoken by MACBETH"),
    ({"quote": "Life's but a walking shadow, a poor player.", "play": "Twelfth Night", "character": "Macbeth"},
     "found in Macbeth"),
    ({"quote": "Something is rotten in the state of Denmark.", "play": "Hamlet", "character": "Marcellus"},
     "wording not found"),
    ({"quote": "If music be the food of love, play on.", "play": "Twelfth Nite", "character": "Orsino"},
     "unknown play name"),
])
def test_problems_are_reported(works, capsys, quote, expected):
    problems, out = run([quote], works, capsys)
    assert problems == 1
    assert expected in out


def test_write_refs_fills_act_and_scene_only_for_good_quotes(works, capsys):
    good = {"quote": "If music be the food of love, play on.", "play": "Twelfth Night", "character": "Orsino"}
    bad = {"quote": "If music be the food of love, play on.", "play": "Twelfth Night", "character": "Viola"}
    cq.check([good, bad], *works, write_refs=True)
    capsys.readouterr()
    assert (good["act"], good["scene"]) == ("I", "I")
    assert "act" not in bad


def test_wrong_act_or_scene_is_reported(works, capsys):
    quote = {"quote": "Life's but a walking shadow, a poor player.", "play": "Macbeth",
             "character": "Macbeth", "act": "V", "scene": "III"}
    problems, out = run([quote], works, capsys)
    assert problems == 1
    assert "found in Act V, Scene V, not Act V, Scene III" in out


def sonnet(text, number=None):
    q = {"quote": text, "play": "Sonnets", "character": "Shakespeare"}
    return {**q, "sonnet": number} if number else q


def test_sonnets_are_found_with_their_number(works, capsys):
    good = sonnet("Shall I compare thee to a summer's day?")
    problems, out = run([good, sonnet("Devouring Time, blunt thou the lion's paws.", 19)], works, capsys)
    assert problems == 0
    assert "Sonnet 18" in out and "Sonnet 19" in out


def test_wrong_sonnet_number_is_reported(works, capsys):
    problems, out = run([sonnet("Shall I compare thee to a summer's day?", 116)], works, capsys)
    assert problems == 1
    assert "found in Sonnet 18, not Sonnet 116" in out


def test_write_refs_sets_sonnet_number(works, capsys):
    q = sonnet("Thou art more lovely and more temperate.")
    cq.check([q], *works, write_refs=True)
    capsys.readouterr()
    assert q["sonnet"] == 18 and "act" not in q


@pytest.mark.parametrize("character, speaker, play", [
    ("King Henry", "KING", "Henry V"),
    ("King Henry IV", "KING", "Henry IV, Part 2"),
    ("Prince of Morocco", "MOROCCO", "The Merchant of Venice"),
    ("Orsino", "DUKE", "Twelfth Night"),
])
def test_speaker_name_variants(character, speaker, play):
    assert cq.speaker_matches(character, speaker, play)


def test_real_quotes_use_known_play_names():
    for q in sw.load_quotes(sw.QUOTES_PATH):
        assert q["play"] in cq.PLAY_TITLES, q["play"]
