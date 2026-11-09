"""Splitter and text normalisation (T2)."""

import json
import re
from pathlib import Path

import pytest

from pipeline import sentences as S
from pipeline.frontmatter import read_article, split_bytes
from pipeline.textnorm import normalize

REPO = Path(__file__).resolve().parent.parent
ARTICLE_01 = REPO / "source" / "article-01.md"
FIXTURE = REPO / "tests" / "fixtures" / "verify" / "article-fixture.md"
# The example articles ship in the deliverables zip, not in the repository.
needs_article_01 = pytest.mark.skipif(
    not ARTICLE_01.exists(),
    reason="source/article-01.md not present (example data ships in the deliverables zip, not the repo)",
)


def texts(body: str) -> list[str]:
    return [e["text"] for e in S.split_article(body)]


# --- normalisation -----------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("“Hi”, it’s here", "\"Hi\", it's here"),
        ("a b  \t c", "a b c"),
        ("**bold** and *it* and ***both***", "bold and it and both"),
        ("[link text](https://example.com) and ![img](x.png)", "link text and"),
        ("snake_case_name stays, _emph_ goes", "snake_case_name stays, emph goes"),
        ("`code` and <b>tag</b>", "code and tag"),
        ("open **bold", "open bold"),
        (r"escaped \* star and \| pipe", "escaped * star and | pipe"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


# --- sentence splitting --------------------------------------------------------

def test_splits_on_sentence_ends():
    assert texts("One thing. Two things! Three? Four.") == ["One thing.", "Two things!", "Three?", "Four."]


def test_keeps_abbreviations_initials_and_decimals():
    body = "Led by Cody C. Jensen, e.g. a CEO. It is rated 4.9 by U.S. users. No. 1 is here."
    assert texts(body) == ["Led by Cody C. Jensen, e.g. a CEO.", "It is rated 4.9 by U.S. users.", "No. 1 is here."]


def test_closing_quote_stays_with_its_sentence():
    assert texts('He said "it works." Then he left.') == ['He said "it works."', "Then he left."]


def test_lowercase_after_period_does_not_split():
    assert texts("Version 2. then more text.") == ["Version 2. then more text."]


def test_bold_across_sentences_is_removed_before_splitting():
    assert texts("**First one.** Second one.") == ["First one.", "Second one."]


def test_paragraph_over_several_lines_keeps_each_sentence_line():
    body = "First sentence\ncontinues here. Second\nsentence. Third.\n"
    entries = S.split_article(body, line_offset=5)
    assert [(e["text"], e["line"]) for e in entries] == [
        ("First sentence continues here.", 6),
        ("Second sentence.", 7),
        ("Third.", 8),
    ]


def test_headings_set_section_and_are_not_entries():
    body = "# Title\n\nIntro.\n\n## Part two ##\n\nBody.\n\nSetext\n------\n\nLast.\n"
    entries = S.split_article(body)
    assert [(e["section"], e["text"]) for e in entries] == [
        ("Title", "Intro."), ("Part two", "Body."), ("Setext", "Last."),
    ]


def test_lists_quotes_and_markers():
    body = "- A bullet. With two.\n  continued.\n1. **Step one.** Do it.\n2) Step two.\n\n> Quoted text.\n>\n> Second para.\n"
    entries = S.split_article(body)
    assert [(e["kind"], e["text"], e.get("marker")) for e in entries] == [
        ("list_item", "A bullet.", None),
        ("list_item", "With two. continued.", None),
        ("list_item", "Step one.", "1."),
        ("list_item", "Do it.", None),
        ("list_item", "Step two.", "2)"),
        ("quote", "Quoted text.", None),
        ("quote", "Second para.", None),
    ]


def test_tables_keep_cells_by_header():
    body = "| Rank | Name | Note |\n| --- | :--- | ---: |\n| 1 | **Acme** | a \\| b |\n| 2 | Beta |\n"
    entries = S.split_article(body)
    assert entries[0] == {"n": 1, "section": "", "line": 1, "kind": "table_header", "text": "Rank | Name | Note"}
    assert entries[1]["cells"] == {"Rank": "1", "Name": "Acme", "Note": "a | b"}
    assert entries[1]["text"] == "1 | Acme | a | b"
    assert entries[2]["cells"] == {"Rank": "2", "Name": "Beta"}
    assert entries[2]["line"] == 4


def test_table_without_outer_pipes():
    body = "Name | Score\n--- | ---\nAcme | 9\n\nAfter.\n"
    entries = S.split_article(body)
    assert entries[1]["cells"] == {"Name": "Acme", "Score": "9"}
    assert entries[2]["text"] == "After."
    for e in entries:
        assert e["text"] in S.normalized_article(body)


def test_code_fences_comments_and_rules_are_skipped():
    body = "Before.\n\n```\nnot. a sentence.\n```\n<!-- hidden\nnote -->\n\n---\n\nAfter.\n"
    assert texts(body) == ["Before.", "After."]


def test_crlf_line_endings():
    body = "# T\r\n\r\nOne. Two.\r\n\r\n| A | B |\r\n|---|---|\r\n| x | y |\r\n"
    entries = S.split_article(body)
    assert [e["text"] for e in entries] == ["One.", "Two.", "A | B", "x | y"]
    assert entries[3]["line"] == 7


def test_numbering_is_sequential():
    entries = S.split_article(FIXTURE.read_text(encoding="utf-8"))
    assert [e["n"] for e in entries] == list(range(1, len(entries) + 1))


# --- article-01 and the fixture: every entry verbatim ----------------------------

def _raw_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text)


