import os
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import cli, exitcodes, stages
from pipeline.paths import ArticlePaths

REPO = Path(__file__).resolve().parent.parent


def run(project: Path, *argv: str) -> int:
    return cli.main(list(argv), root=project)


@pytest.fixture
def recorder(monkeypatch):
    """Replace every stage with a no-op that records its name."""
    calls: list[str] = []

    def make(name):
        def fn(ctx):
            calls.append(name)
            return exitcodes.OK

        return fn

    monkeypatch.setattr(stages, "STAGES", {n: make(n) for n in stages.STAGE_NAMES})
    return calls


def article(project: Path) -> str:
    return str(project / "source" / "article-test.md")


def touch_all_outputs(project: Path) -> None:
    p = ArticlePaths.for_article(project / "source" / "article-test.md", root=project)
    for f in (p.sentences, p.scenes, p.verify_report, p.timing, p.render_out, p.final_mp4):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}")


# --- help -------------------------------------------------------------------

def test_top_level_help_lists_every_stage():
    out = subprocess.run(
        [sys.executable, "-m", "pipeline", "--help"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert out.returncode == 0
    for name in stages.STAGE_NAMES:
        assert name in out.stdout
    assert "run" in out.stdout and "doctor" in out.stdout


def test_run_help_lists_every_stage(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in stages.STAGE_NAMES:
        assert name in out
    assert "--review" in out and "--from" in out


def test_no_command_is_an_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


# --- --from validation --------------------------------------------------------

@pytest.mark.parametrize("bad", ["sentence", "all", "2026-11-07", "TTS", "review", ""])
def test_from_rejects_unknown_stage(project, capsys, bad):
    with pytest.raises(SystemExit) as exc:
        run(project, "run", article(project), "--from", bad)
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize("stage", stages.STAGE_NAMES)
def test_from_accepts_every_stage_name(project, recorder, stage):
    touch_all_outputs(project)
    assert run(project, "run", article(project), "--from", stage) == exitcodes.OK
    assert recorder[0] == stage


@pytest.mark.parametrize("stage", stages.STAGE_NAMES[1:])
def test_from_refuses_when_inputs_missing(project, recorder, capsys, stage):
    code = run(project, "run", article(project), "--from", stage)
    assert code == exitcodes.SETUP
    assert recorder == []
    err = capsys.readouterr().err
    assert f"--from {stage} needs files" in err


def test_from_lists_the_missing_file(project, recorder, capsys):
    run(project, "run", article(project), "--from", "scenes")
    assert "scenes/article-test.sentences.json" in capsys.readouterr().err


# --- run order and review gate ---------------------------------------------

def test_full_run_order(project, recorder):
    assert run(project, "run", article(project)) == exitcodes.OK
    assert recorder == ["sentences", "scenes", "verify", "docs", "tts", "docs", "render", "mux", "check"]


def test_review_stops_after_docs(project, recorder, capsys):
    assert run(project, "run", article(project), "--review") == exitcodes.OK
    assert recorder == ["sentences", "scenes", "verify", "docs"]
    out = capsys.readouterr().out
    assert "--from tts" in out
    assert "output/article-test/factsheet.md" in out


def test_from_tts_runs_the_rest(project, recorder):
    touch_all_outputs(project)
    assert run(project, "run", article(project), "--from", "tts", "--review") == exitcodes.OK
    assert recorder == ["tts", "docs", "render", "mux", "check"]


def test_failing_stage_stops_the_run(project, monkeypatch):
    calls = []

    def ok(ctx):
        calls.append("sentences")
        return 0

    def fail(ctx):
        calls.append("scenes")
        return exitcodes.PROVIDER

    monkeypatch.setitem(stages.STAGES, "sentences", ok)
    monkeypatch.setitem(stages.STAGES, "scenes", fail)
    assert run(project, "run", article(project)) == exitcodes.PROVIDER
    assert calls == ["sentences", "scenes"]


# --- stubs and inputs --------------------------------------------------------

def test_stub_says_not_built_and_exits_2(project, capsys):
    # T6 built the last stages (`mux`, `check`), so no stage is a stub any more; the
    # stub maker itself still behaves as T1 defined it.
    stub = stages._stub("mux")
    assert stub(None) == exitcodes.SETUP
    assert "Stage 'mux' is not built yet (task T6)." in capsys.readouterr().out


STUBS = [n for n in stages.STAGE_NAMES if stages.STAGES[n].__name__.endswith("_stub")]


def test_built_stages_are_not_stubs():
    assert STUBS == []


def test_missing_article(project, capsys):
    assert run(project, "run", str(project / "source" / "nope.md")) == exitcodes.SETUP
    assert "article file not found" in capsys.readouterr().err


def test_article_must_be_markdown(project, capsys):
    path = project / "source" / "article-x.txt"
    path.write_text("hello")
    assert run(project, "run", str(path)) == exitcodes.SETUP
    assert ".md" in capsys.readouterr().err


@pytest.mark.parametrize(
    "front, missing",
    [
        ("promotional: true\n", "publisher"),
        ("publisher: X\n", "promotional"),
        ("", "publisher, promotional"),
    ],
)
def test_front_matter_required(project, recorder, capsys, front, missing):
    path = project / "source" / "article-fm.md"
    path.write_text(f"---\n{front}---\n# Title\n")
    assert run(project, "run", str(path)) == exitcodes.SETUP
    assert f"missing {missing}" in capsys.readouterr().err
    assert recorder == []


def test_no_front_matter(project, recorder, capsys):
    path = project / "source" / "article-plain.md"
    path.write_text("# Title\n\nText.\n")
    assert run(project, "run", str(path)) == exitcodes.SETUP
    assert "no front matter" in capsys.readouterr().err


def test_article_id_comes_from_file_name(project):
    p = ArticlePaths.for_article(project / "source" / "article-07.md", root=project)
    assert p.id == "article-07"
    assert p.scenes == project / "scenes" / "article-07.scenes.json"
    assert p.final_mp4 == project / "output" / "article-07" / "article-07.mp4"


def test_env_file_is_loaded_for_run(project, recorder, monkeypatch):
    monkeypatch.delenv("A2V_TEST_VAR", raising=False)
    (project / ".env").write_text("A2V_TEST_VAR=from-file\n")
    assert run(project, "run", article(project)) == exitcodes.OK
    assert os.environ["A2V_TEST_VAR"] == "from-file"
    monkeypatch.delenv("A2V_TEST_VAR")


# --- doctor ------------------------------------------------------------------

def test_doctor_reports_each_item(project, capsys):
    code = run(project, "doctor")
    out = capsys.readouterr().out
    for item in ("Python", "Node", "ffmpeg", "ffprobe", "Folders", "Config", "LLM key",
                 "TTS packages", "Kokoro model", "spaCy model", "Remotion", "Music"):
        assert item in out, item
    assert "not checked until" not in out
    assert code in (exitcodes.OK, exitcodes.SETUP)


def test_doctor_fails_on_missing_folder(project, capsys):
    (project / "scenes").rmdir()
    assert run(project, "doctor") == exitcodes.SETUP
    assert "missing: scenes" in capsys.readouterr().out


def test_doctor_never_prints_the_key(project, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value-123")
    run(project, "doctor")
    out = capsys.readouterr().out
    assert "secret-value-123" not in out
    assert "set (value not shown)" in out


def test_doctor_empty_key_is_a_warning(project, capsys, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    run(project, "doctor")
    out = capsys.readouterr().out
    assert "[WARN ] LLM key" in out
