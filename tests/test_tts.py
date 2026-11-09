"""Voiceover stage (T4). No Kokoro and no network: a fake voice makes the audio."""

import csv
import importlib.util
import io
import json
from pathlib import Path

import pytest

from pipeline import exitcodes, sentences, stages, tts
from pipeline.claims import content_sha256
from pipeline.cli import main
from pipeline.frontmatter import read_article

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"
ARTICLE = FIX / "article-fixture.md"
GOOD = FIX / "good.scenes.json"

RULES = tts.load_lexicon()


def spoken(text: str) -> str:
    return tts.apply_lexicon(text, RULES)


# --- lexicon -----------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    # The cases PLAN.md section 1 names for T4.
    ("It starts at GBP 1,500 a month.", "It starts at 1,500 pounds a month."),
    ("It scored 48/50.", "It scored 48 out of 50."),
    ("It ranks itself #1.", "It ranks itself number 1."),
    ("The minimum is $8,000 a month.", "The minimum is 8,000 dollars a month."),
    # Acronyms are left alone: Kokoro's front end spells them letter by letter, and
    # "A E O" would be read with the article "uh" (see lexicon.yaml).
    ("GEO and AEO are new; CRO is not.", "GEO and AEO are new; CRO is not."),
    # More rules.
    ("A fee of £2,000 or EUR 30.", "A fee of 2,000 pounds or 30 euros."),
    ("Budgets near $1.5M and $250K.", "Budgets near 1.5 million dollars and 250 thousand dollars."),
    ("It costs $2.50.", "It costs $2.50."),
    ("Open 24/7 since 3/21/2026.", "Open 24 7 since 3/21/2026."),
    ("It takes 3-5 days in 2025-2026.", "It takes 3 to 5 days in 2025 to 2026."),
    ("Leads grew 3x vs. last year.", "Leads grew 3 times versus last year."),
    ("The shop’s “best” price", "The shop's \"best\" price"),
    ("Plain text with 8.9% and 68,631 answers.", "Plain text with 8.9% and 68,631 answers."),
])
def test_lexicon(text, want):
    assert spoken(text) == want


def test_lexicon_rules_apply_in_order(tmp_path):
    f = tmp_path / "lex.yaml"
    f.write_bytes(b"rules:\n  - {pattern: 'a', replace: 'b'}\n  - {pattern: 'b', replace: 'c'}\n")
    assert tts.apply_lexicon("a", tts.load_lexicon(f)) == "c"


@pytest.mark.parametrize("body, msg", [
    (b"rules:\n  - {pattern: '('}\n", "needs 'pattern' and 'replace'"),
    (b"rules:\n  - {pattern: '(', replace: 'x'}\n", "bad pattern"),
    (b"rules: [\n", "not valid YAML"),
])
def test_bad_lexicon(tmp_path, body, msg):
    f = tmp_path / "lex.yaml"
    f.write_bytes(body)
    with pytest.raises(tts.LexiconError, match=msg):
        tts.load_lexicon(f)


# --- stage with a fake voice -------------------------------------------------

# The stage tests need numpy and soundfile (requirements.txt); the lexicon tests do not.
HAS_AUDIO = all(importlib.util.find_spec(m) is not None for m in ("numpy", "soundfile"))
needs_audio = pytest.mark.skipif(not HAS_AUDIO, reason="numpy/soundfile not installed")


class FakeVoice:
    """A tone whose length is `seconds_per_word` per word of the spoken text."""

    sample_rate = 24000

    def __init__(self, seconds_per_word=0.4):
        self.spw = seconds_per_word
        self.calls = []

    def synth(self, text):
        import numpy as np

        self.calls.append(text)
        n = int(len(text.split()) * self.spw * self.sample_rate)
        return (0.1 * np.sin(np.arange(n) / 10)).astype("float32")


@pytest.fixture
def checked(project):
    """Fixture article with sentences and scenes, verified (stops at the review gate)."""
    art = project / "source" / "article-fixture.md"
    art.write_bytes(ARTICLE.read_bytes())
    meta, body = read_article(art)
    sdata = sentences.build(body, "article-fixture", sentences.body_line_offset(art))
    sentences.write_json(project / "scenes" / "article-fixture.sentences.json", sdata)
    (project / "scenes" / "article-fixture.scenes.json").write_bytes(GOOD.read_bytes())
    assert main(["run", str(art), "--from", "verify", "--review"], root=project) == 0
    return project, art


def use_voice(monkeypatch, voice):
    monkeypatch.setitem(stages.STAGES, "tts", lambda ctx: tts.run(ctx, synth=voice))
    # Stop after tts + docs: the later stages are not built yet.
    for name in ("render", "mux", "check"):
        monkeypatch.setitem(stages.STAGES, name, lambda ctx: exitcodes.OK)


