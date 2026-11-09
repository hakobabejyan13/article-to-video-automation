"""The checker (T2): the good fixture passes, each bad fixture fails with a clear message.

The bad fixtures are the good fixture with one change each, made in `BAD` below, so
they can never drift from the good one.
"""

import copy
import json
from pathlib import Path

import pytest

from pipeline import config, sentences, verify
from pipeline.frontmatter import read_article

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"
ARTICLE = FIX / "article-fixture.md"
GOOD = FIX / "good.scenes.json"


@pytest.fixture(scope="module")
def base():
    meta, body = read_article(ARTICLE)
    sdata = sentences.build(body, "article-fixture", sentences.body_line_offset(ARTICLE))
    doc = json.loads(GOOD.read_text(encoding="utf-8"))
    cfg = config.load()
    # The fixtures and expected messages were written for 150 words per minute; the
    # live value is a measured voice setting (T4), so the checker tests pin their own.
    cfg["speech"]["words_per_minute"] = 150
    return {"meta": meta, "body": body, "sentences": sdata, "doc": doc, "cfg": cfg}


def check(base, doc=None, sdata=None, body=None, meta=None, cfg=None):
    return verify.check_document(
        doc if doc is not None else base["doc"],
        sdata if sdata is not None else base["sentences"],
        body if body is not None else base["body"],
        meta if meta is not None else base["meta"],
        cfg if cfg is not None else base["cfg"],
        article_id="article-fixture",
    )


def scene(doc, sid):
    return doc["scenes"][sid - 1]


def test_good_fixture_passes_with_no_warnings(base):
    rep = check(base)
    assert rep.error_lines() == []
    assert rep.warnings == []
    assert rep.stats == {
        "scenes": 7, "claims": 24, "voiceover_words": 182, "word_range": [150, 225],
        "sentences_cited": 16, "sections_cited": 4,
    }


# --- bad fixtures ----------------------------------------------------------------

def changed_number(d):
    scene(d, 3)["voiceover"][0]["text"] = "Northwind Cycles reports that a basic tune-up costs $40 at Northwind Cycles."


def rounded_number(d):
    scene(d, 2)["voiceover"][1]["text"] = "Northwind Cycles scored 20, Acme Bike Lab scored 16, and Blue Harbor Bikes scored 15."


def changed_number_word(d):
    scene(d, 4)["voiceover"][0]["text"] = (
        "According to Northwind Cycles, eleven shops were visited between March 3 and March 21, 2026."
    )


def ordinal_matched_to_count(d):
    # Sentence 17 has 4 only as a count ("4 of the 12 shops").
    scene(d, 6)["voiceover"][1] = {"text": "Gearbox Garage ranked fourth.", "source_ids": [17], "spoken": None}


def label_with_wrong_value(d):
    scene(d, 2)["visual"]["items"][1] = {"label": "Acme Bike Lab", "value": "18", "source_ids": [8, 9]}


def missing_attribution(d):
    scene(d, 2)["voiceover"][0]["text"] = "Each shop was scored out of 20 on four criteria worth 5 points each."


def missing_disclosure_rank(d):
    scene(d, 1)["voiceover"][0]["text"] = "Northwind Cycles publishes this guide to bike repair shops in Springfield."


def disclosure_not_first(d):
    scene(d, 1)["visual"]["variant"] = "title"


def number_in_no_claim_text(d):
    scene(d, 3)["on_screen"][0]["text"] = "Tune-ups from $45"


def too_short(d):
    del d["scenes"][3:6]
    for k, s in enumerate(d["scenes"], start=1):
        s["id"] = k


def too_long(d):
    scene(d, 6)["voiceover"] += [copy.deepcopy(line) for s in d["scenes"][1:6] for line in s["voiceover"]]


def changed_quote_word(d):
    scene(d, 5)["on_screen"][0]["text"] = "We fix all flats in under 20 minutes."


def wrong_currency(d):
    scene(d, 3)["voiceover"][1]["text"] = "Acme Bike Lab charges $30 for the same service, and Blue Harbor Bikes charges $60."


def unknown_source_id(d):
    scene(d, 2)["on_screen"][0]["source_ids"] = [99]


def uncited_claim_line(d):
    scene(d, 6)["voiceover"][2]["source_ids"] = []


def company_not_named(d):
    scene(d, 5)["voiceover"][0]["text"] = "In its own words, it fixes most flats in under 20 minutes."


def publisher_changed(d):
    d["article"]["publisher"] = "Acme Bike Lab"