@pytest.mark.parametrize("path", [
    pytest.param(ARTICLE_01, id="article-01", marks=needs_article_01),
    pytest.param(FIXTURE, id="fixture"),
])
def test_every_entry_is_found_verbatim(path):
    meta, body = read_article(path)
    offset = S.body_line_offset(path)
    entries = S.split_article(body, offset)
    assert entries
    art = S.normalized_article(body)
    lines = path.read_text(encoding="utf-8").split("\n")
    for e in entries:
        assert e["text"] in art, f"entry {e['n']} not verbatim: {e['text']!r}"
        # Independent of the normaliser: the entry's words appear, in order, in the
        # raw file starting at its line.
        raw = normalize(" ".join(lines[e["line"] - 1 : e["line"] + 3]))
        pos = 0
        for w in _raw_words(e["text"]):
            found = raw.find(w, pos)
            assert found >= 0, f"entry {e['n']}: word {w!r} not at line {e['line']}"
            pos = found + len(w)


@needs_article_01
def test_article_01_split():
    meta, body = read_article(ARTICLE_01)
    entries = S.split_article(body, S.body_line_offset(ARTICLE_01))
    kinds = [e["kind"] for e in entries]
    assert kinds.count("table_header") == 3
    assert kinds.count("table_row") == 27
    rows = [e for e in entries if e["kind"] == "table_row"]
    assert rows[0]["cells"] == {
        "Rank": "1", "Agency": "Searchbloom", "Score (/50)": "48",
        "Best for": "AI search tied to leads and revenue, run on a published method",
        "Fee": "SEO from $3,000 a month",
    }
    # Line numbers count the front matter: the first table row is on file line 20.
    assert rows[0]["line"] == 20
    lines = ARTICLE_01.read_text(encoding="utf-8").split("\n")
    assert lines[rows[0]["line"] - 1].startswith("| 1 | Searchbloom | 48 |")
    first = entries[0]
    assert first["text"].startswith("The best AI SEO companies in 2026 are (1) Searchbloom")
    assert first["section"] == "Best AI SEO Companies in 2026 (AEO and GEO)"
    assert all(e["text"] and "**" not in e["text"] for e in entries)


# --- the stage -----------------------------------------------------------------

def test_stage_writes_sentences_file(project, monkeypatch):
    from pipeline import stages
    from pipeline.cli import main

    art = project / "source" / "article-fixture.md"
    art.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setitem(stages.STAGES, "scenes", lambda ctx: 2)  # stop after `sentences`, no LLM
    assert main(["run", str(art)], root=project) == 2
    data = json.loads((project / "scenes" / "article-fixture.sentences.json").read_text(encoding="utf-8"))
    _, body = split_bytes(FIXTURE.read_bytes())
    assert data["article"] == "article-fixture"
    assert data["body_sha256"] == S.body_sha256(body.decode("utf-8"))
    assert data["count"] == len(data["sentences"]) == 19
    assert data["sentences"][0]["line"] == 7
    raw = (project / "scenes" / "article-fixture.sentences.json").read_bytes()
    assert b"\r\n" not in raw
