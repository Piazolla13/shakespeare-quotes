"""
Check quotes.json against the Project Gutenberg text of the Complete Works (eBook #100).

For every quote, finds the closest passage in the plays and reports whether the wording matches,
who speaks it there, and in which play, act and scene. Nothing is changed; fix quotes.json by hand.

    .venv/bin/python tools/check_quotes.py              # downloads the text once and caches it
    .venv/bin/python tools/check_quotes.py --source pg100.txt
    .venv/bin/python tools/check_quotes.py --write-refs   # also save act/scene into quotes.json

Exit status is 1 if any quote has a wording, speaker or play problem.
"""

import argparse
import difflib
import json
import re
import sys
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
QUOTES_PATH = PROJECT_DIR / "quotes.json"
SOURCE_URL = "https://www.gutenberg.org/cache/epub/100/pg100.txt"
CACHE_PATH = Path.home() / "Library" / "Caches" / "shakespeare-quotes" / "pg100.txt"

# Play names used in quotes.json -> title line in the Gutenberg text
PLAY_TITLES = {
    "All's Well That Ends Well": "ALL’S WELL THAT ENDS WELL",
    "Antony and Cleopatra": "THE TRAGEDY OF ANTONY AND CLEOPATRA",
    "As You Like It": "AS YOU LIKE IT",
    "The Comedy of Errors": "THE COMEDY OF ERRORS",
    "Coriolanus": "THE TRAGEDY OF CORIOLANUS",
    "Cymbeline": "CYMBELINE",
    "Hamlet": "THE TRAGEDY OF HAMLET, PRINCE OF DENMARK",
    "Henry IV, Part 1": "THE FIRST PART OF KING HENRY THE FOURTH",
    "Henry IV, Part 2": "THE SECOND PART OF KING HENRY THE FOURTH",
    "Henry V": "THE LIFE OF KING HENRY THE FIFTH",
    "Henry VI, Part 1": "THE FIRST PART OF HENRY THE SIXTH",
    "Henry VI, Part 2": "THE SECOND PART OF KING HENRY THE SIXTH",
    "Henry VI, Part 3": "THE THIRD PART OF KING HENRY THE SIXTH",
    "Henry VIII": "KING HENRY THE EIGHTH",
    "King John": "THE LIFE AND DEATH OF KING JOHN",
    "Julius Caesar": "THE TRAGEDY OF JULIUS CAESAR",
    "King Lear": "THE TRAGEDY OF KING LEAR",
    "Love's Labour's Lost": "LOVE’S LABOUR’S LOST",
    "Macbeth": "THE TRAGEDY OF MACBETH",
    "Measure for Measure": "MEASURE FOR MEASURE",
    "The Merchant of Venice": "THE MERCHANT OF VENICE",
    "The Merry Wives of Windsor": "THE MERRY WIVES OF WINDSOR",
    "A Midsummer Night's Dream": "A MIDSUMMER NIGHT’S DREAM",
    "Much Ado About Nothing": "MUCH ADO ABOUT NOTHING",
    "Othello": "THE TRAGEDY OF OTHELLO, THE MOOR OF VENICE",
    "Pericles": "PERICLES, PRINCE OF TYRE",
    "Richard II": "KING RICHARD THE SECOND",
    "Richard III": "KING RICHARD THE THIRD",
    "Romeo and Juliet": "THE TRAGEDY OF ROMEO AND JULIET",
    "The Taming of the Shrew": "THE TAMING OF THE SHREW",
    "The Tempest": "THE TEMPEST",
    "Timon of Athens": "THE LIFE OF TIMON OF ATHENS",
    "Titus Andronicus": "THE TRAGEDY OF TITUS ANDRONICUS",
    "Troilus and Cressida": "TROILUS AND CRESSIDA",
    "Twelfth Night": "TWELFTH NIGHT; OR, WHAT YOU WILL",
    "The Two Gentlemen of Verona": "THE TWO GENTLEMEN OF VERONA",
    "The Two Noble Kinsmen": "THE TWO NOBLE KINSMEN",
    "The Winter's Tale": "THE WINTER’S TALE",
}
TITLE_TO_PLAY = {title: play for play, title in PLAY_TITLES.items()}