def bad_schema(d):
    scene(d, 2)["visual"]["type"] = "pie_chart"
    scene(d, 3)["source_sentence"] = ["not allowed"]


def bad_scene_ids(d):
    scene(d, 2)["id"] = 5


BAD = [
    (changed_number, "counts", "40", 3),
    (rounded_number, "counts", "number(s) 20", 2),
    (changed_number_word, "counts", "11", 4),
    (ordinal_matched_to_count, "ordinals", "appears there only as a count", 6),
    (label_with_wrong_value, "pairing", "'Acme Bike Lab' and value '18'", 2),
    (missing_attribution, "attribution", "publisher claim without attribution", 2),
    (missing_disclosure_rank, "attribution", "say it ranks itself", 1),
    (disclosure_not_first, "attribution", "variant 'disclosure'", 1),
    (number_in_no_claim_text, "no_claim", "has no source_ids but contains a number", 3),
    (too_short, "length", "needs 150-225 words", None),
    (too_long, "length", "Cut about", None),
    (changed_quote_word, "verbatim", "not word for word", 5),
    (wrong_currency, "counts", "wrong currency", 3),
    (unknown_source_id, "schema", "do not exist", 2),
    (uncited_claim_line, "schema", "cites no sentence", 6),
    (company_not_named, "attribution", "must name Acme Bike Lab", 5),
    (publisher_changed, "schema", "front matter says 'Northwind Cycles'", None),
    (bad_schema, "schema", "pie_chart", None),
    (bad_scene_ids, "schema", "1, 2, 3", None),
]


@pytest.mark.parametrize("mutate, check_name, words, scene_id", BAD, ids=[b[0].__name__ for b in BAD])
def test_bad_fixture_fails_clearly(base, mutate, check_name, words, scene_id):
    doc = copy.deepcopy(base["doc"])
    mutate(doc)
    rep = check(base, doc=doc)
    assert not rep.passed
    hits = [e for e in rep.errors if e.check == check_name and words in e.message]
    assert hits, f"expected a {check_name} error mentioning {words!r}, got:\n" + "\n".join(rep.error_lines())
    if scene_id is not None:
        assert hits[0].scene == scene_id
    # Every other check stays quiet: one change gives errors of one kind only
    # (the length check may also move when lines are added or removed).
    assert {e.check for e in rep.errors} <= {check_name, "length"}


def test_changed_word_in_sentences_file_fails(base):
    sdata = copy.deepcopy(base["sentences"])
    sdata["sentences"][3]["text"] = sdata["sentences"][3]["text"].replace("basic", "cheap")
    rep = check(base, sdata=sdata)
    assert [e.check for e in rep.errors] == ["verbatim"]
    assert "sentence 4 is not found word for word" in rep.errors[0].message


def test_stale_sentences_file_fails(base):
    rep = check(base, body=base["body"].replace("Riverside", "Hillside"))
    assert any("older than the article" in e.message for e in rep.errors)


def test_rank_column_supports_an_ordinal(base):
    doc = copy.deepcopy(base["doc"])
    scene(doc, 6)["voiceover"][1] = {"text": "Gearbox Garage ranked fourth.", "source_ids": [11], "spoken": None}
    rep = check(base, doc=doc)
    assert rep.passed, rep.error_lines()


def test_list_marker_supports_an_ordinal(base):
    doc = copy.deepcopy(base["doc"])
    scene(doc, 6)["voiceover"][1]["text"] = (
        "The guide's first step is to ask for a written quote, since prices at 4 of the 12 shops were not posted."
    )
    rep = check(base, doc=doc)
    assert rep.passed, rep.error_lines()


def test_not_promotional_skips_attribution(base):
    doc = copy.deepcopy(base["doc"])
    doc["article"]["promotional"] = False
    missing_attribution(doc)
    missing_disclosure_rank(doc)
    meta = dict(base["meta"], promotional=False)
    rep = check(base, doc=doc, meta=meta)
    assert rep.passed, rep.error_lines()


def test_word_range_follows_config(base):
    cfg = copy.deepcopy(base["cfg"])
    cfg["video"]["target_seconds"] = [30, 45]
    rep = check(base, cfg=cfg)
    assert [e.check for e in rep.errors] == ["length"]
    assert "30-45 s at 150 words per minute needs 75-112 words" in rep.errors[0].message


def test_review_warnings(base):
    doc = copy.deepcopy(base["doc"])
    scene(doc, 2)["voiceover"][1]["text"] += " That means Northwind Cycles is the trusted choice."
    rep = check(base, doc=doc)
    assert rep.passed, rep.error_lines()
    msgs = [w.text() for w in rep.warnings]
    assert any("[inference]" in m and "'that means'" in m for m in msgs)
    assert any("[judging]" in m and "'trusted'" in m for m in msgs)


