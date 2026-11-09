"""Script and fact sheet (T2)."""

import csv
import io
import json
from pathlib import Path

import pytest

from pipeline import docs, sentences
from pipeline.claims import content_sha256
from pipeline.cli import main
from pipeline.frontmatter import read_article

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"
ARTICLE = FIX / "article-fixture.md"
GOOD = FIX / "good.scenes.json"


@pytest.fixture
def checked(project):
    """Project with the fixture article, its sentences and scenes, verified (--review stop)."""
    art = project / "source" / "article-fixture.md"
    art.write_bytes(ARTICLE.read_bytes())
    meta, body = read_article(art)
    sdata = sentences.build(body, "article-fixture", sentences.body_line_offset(art))
    sentences.write_json(project / "scenes" / "article-fixture.sentences.json", sdata)
    (project / "scenes" / "article-fixture.scenes.json").write_bytes(GOOD.read_bytes())
    assert main(["run", str(art), "--from", "verify", "--review"], root=project) == 0
    return project, art


def out(project, name):
    return project / "output" / "article-fixture" / name


def read_csv(path):
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM for Excel
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))


def test_factsheet_has_one_row_per_claim(checked):
    project, _ = checked
    rows = read_csv(out(project, "factsheet.csv"))
    assert len(rows) == 24
    assert list(rows[0].keys()) == docs.CSV_COLUMNS
    bar = [r for r in rows if r["element"] == "bar"]
    assert [r["text"] for r in bar] == ["Northwind Cycles: 18", "Acme Bike Lab: 16", "Blue Harbor Bikes: 15"]
    assert bar[0]["sentence_numbers"] == "8"
    assert bar[0]["cited_sentences"] == "[8] 1 | Northwind Cycles | 18 | $45"
    assert bar[0]["section"] == "Scores"
    assert bar[0]["line"] == "17"
    assert bar[0]["attributed_to"] == "Northwind Cycles (publisher)"
    assert all(r["timecode"] == "-" for r in rows)
    quote = [r for r in rows if r["element"] == "quote"][0]
    assert quote["attributed_to"] == "Acme Bike Lab (company), via Northwind Cycles"
    # Text without source_ids makes no claim and has no row.
    assert not any(r["text"] == "Read the full guide" for r in rows)


def test_two_cited_sentences_are_both_listed(checked):
    project, _ = checked
    rows = read_csv(out(project, "factsheet.csv"))
    first = rows[0]
    assert first["element"] == "voiceover" and first["scene"] == "1"
    assert first["sentence_numbers"] == "1; 2"
    assert first["cited_sentences"].split("\n")[1] == "[2] Northwind Cycles publishes this guide and ranks itself first."


def test_factsheet_md(checked):
    project, _ = checked
    md = out(project, "factsheet.md").read_text(encoding="utf-8")
    assert md.startswith("# Fact sheet: Best Bike Repair Shops in Springfield (2026)")
    assert "Checker: **PASS**" in md
    assert "## Review warnings\n\nNone." in md
    assert "not yet (filled after the tts stage)" in md
    assert "| 2 | - | bar | Northwind Cycles: 18 |" in md
    # Pipes inside a cited table row are escaped so the Markdown table stays intact.
    assert "[8] 1 \\| Northwind Cycles \\| 18 \\| $45" in md


def test_script_md(checked):
    project, _ = checked
    md = out(project, "script.md").read_text(encoding="utf-8")
    assert "## Scene 1\n\nVisual: card (disclosure)." in md
    assert "Source tag on screen: Source: Northwind Cycles\n" in md
    assert "Source tag on screen: Source: Acme Bike Lab, via Northwind Cycles\n" in md
    assert "- According to Northwind Cycles, each shop was scored out of 20" in md
    assert "- quote: We fix most flats in under 20 minutes." in md
    assert "- Acme Bike Lab: EUR 30" in md
    assert "182 voiceover words, not voiced yet." in md