def scenes_path(project):
    return project / "scenes" / "article-fixture.scenes.json"


def timing_path(project):
    return project / "audio" / "article-fixture" / "timing.json"


@needs_audio
def test_tts_writes_clips_timing_and_spoken(checked, monkeypatch):
    project, art = checked
    before = json.loads(scenes_path(project).read_text(encoding="utf-8"))
    voice = FakeVoice(0.4)
    use_voice(monkeypatch, voice)
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.OK

    doc = json.loads(scenes_path(project).read_text(encoding="utf-8"))
    timing = json.loads(timing_path(project).read_text(encoding="utf-8"))

    # The checked text never changes, so the verify report still matches.
    assert content_sha256(doc) == content_sha256(before)
    for s_before, s in zip(before["scenes"], doc["scenes"]):
        for l_before, line in zip(s_before["voiceover"], s["voiceover"]):
            assert line["text"] == l_before["text"]
            assert line["spoken"] == spoken(line["text"])
    # Lines go to the voice in their spoken form.
    assert voice.calls == [ln["spoken"] for s in doc["scenes"] for ln in s["voiceover"]]
    assert any("dollars" in c for c in voice.calls)

    # timing.json shape (STATUS.md "For T4").
    assert set(timing) >= {"total_s", "scenes"}
    assert [s["id"] for s in timing["scenes"]] == [s["id"] for s in doc["scenes"]]
    start = 0.0
    for t, s in zip(timing["scenes"], doc["scenes"]):
        assert set(t) >= {"id", "start_s", "duration_s", "lines", "file"}
        assert t["start_s"] == pytest.approx(start, abs=0.002)
        assert t["duration_s"] == s["duration_s"]
        assert len(t["lines"]) == len(s["voiceover"])
        assert t["lines"][0]["start_s"] == t["start_s"]  # speech starts at the scene start
        for a, b in zip(t["lines"], t["lines"][1:]):
            assert b["start_s"] > a["start_s"] + a["duration_s"]  # a pause between lines
        wav = project / "audio" / "article-fixture" / t["file"]
        import soundfile
        info = soundfile.info(str(wav))
        assert info.samplerate == 24000
        assert info.frames / info.samplerate == pytest.approx(t["duration_s"], abs=0.002)
        start += t["duration_s"]
    assert timing["total_s"] == pytest.approx(start, abs=0.005)
    assert 60 <= timing["total_s"] <= 90


@needs_audio
def test_docs_reads_the_timing(checked, monkeypatch):
    project, art = checked
    use_voice(monkeypatch, FakeVoice(0.4))
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.OK
    out = project / "output" / "article-fixture"
    rows = list(csv.DictReader(io.StringIO((out / "factsheet.csv").read_bytes().decode("utf-8-sig"))))
    assert rows and all(r["timecode"] != "-" for r in rows)
    timing = json.loads(timing_path(project).read_text(encoding="utf-8"))
    second_scene = timing["scenes"][1]
    assert any(r["scene"] == str(second_scene["id"]) and r["timecode"].startswith("0:") for r in rows)
    script = (out / "script.md").read_text(encoding="utf-8")
    assert "Spoken as:" in script  # "$45" is spoken as "45 dollars"
    assert "s of voiceover" in script
    assert "from audio timing" in (out / "factsheet.md").read_text(encoding="utf-8")


@needs_audio
def test_too_long_stops_with_the_length_message(checked, monkeypatch, capsys):
    project, art = checked
    timing_path(project).parent.mkdir(parents=True, exist_ok=True)
    timing_path(project).write_bytes(b'{"total_s": 1, "scenes": []}')  # stale, from an earlier run
    before = scenes_path(project).read_bytes()
    use_voice(monkeypatch, FakeVoice(0.7))  # about 125 s for the fixture's words
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.CHECK_FAILED
    out = capsys.readouterr().out
    assert "Voiceover is " in out
    assert "s; the target is 60-90 s. Shorten the scenes and run `--from scenes`, or change video.target_seconds." in out
    assert not timing_path(project).exists()  # later stages cannot start
    assert scenes_path(project).read_bytes() == before
    assert (project / "audio" / "article-fixture" / "scene-01.wav").exists()  # kept for listening


@needs_audio
def test_too_short_stops_too(checked, monkeypatch, capsys):
    project, art = checked
    use_voice(monkeypatch, FakeVoice(0.1))
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.CHECK_FAILED
    assert "the target is 60-90 s" in capsys.readouterr().out