def test_coverage_warning(base):
    cfg = copy.deepcopy(base["cfg"])
    cfg["review_warnings"]["min_sections"] = 5
    rep = check(base, cfg=cfg)
    assert rep.passed
    assert [w.check for w in rep.warnings] == ["coverage"]


def test_messages_name_scene_and_element(base):
    doc = copy.deepcopy(base["doc"])
    changed_number(doc)
    rep = check(base, doc=doc)
    line = rep.error_lines()[0]
    assert line.startswith("[counts] scene 3 voiceover[0]: number(s) 40")
    assert "they state: 9, 12, 45" in line


def test_garbage_input_never_raises(base):
    for doc in ({}, [], {"article": {}, "scenes": "x"}, {"scenes": [None]}):
        rep = check(base, doc=doc)
        assert not rep.passed
        assert all(e.check == "schema" for e in rep.errors)


# --- the stage --------------------------------------------------------------------

def _setup(project, doc=None):
    art = project / "source" / "article-fixture.md"
    art.write_bytes(ARTICLE.read_bytes())
    meta, body = read_article(art)
    sdata = sentences.build(body, "article-fixture", sentences.body_line_offset(art))
    sentences.write_json(project / "scenes" / "article-fixture.sentences.json", sdata)
    scenes_doc = doc if doc is not None else json.loads(GOOD.read_text(encoding="utf-8"))
    sentences.write_json(project / "scenes" / "article-fixture.scenes.json", scenes_doc)
    return art


def test_stage_pass_writes_report(project, capsys):
    from pipeline.cli import main

    art = _setup(project)
    # --from verify runs verify, docs, then stops at --review.
    assert main(["run", str(art), "--from", "verify", "--review"], root=project) == 0
    out = capsys.readouterr().out
    assert "PASS: 7 scenes, 24 claims, 182 voiceover words" in out
    report = json.loads((project / "output" / "article-fixture" / "verify-report.json").read_text(encoding="utf-8"))
    assert report["article"] == "article-fixture"
    assert report["verify"]["result"] == "pass"
    assert report["verify"]["errors"] == []
    assert len(report["verify"]["scenes_sha256"]) == 64


def test_stage_fail_exits_1_and_lists_errors(project, capsys):
    from pipeline.cli import main

    doc = json.loads(GOOD.read_text(encoding="utf-8"))
    changed_number(doc)
    art = _setup(project, doc)
    assert main(["run", str(art), "--from", "verify"], root=project) == 1
    out = capsys.readouterr().out
    assert "FAIL: 1 error(s)" in out
    assert "[counts] scene 3 voiceover[0]" in out
    report = json.loads((project / "output" / "article-fixture" / "verify-report.json").read_text(encoding="utf-8"))
    assert report["verify"]["result"] == "fail"
    assert report["verify"]["errors"][0]["check"] == "counts"
    assert not (project / "output" / "article-fixture" / "factsheet.md").exists()


def test_stage_invalid_json_fails(project, capsys):
    from pipeline.cli import main

    art = _setup(project)
    (project / "scenes" / "article-fixture.scenes.json").write_bytes(b"{not json")
    assert main(["run", str(art), "--from", "verify"], root=project) == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_report_keeps_other_sections(project):
    path = project / "output" / "a" / "verify-report.json"
    sentences.write_json(path, {"article": "a", "custom": 1, "check": {"result": "pass"}})
    verify.write_report(path, {"article": "a", "verify": {"result": "pass"}})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"article": "a", "custom": 1, "verify": {"result": "pass"}}


def test_pipeline_code_names_no_article_or_publisher():
    """CLAUDE.md design rule: nothing in pipeline/ is specific to one article."""
    root = Path(__file__).resolve().parent.parent / "pipeline"
    banned = ["searchbloom", "article-01", "northwind", "the seo works", "tinuiti"]
    for f in root.rglob("*"):
        if f.suffix in {".py", ".yaml", ".json", ".md"} and "__pycache__" not in f.parts:
            text = f.read_text(encoding="utf-8").lower()
            for word in banned:
                assert word not in text, f"{f.relative_to(root)} mentions {word!r}"


def test_possessive_label_matches_the_bare_name():
    from pipeline.verify import label_in

    text = "across 68,631 AI answers Acme tracked in its own category, its own website was 8.9%"
    assert label_in("Acme's own website", text)
    assert not label_in("Zenith's own website", text)