def test_timecodes_and_spoken_form_after_tts(checked):
    project, art = checked
    # What the tts stage (T4) will do: fill `spoken` and write timing.json.
    path = project / "scenes" / "article-fixture.scenes.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenes"][2]["voiceover"][1]["spoken"] = (
        "Acme Bike Lab charges 30 euros for the same service, and Blue Harbor Bikes charges 60 dollars."
    )
    for s in doc["scenes"]:
        s["duration_s"] = 10.0
    sentences.write_json(path, doc)
    timing = {"total_s": 70.0, "scenes_sha256": content_sha256(doc), "scenes": [
        {"id": k, "start_s": (k - 1) * 10.0, "duration_s": 10.0} for k in range(1, 8)
    ]}
    timing["scenes"][2]["lines"] = [{"start_s": 20.0, "duration_s": 4.0}, {"start_s": 24.25, "duration_s": 6.0}]
    sentences.write_json(project / "audio" / "article-fixture" / "timing.json", timing)

    assert main(["run", str(art), "--from", "docs", "--review"], root=project) == 0
    rows = read_csv(out(project, "factsheet.csv"))
    by_text = {r["text"]: r for r in rows}
    line = by_text["Acme Bike Lab charges EUR 30 for the same service, and Blue Harbor Bikes charges $60."]
    assert line["timecode"] == "0:24.3"
    assert line["spoken"].startswith("Acme Bike Lab charges 30 euros")
    assert by_text["Acme Bike Lab: EUR 30"]["timecode"] == "0:20.0"
    assert by_text["Scores out of 20"]["timecode"] == "0:10.0"
    script = out(project, "script.md").read_text(encoding="utf-8")
    assert "## Scene 3 (0:20.0, 10.0 s)" in script
    assert "  - Spoken as: Acme Bike Lab charges 30 euros" in script
    assert "70.0 s of voiceover." in script
    assert "from audio timing" in out(project, "factsheet.md").read_text(encoding="utf-8")


def test_timing_of_older_scenes_is_ignored(checked, capsys):
    """After the scenes are edited and checked again, the old timing.json must not put
    stale timecodes into the fact sheet under review."""
    project, art = checked
    timing = {"total_s": 70.0, "scenes_sha256": "0" * 64, "scenes": [
        {"id": k, "start_s": (k - 1) * 10.0, "duration_s": 10.0} for k in range(1, 8)
    ]}
    sentences.write_json(project / "audio" / "article-fixture" / "timing.json", timing)
    assert main(["run", str(art), "--from", "docs", "--review"], root=project) == 0
    assert "belongs to an older scenes file" in capsys.readouterr().out
    assert "not yet (filled after the tts stage)" in out(project, "factsheet.md").read_text(encoding="utf-8")
    assert all(r["timecode"] in ("", "-") for r in read_csv(out(project, "factsheet.csv")))


def test_docs_refuses_scenes_changed_after_verify(checked, capsys):
    project, art = checked
    path = project / "scenes" / "article-fixture.scenes.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenes"][2]["voiceover"][0]["text"] = doc["scenes"][2]["voiceover"][0]["text"].replace("$45", "$40")
    sentences.write_json(path, doc)
    assert main(["run", str(art), "--from", "docs"], root=project) == 1
    assert "changed after it was checked" in capsys.readouterr().out


def test_docs_refuses_failed_report(checked, capsys):
    project, art = checked
    rp = out(project, "verify-report.json")
    report = json.loads(rp.read_text(encoding="utf-8"))
    report["verify"]["result"] = "fail"
    sentences.write_json(rp, report)
    assert main(["run", str(art), "--from", "docs"], root=project) == 1
    assert "does not say pass" in capsys.readouterr().out


@pytest.mark.parametrize("seconds, text", [(None, "-"), (0, "0:00.0"), (5.04, "0:05.0"), (65.96, "1:06.0"), (600, "10:00.0")])
def test_timecode(seconds, text):
    assert docs.timecode(seconds) == text


def test_outputs_use_lf_and_utf8(checked):
    project, _ = checked
    for name in ("factsheet.md", "script.md"):
        raw = out(project, name).read_bytes()
        assert b"\r\n" not in raw
        raw.decode("utf-8")
