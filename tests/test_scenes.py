"""`scenes` stage (pipeline/scenes.py): prompt, assembly, retry loop, exit codes.

The LLM is replaced by a fake that returns recorded-style answers, so no network is
used. The answers are built from the made-up fixture article and its good scenes
file (tests/fixtures/verify/).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from pipeline import config, exitcodes, llm, scenes, sentences
from pipeline.frontmatter import read_article

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"
ARTICLE = FIX / "article-fixture.md"
GOOD = FIX / "good.scenes.json"


def load_fixture():
    meta, body = read_article(ARTICLE)
    sdata = sentences.build(body, "article-fixture", sentences.body_line_offset(ARTICLE))
    good = json.loads(GOOD.read_text(encoding="utf-8"))
    return meta, body, sdata, good


def llm_answer(doc: dict) -> str:
    """What the LLM returns: only the scenes, without the fields code fills in."""
    out = []
    for sc in copy.deepcopy(doc["scenes"]):
        sc.pop("duration_s", None)
        for line in sc["voiceover"]:
            line.pop("spoken", None)
        out.append(sc)
    return json.dumps({"scenes": out})


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt, cfg_llm, schema=None, log=print, **kw):
        self.prompts.append(prompt)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return llm.LLMResult(text=a, provider="gemini", model="fake-model", seconds=0.1,
                             usage={"totalTokenCount": 10})


@pytest.fixture
def cfg():
    c = config.load()
    c["speech"]["words_per_minute"] = 150  # fixtures were written for 150 (see test_verify.py)
    return c


# ---------------------------------------------------------------- prompt

def test_prompt_is_filled_and_promotional_block_kept(cfg):
    meta, body, sdata, _ = load_fixture()
    p = scenes.build_prompt(sdata, meta, cfg)
    assert "{{" not in p and "<!--" not in p
    assert "This article is promotional: Northwind Cycles" in p
    assert '"according to Northwind Cycles"' in p
    assert "not marked promotional" not in p
    lo, hi = 150, 225
    assert f"{lo}-{hi} words" in p
    for e in sdata["sentences"]:
        assert scenes.format_entry(e) in p
    assert f"({len(sdata['sentences'])} entries)" in p


def test_prompt_for_a_non_promotional_article(cfg):
    meta, body, sdata, _ = load_fixture()
    p = scenes.build_prompt(sdata, {**meta, "promotional": False}, cfg)
    assert "not marked promotional" in p and "This article is promotional" not in p


def test_prompt_lists_kinds_markers_and_table_rows():
    e = {"n": 7, "section": "How", "kind": "list_item", "marker": "2.", "text": "Ask first."}
    assert scenes.format_entry(e) == "[7] (How) list item 2.: Ask first."
    e = {"n": 8, "section": "T", "kind": "table_row", "text": "1 | A | 48"}
    assert scenes.format_entry(e) == "[8] (T) table row: 1 | A | 48"


def test_article_text_with_braces_is_not_a_placeholder(cfg):
    meta, body, sdata, _ = load_fixture()
    sdata = copy.deepcopy(sdata)
    sdata["sentences"][0]["text"] = "A {{word_lo}} in the article."
    p = scenes.build_prompt(sdata, meta, cfg)
    assert "A {{word_lo}} in the article." in p


def test_template_has_no_unknown_placeholders(cfg):
    meta, body, sdata, _ = load_fixture()
    with pytest.raises(KeyError):
        scenes.build_prompt(sdata, meta, cfg, template="Hello {{nope}}\n")


def test_llm_schema_follows_the_main_schema():
    main = json.loads(scenes.SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]
    s = scenes.llm_schema()
    scene = s["properties"]["scenes"]["items"]
    vis = scene["properties"]["visual"]["properties"]
    assert vis["type"]["enum"] == main["visual"]["properties"]["type"]["enum"]
    assert vis["variant"]["enum"] == main["visual"]["properties"]["variant"]["enum"]
    role = scene["properties"]["on_screen"]["items"]["properties"]["role"]["enum"]
    assert role == main["on_screen_text"]["properties"]["role"]["enum"]
    # the LLM never supplies the article block or the fields later stages fill
    assert "article" not in s["properties"]
    assert "spoken" not in scene["properties"]["voiceover"]["items"]["properties"]
    assert "duration_s" not in scene["properties"]

    def all_objects_closed(x):
        if isinstance(x, dict):
            if x.get("type") == "object":
                assert x.get("additionalProperties") is False
            for v in x.values():
                all_objects_closed(v)
        elif isinstance(x, list):
            for v in x:
                all_objects_closed(v)

    all_objects_closed(s)


# ---------------------------------------------------------------- assembling

def test_assemble_copies_front_matter_not_llm_fields():
    meta, body, sdata, good = load_fixture()
    answer = json.loads(llm_answer(good))
    answer["scenes"][0]["voiceover"][0]["spoken"] = "made up by the model"
    answer["scenes"][1]["visual"]["variant"] = "title"  # meaningless off a card
    answer["scenes"][1]["visual"]["icon"] = ""
    doc = scenes.assemble(answer, "article-fixture", scenes.article_title(body, meta, "x"), meta)
    assert doc["article"] == {"id": "article-fixture", "title": "Best Bike Repair Shops in Springfield (2026)",
                              "publisher": "Northwind Cycles", "promotional": True}
    assert doc["scenes"][0]["voiceover"][0]["spoken"] is None
    assert all(sc["duration_s"] is None for sc in doc["scenes"])
    assert "variant" not in doc["scenes"][1]["visual"] and "icon" not in doc["scenes"][1]["visual"]
    assert doc["scenes"] == good["scenes"] or doc["scenes"][2:] == good["scenes"][2:]


def test_good_answer_assembles_to_the_good_fixture():
    meta, body, sdata, good = load_fixture()
    doc = scenes.assemble(json.loads(llm_answer(good)), "article-fixture",
                          scenes.article_title(body, meta, "x"), meta)
    assert doc == good


def test_title_from_front_matter_wins():
    assert scenes.article_title("# Heading\n", {"title": "Given"}, "x") == "Given"
    assert scenes.article_title("no heading", {}, "fallback-id") == "fallback-id"


@pytest.mark.parametrize("text", ['```json\n{"scenes": []}\n```', '{"scenes": []}', "[]"])
def test_parse_answer_accepts_fences_and_bare_lists(text):
    assert scenes.parse_answer(text) == {"scenes": []}


@pytest.mark.parametrize("text", ["not json", '{"other": 1}'])
def test_parse_answer_rejects(text):
    with pytest.raises(scenes.AnswerError):
        scenes.parse_answer(text)


# ---------------------------------------------------------------- the loop

def test_retry_sends_errors_back_then_passes(cfg, monkeypatch):
    meta, body, sdata, good = load_fixture()
    bad = copy.deepcopy(good)
    bad["scenes"][1]["visual"]["items"][0]["value"] = "19"  # the article says 18
    fake = FakeLLM(["not json at all", llm_answer(bad), llm_answer(good)])
    monkeypatch.setattr(llm, "generate", fake)
    doc, rep, attempts = scenes.generate_scenes(sdata, body, meta, cfg, "article-fixture", log=lambda m: None)
    assert rep.passed and attempts == 3 and doc == good
    assert "## The checker rejected it" in fake.prompts[1] and "not valid JSON" in fake.prompts[1]
    assert "not json at all" in fake.prompts[1]
    assert re.search(r"\[(counts|pairing)\] scene 2", fake.prompts[2])
    assert fake.prompts[0] in fake.prompts[2]  # each retry repeats the full base prompt


def test_loop_gives_up_after_max_retries(cfg, monkeypatch):
    meta, body, sdata, good = load_fixture()
    bad = copy.deepcopy(good)
    bad["scenes"][0]["voiceover"][0]["text"] = "Hello there, this is about bikes."
    cfg = copy.deepcopy(cfg)
    cfg["llm"]["max_retries"] = 1
    fake = FakeLLM([llm_answer(bad)] * 2)
    monkeypatch.setattr(llm, "generate", fake)
    doc, rep, attempts = scenes.generate_scenes(sdata, body, meta, cfg, "article-fixture", log=lambda m: None)
    assert not rep.passed and attempts == 2 and len(fake.prompts) == 2
    assert any("[attribution]" in e for e in rep.error_lines())


# ---------------------------------------------------------------- the stage

def _project(project: Path) -> Path:
    art = project / "source" / "article-fixture.md"
    art.write_bytes(ARTICLE.read_bytes())
    return art


def test_stage_pass_then_review_stop(project, monkeypatch, capsys):
    from pipeline.cli import main

    _, _, _, good = load_fixture()
    monkeypatch.setattr(llm, "generate", FakeLLM([llm_answer(good)]))
    art = _project(project)
    assert main(["run", str(art), "--review"], root=project) == exitcodes.OK
    out = capsys.readouterr().out
    assert "checker: PASS" in out and "Stopped for review" in out
    written = json.loads((project / "scenes" / "article-fixture.scenes.json").read_text(encoding="utf-8"))
    assert written == good
    raw = (project / "scenes" / "article-fixture.scenes.json").read_bytes()
    assert b"\r\n" not in raw
    llm_dir = project / "output" / "article-fixture" / "llm"
    assert (llm_dir / "attempt-1.txt").exists() and (llm_dir / "run.log").exists()
    report = json.loads((project / "output" / "article-fixture" / "verify-report.json").read_text(encoding="utf-8"))
    assert report["verify"]["result"] == "pass"
    assert (project / "output" / "article-fixture" / "factsheet.md").exists()


def test_stage_checker_failure_exits_1_and_keeps_the_file(project, monkeypatch, capsys):
    from pipeline.cli import main

    _, _, _, good = load_fixture()
    bad = copy.deepcopy(good)
    bad["scenes"][1]["visual"]["items"][0]["value"] = "19"
    monkeypatch.setattr(llm, "generate", FakeLLM([llm_answer(bad)] * 4))
    art = _project(project)
    assert main(["run", str(art), "--review"], root=project) == exitcodes.CHECK_FAILED
    out = capsys.readouterr().out
    assert "FAIL: the checker still fails after 4 attempt(s)" in out
    assert (project / "scenes" / "article-fixture.scenes.json").exists()
    report = json.loads((project / "output" / "article-fixture" / "verify-report.json").read_text(encoding="utf-8"))
    assert report["verify"]["result"] == "fail"
    assert not (project / "output" / "article-fixture" / "factsheet.md").exists()


def test_stage_provider_unavailable_exits_3(project, monkeypatch, capsys):
    from pipeline.cli import main

    monkeypatch.setattr(llm, "generate", FakeLLM([llm.ProviderUnavailable("every gemini model failed: m1: HTTP 503")]))
    art = _project(project)
    assert main(["run", str(art)], root=project) == exitcodes.PROVIDER
    out = capsys.readouterr().out
    assert "every gemini model failed" in out and "llm.fallback_models" in out
    assert not (project / "scenes" / "article-fixture.scenes.json").exists()


def test_stage_setup_error_exits_2(project, monkeypatch, capsys):
    from pipeline.cli import main

    monkeypatch.setattr(llm, "generate", FakeLLM([llm.LLMSetupError("ANTHROPIC_API_KEY is not set")]))
    art = _project(project)
    assert main(["run", str(art)], root=project) == exitcodes.SETUP
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out


def test_stage_refuses_a_stale_sentences_file(project, monkeypatch, capsys):
    from pipeline.cli import main

    art = _project(project)
    sentences.write_json(project / "scenes" / "article-fixture.sentences.json",
                         {"article": "article-fixture", "body_sha256": "0" * 64, "count": 1,
                          "sentences": [{"n": 1, "section": "", "line": 1, "kind": "text", "text": "x"}]})
    fake = FakeLLM([])
    monkeypatch.setattr(llm, "generate", fake)
    assert main(["run", str(art), "--from", "scenes"], root=project) == exitcodes.SETUP
    assert "older than the article" in capsys.readouterr().out and not fake.prompts