CLOSE_ENOUGH = 0.85  # word-level similarity below this counts as "not found"
SPEAKER_LINE = re.compile(r"^[A-Z][A-Z0-9 ,’'&-]*\.$")
# Speaker line followed by a stage direction: "CLOWN. [_sings._]", "BALTHASAR [sings.]"
SPEAKER_WITH_DIRECTION = re.compile(r"^([A-Z][A-Z0-9 ,’'&-]*?)\.?\s*(\[[^\]]*\]|\([^)]*\))$")
ACT_LINE = re.compile(r"^ACT ([IVX]+)\b")
SCENE_LINE = re.compile(r"^SCENE ([IVX]+)\.")
STAGE_DIRECTION = re.compile(r"\[_.*?_\]")
# Words that differ only in title or form of address ("King Henry" vs "HENRY")
SPEAKER_FILLER = {"the", "of", "king", "queen", "prince", "princess", "duke", "lady", "lord", "first",
                  "second", "third", "friar", "sir"}
# Speech prefixes in the Gutenberg text that name a role rather than the character
SPEAKER_ALIASES = {
    ("Twelfth Night", "DUKE"): "Orsino",
    ("Twelfth Night", "CLOWN"): "Feste",
    ("Macbeth", "ALL"): "The Witches",
    ("Hamlet", "KING"): "Claudius",
    ("Hamlet", "QUEEN"): "Gertrude",
    ("Romeo and Juliet", "FRIAR LAWRENCE"): "Friar Laurence",
}
# Elided forms, so "under ’t" matches "under it"
ELISIONS = {"th'": "the", "'t": "it", "i'": "in", "o'": "of", "ne'er": "never", "e'er": "ever"}