def test_length_message():
    assert tts.length_message(94.2, 60, 90) == (
        "Voiceover is 94.2 s; the target is 60-90 s. Shorten the scenes and run `--from scenes`, "
        "or change video.target_seconds.")


@needs_audio
def test_tts_refuses_failed_report(checked, monkeypatch, capsys):
    project, art = checked
    report = project / "output" / "article-fixture" / "verify-report.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    data["verify"]["result"] = "fail"
    report.write_bytes(json.dumps(data).encode("utf-8"))
    voice = FakeVoice()
    use_voice(monkeypatch, voice)
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.CHECK_FAILED
    assert "does not say pass" in capsys.readouterr().out
    assert voice.calls == []


@needs_audio
def test_tts_refuses_scenes_changed_after_verify(checked, monkeypatch, capsys):
    project, art = checked
    doc = json.loads(scenes_path(project).read_text(encoding="utf-8"))
    doc["scenes"][1]["voiceover"][0]["text"] += " Extra."
    scenes_path(project).write_bytes(json.dumps(doc).encode("utf-8"))
    voice = FakeVoice()
    use_voice(monkeypatch, voice)
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.CHECK_FAILED
    assert "changed after it was checked" in capsys.readouterr().out
    assert voice.calls == []


def test_unknown_provider_is_a_setup_error():
    with pytest.raises(tts.TTSSetupError, match="not known"):
        tts.make_synth({"provider": "nope"})


@needs_audio
def test_build_scene_audio_offsets():
    import numpy as np

    a, b = np.ones(24000, dtype="float32"), np.ones(12000, dtype="float32")
    samples, lines, dur = tts.build_scene_audio([a, b], 24000, 0.5, 0.25)
    assert lines == [(0.0, 1.0), (1.5, 0.5)]
    assert dur == pytest.approx(2.25)
    assert len(samples) == int(2.25 * 24000)


# --- leading silence (open issue 30) -------------------------------------------

class LeadInVoice(FakeVoice):
    """Like FakeVoice, but each clip opens with 300 ms of near silence, as Kokoro's do."""

    def synth(self, text):
        import numpy as np

        tone = super().synth(text)
        hiss = np.full(int(0.3 * self.sample_rate), 1e-4, dtype="float32")
        return np.concatenate([hiss, tone])


@needs_audio
@pytest.mark.parametrize("lead_s, want_s", [(0.3, 0.05), (0.02, 0.02), (0.0, 0.0)])
def test_trim_leading_silence(lead_s, want_s):
    import numpy as np

    sr = 24000
    clip = np.concatenate([np.zeros(int(lead_s * sr), dtype="float32"),
                           np.full(sr, 0.5, dtype="float32"), np.zeros(sr // 2, dtype="float32")])
    out = tts.trim_leading_silence(clip, sr, 0.05, -45)
    first = int(np.flatnonzero(np.abs(out) > 0)[0])
    assert first / sr == pytest.approx(want_s, abs=1 / sr)
    assert len(out) == len(clip) - int(round((lead_s - want_s) * sr))  # the tail is kept


@needs_audio
def test_trim_keeps_an_all_silent_clip():
    import numpy as np

    clip = np.zeros(2400, dtype="float32")
    assert len(tts.trim_leading_silence(clip, 24000, 0.05, -45)) == 2400


@needs_audio
def test_every_scene_clip_starts_speaking_within_50_ms(checked, monkeypatch):
    """With Kokoro-like 300 ms lead-ins, each line's speech starts about 50 ms after its
    timing.json start, so the check stage's sync (c) (100 ms) can pass."""
    import numpy as np
    import soundfile

    project, art = checked
    use_voice(monkeypatch, LeadInVoice(0.4))
    assert main(["run", str(art), "--from", "tts"], root=project) == exitcodes.OK
    timing = json.loads(timing_path(project).read_text(encoding="utf-8"))
    floor = 10 ** (-45 / 20)
    for t in timing["scenes"]:
        samples, sr = soundfile.read(str(project / "audio" / "article-fixture" / t["file"]), dtype="float32")
        for line in t["lines"]:
            k = int(round((line["start_s"] - t["start_s"]) * sr))
            onset = int(np.flatnonzero(np.abs(samples[k:]) >= floor)[0])
            assert 0.04 <= onset / sr <= 0.06


def test_tts_stage_is_registered():
    assert stages.STAGES["tts"] is tts.run


def test_measure_tool_reports_time_and_memory(capfd):
    import sys

    from pipeline.tools import measure

    assert measure.main(["--", sys.executable, "-c", "x = bytearray(50 * 2**20)"]) == 0
    out = capfd.readouterr().out
    assert "[measure] exit code 0, wall time" in out and "peak memory" in out