def normalize_words(text):
    text = unicodedata.normalize("NFKD", text.replace("’", "'").replace("‘", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"(?<=[a-z])'t\b", " 't", text)  # "under't" -> "under 't"
    text = re.sub(r"(?<=[a-z])'d\b", "ed", text)   # "strain'd" -> "strained"
    words = re.findall(r"'?[a-z]+(?:'[a-z]+)*'?", text)
    return [ELISIONS.get(w, w.strip("'")) for w in words]


def load_source(source):
    if source:
        return Path(source).read_text(encoding="utf-8-sig")
    if not CACHE_PATH.exists():
        print(f"Downloading {SOURCE_URL} …", file=sys.stderr)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
            CACHE_PATH.write_bytes(response.read())
    return CACHE_PATH.read_text(encoding="utf-8-sig")


def index_works(text):
    """Word list of the plays, each word tagged with (play, act, scene, speaker, source line)."""
    lines = [line.strip() for line in text.splitlines()]
    start = next(i for i, line in enumerate(lines) if line.startswith("*** START"))
    end = next(i for i, line in enumerate(lines) if line.startswith("*** END"))
    lines = lines[start + 1:end]

    # Each title appears twice: in the contents list and as the play's heading; keep the last
    heading_line = {}
    for i, line in enumerate(lines):
        if line in TITLE_TO_PLAY:
            heading_line[TITLE_TO_PLAY[line]] = i
    headings = {i: play for play, i in heading_line.items()}

    words, where = [], []
    play = act = scene = speaker = None
    for i, line in enumerate(lines):
        if i in headings:
            play, act, scene, speaker = headings[i], None, None, None
            continue
        if play is None or not line:
            continue
        if ACT_LINE.match(line):
            act = ACT_LINE.match(line).group(1)
            continue
        if SCENE_LINE.match(line):
            scene = SCENE_LINE.match(line).group(1)
            continue
        if SPEAKER_LINE.match(line):
            speaker = line.rstrip(".")
            continue
        if SPEAKER_WITH_DIRECTION.match(line):
            speaker = SPEAKER_WITH_DIRECTION.match(line).group(1)
            continue
        for word in normalize_words(STAGE_DIRECTION.sub(" ", line)):
            words.append(word)
            where.append((play, act, scene, speaker, line))
    return words, where


def best_match(quote_words, words, positions, where=None, play=None):
    """(similarity, start index) of the passage most similar to the quote.

    Equally good matches (a line used in two plays) prefer the given play.
    """
    n = len(quote_words)
    # Anchor on the quote's rarest words, then compare a window around each occurrence
    anchors = sorted(set(quote_words), key=lambda w: len(positions.get(w, ())) or 10**9)[:3]
    best, best_key = (0.0, None), (0.0, False)
    for anchor in anchors:
        offset = quote_words.index(anchor)
        for pos in positions.get(anchor, ()):
            start = max(0, pos - offset - 2)
            window = words[start:start + n + 4]
            matcher = difflib.SequenceMatcher(None, quote_words, window, autojunk=False)
            ratio = matcher.ratio() * (len(window) + n) / (2 * n)  # score against the quote length
            blocks = [b for b in matcher.get_matching_blocks() if b.size]
            match_start = start + (blocks[0].b - blocks[0].a if blocks else 0)
            in_play = where is not None and where[min(match_start, len(where) - 1)][0] == play
            key = (round(min(ratio, 1.0), 6), in_play)
            if key > best_key:
                best, best_key = (key[0], match_start), key
    return best


def speaker_matches(character, speaker, play):
    if SPEAKER_ALIASES.get((play, speaker)) == character:
        return True
    ours, theirs = set(normalize_words(character)), set(normalize_words(speaker or ""))
    if ours and theirs and theirs <= ours:  # "KING" for "King Henry"
        return True
    ours, theirs = ours - SPEAKER_FILLER, theirs - SPEAKER_FILLER
    return bool(ours) and bool(theirs) and (ours <= theirs or theirs <= ours)


def check(quotes, words, where, write_refs=False):
    """Print a report; returns the number of quotes with problems.

    With write_refs, quotes without problems get "act" / "scene" set from the text (in place).
    """
    positions = defaultdict(list)
    for i, word in enumerate(words):
        positions[word].append(i)

    problems = 0
    for q in quotes:
        quote_words = normalize_words(q["quote"])
        ratio, start = best_match(quote_words, words, positions, where, q["play"])
        found = start is not None and ratio >= CLOSE_ENOUGH
        issues = []
        if q["play"] not in PLAY_TITLES:
            issues.append(f"unknown play name {q['play']!r}")
        if not found:
            issues.append("wording not found")
            status = "MISSING"
        else:
            status = "EXACT" if ratio >= 0.999 else f"CLOSE {ratio:.2f}"
            play, act, scene, speaker, _ = where[start]
            if play != q["play"]:
                issues.append(f"found in {play}")
            if not speaker_matches(q["character"], speaker, play):
                issues.append(f"spoken by {speaker}")
            if "act" in q and (q["act"], q.get("scene")) != (act, scene):
                issues.append(f"found in Act {act}, Scene {scene}, not Act {q['act']}, Scene {q.get('scene')}")
        problems += bool(issues)

        print(f"{'!!' if issues else 'ok'} {status:<10} {q['quote'][:60]}")
        if found:
            print(f"   {play} {act or '?'}.{scene or '?'} — {speaker}")
            if status != "EXACT":
                end = min(start + len(quote_words), len(where) - 1)
                source_lines = list(dict.fromkeys(w[4] for w in where[start:end + 1]))
                print(f"   text: {' / '.join(source_lines)}")
            if write_refs and not issues and act and scene:
                q["act"], q["scene"] = act, scene
        for issue in issues:
            print(f"   -> {issue} (quotes.json says {q['character']}, {q['play']})")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--source", help="path to a local copy of pg100.txt")
    parser.add_argument("--quotes", default=QUOTES_PATH, help="quotes file to check")
    parser.add_argument("--write-refs", action="store_true",
                        help="save act and scene into the quotes file for quotes without problems")
    args = parser.parse_args()

    with open(args.quotes, encoding="utf-8") as f:
        quotes = json.load(f)
    words, where = index_works(load_source(args.source))
    problems = check(quotes, words, where, args.write_refs)
    if args.write_refs:
        with open(args.quotes, "w", encoding="utf-8") as f:
            json.dump(quotes, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Wrote act/scene references to {args.quotes}")
    print(f"\n{len(quotes) - problems} of {len(quotes)} quotes OK, {problems} to review")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
