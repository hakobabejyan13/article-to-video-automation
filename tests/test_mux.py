"""Mux and check stages (T6). No Remotion and no network: a stand-in for the rendered
video is made with FFmpeg (black 1920x1080 frames plus the fake voice from the tts
tests), and the music is a made-up tone written by the test. Needs ffmpeg/ffprobe on
PATH and numpy/soundfile (skips otherwise)."""

from __future__ import annotations

import importlib.util
import json
import os
import math
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from pipeline import check, exitcodes, mux, stages
from pipeline.cli import main
from pipeline.config import load as load_config
from pipeline.paths import ArticlePaths

REPO = Path(__file__).resolve().parent.parent
CONFIG = load_config(REPO / "pipeline" / "config.yaml")
TIMING = REPO / "tests" / "fixtures" / "render" / "good.timing.json"

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
HAS_AUDIO = all(importlib.util.find_spec(m) is not None for m in ("numpy", "soundfile"))
media = pytest.mark.skipif(not (HAS_FFMPEG and HAS_AUDIO), reason="needs ffmpeg, ffprobe, numpy and soundfile")

MUSIC_S = 20.0      # shorter than the video, so the bed has to loop
MUSIC_AMP = 0.5


def timing() -> dict:
    return json.loads(TIMING.read_text(encoding="utf-8"))


# --- helpers that make media -------------------------------------------------

def ffmpeg(*args: str) -> None:
    res = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                         capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr


def voice_track(root: Path, art_id: str, out: Path, delay_s: float = 0.0) -> None:
    """One WAV with every scene clip at its start time (what the render's audio is)."""
    import numpy as np
    import soundfile as sf

    t = json.loads((root / "audio" / art_id / "timing.json").read_text(encoding="utf-8"))
    sr = int(t["sample_rate"])
    total = np.zeros(int(round(t["total_s"] * sr)), dtype="float32")
    for sc in t["scenes"]:
        clip, _ = sf.read(str(root / "audio" / art_id / sc["file"]), dtype="float32")
        a = int(round((sc["start_s"] + delay_s) * sr))
        clip = clip[: max(0, len(total) - a)]
        total[a:a + len(clip)] = clip
    sf.write(str(out), total, sr)


def fake_render(root: Path, art_id: str, frames: int | None = None, delay_s: float = 0.0) -> Path:
    """A stand-in for render/out/<id>.mp4: black frames, the voice, h264 + aac."""
    t = json.loads((root / "audio" / art_id / "timing.json").read_text(encoding="utf-8"))
    fps = int(CONFIG["video"]["fps"])
    n = frames if frames is not None else int(math.floor(t["total_s"] * fps + 0.5))
    out = ArticlePaths.for_article(root / "source" / f"{art_id}.md", root=root).render_out
    out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix(".voice.wav")
    voice_track(root, art_id, wav, delay_s)
    ffmpeg("-f", "lavfi", "-i", f"color=c=black:s=1920x1080:r={fps}", "-i", str(wav),
           "-frames:v", str(n), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-ac", "2", "-c:a", "aac", "-b:a", "128k", "-t", f"{n / fps:.3f}", str(out))
    wav.unlink()
    return out


def write_music(path: Path, seconds: float = MUSIC_S) -> None:
    """A steady stereo tone: easy to measure under the voice."""
    import numpy as np
    import soundfile as sf

    sr = 44100
    x = np.arange(int(seconds * sr)) / sr
    tone = (MUSIC_AMP * np.sin(2 * np.pi * 220 * x)).astype("float32")
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.stack([tone, tone], axis=1), sr)


def set_music(root: Path, value) -> None:
    cfg_path = root / "pipeline" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["music"]["file"] = value
    cfg_path.write_bytes(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True).encode("utf-8"))


def mean_db(path: Path, start: float | None = None, dur: float | None = None) -> float:
    cut = ([] if start is None else ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}"])
    res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *cut, "-i", str(path), "-map", "0:a:0",
                          "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    return float(mux.MEAN_VOLUME.search(res.stderr).group(1))


def ready_project(tmp_path: Path, **render_kw):
    """Fixture article verified, voiced (fake voice), 'rendered' by FFmpeg, with music."""
    from tests.test_render import voiced_project

    root, art = voiced_project(tmp_path)
    write_music(root / "assets" / "music" / "test-bed.wav")
    set_music(root, "assets/music/test-bed.wav")
    fake_render(root, "article-fixture", **render_kw)
    return root, art, ArticlePaths.for_article(art, root=root)


@pytest.fixture(scope="module")
def muxed(tmp_path_factory):
    """One project run through mux and check, shared by the read-only tests below."""
    if not (HAS_FFMPEG and HAS_AUDIO):
        pytest.skip("needs ffmpeg, ffprobe, numpy and soundfile")
    root, art, p = ready_project(tmp_path_factory.mktemp("muxed"))
    code = main(["run", str(art), "--from", "mux"], root=root)
    return code, root, art, p


# --- the stages, end to end ----------------------------------------------------

def test_stages_are_registered():
    assert stages.STAGES["mux"] is mux.run
    assert stages.STAGES["check"] is check.run


def test_check_needs_the_voice_track_too(tmp_path):
    p = ArticlePaths.for_article(tmp_path / "source" / "a.md", root=tmp_path)
    assert p.render_out in stages.required_inputs("check", p)


@media
def test_mux_and_check_pass_on_the_fixture(muxed):
    code, root, _, p = muxed
    assert code == exitcodes.OK
    assert p.final_mp4.exists()
    assert not p.final_mp4.with_name(p.id + ".partial.mp4").exists()
    report = json.loads(p.verify_report.read_text(encoding="utf-8"))
    assert report["verify"]["result"] == "pass"         # the verify part is kept
    chk = report["check"]
    assert chk["result"] == "pass" and chk["file"] == "output/article-fixture/article-fixture.mp4"
    assert chk["music"] == "assets/music/test-bed.wav"
    names = [c["name"] for c in chk["checks"]]
    assert names == ["resolution", "video codec", "fps", "audio codec", "duration",
                     "sync (a) frames", "sync (b) stream lengths", "sync (c) speech starts"]
    speech = chk["checks"][-1]["scenes"]
    assert [s["scene"] for s in speech] == [s["id"] for s in timing()["scenes"]]
    assert all(abs(s["offset_ms"]) <= 100 for s in speech)


@media
def test_video_stream_is_copied_unchanged(muxed):
    _, _, _, p = muxed

    def video_md5(path):
        res = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:v:0",
                              "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True, timeout=120)
        return res.stdout.strip()

    assert video_md5(p.final_mp4) == video_md5(p.render_out) != ""


@media
def test_music_sits_duck_db_under_the_voice_and_loops(muxed):
    _, _, _, p = muxed
    t = timing()
    voice = mean_db(p.render_out)
    want = voice + float(CONFIG["music"]["duck_db"])
    # Windows where the voice is silent: inside a scene tail (0.6 s before the next
    # scene starts). The first is after the fade-in; the last is far past the end of
    # the 20 s music file, so the bed must have looped, and before the fade-out.
    gaps = [sc["start_s"] for sc in t["scenes"][1:]]
    late = [g for g in gaps if MUSIC_S + 5 < g < t["total_s"] - 3]
    assert late, "the fixture needs a scene start late in the video"
    for g in (gaps[0], late[-1]):
        got = mean_db(p.final_mp4, g - 0.5, 0.4)
        assert abs(got - want) <= 2.0, (g, got, want)


@media
def test_voice_level_is_not_changed_by_the_mix(muxed):
    _, _, _, p = muxed
    sc = timing()["scenes"][1]
    a, d = sc["start_s"] + 0.5, sc["lines"][0]["duration_s"] - 1.0   # inside speech
    # The tone under the voice adds about 0.04 dB at -20 dB; anything more means the
    # mix scaled the voice (amix without normalize=0 halves it, about -6 dB).
    assert abs(mean_db(p.final_mp4, a, d) - mean_db(p.render_out, a, d)) <= 1.0


@media
def test_check_report_is_replaced_by_a_new_verify(muxed, tmp_path):
    from pipeline import verify

    _, _, _, p = muxed
    copy = tmp_path / "verify-report.json"
    copy.write_bytes(p.verify_report.read_bytes())
    old = json.loads(copy.read_text(encoding="utf-8"))
    verify.write_report(copy, {"article": "article-fixture", "verify": old["verify"]})
    assert "check" not in json.loads(copy.read_text(encoding="utf-8"))


# --- mux refuses bad inputs ----------------------------------------------------

@media
def test_mux_refuses_a_render_older_than_the_voiceover(tmp_path, capsys):
    root, art, p = ready_project(tmp_path, frames=900)
    assert main(["run", str(art), "--from", "mux"], root=root) == exitcodes.CHECK_FAILED
    out = capsys.readouterr().out
    assert "has 900 frames" in out and "run --from render" in out
    assert not p.final_mp4.exists()


@media
@pytest.mark.parametrize("value,msg", [
    (None, "music.file is not set"),
    ("assets/music/missing.mp3", "music file not found: assets/music/missing.mp3"),
])
def test_mux_without_a_music_file_is_a_setup_error(tmp_path, capsys, value, msg):
    root, art, p = ready_project(tmp_path)
    set_music(root, value)
    assert main(["run", str(art), "--from", "mux"], root=root) == exitcodes.SETUP
    assert msg in capsys.readouterr().out
    assert not p.final_mp4.exists()


@media
def test_check_fails_when_the_speech_is_late(tmp_path, capsys):
    """A voice track 300 ms late is caught by sync (c), with the scene numbers."""
    root, art, p = ready_project(tmp_path, delay_s=0.3)
    assert main(["run", str(art), "--from", "mux"], root=root) == exitcodes.CHECK_FAILED
    out = capsys.readouterr().out
    assert "[FAIL] sync (c) speech starts" in out and "scene 1 (+300 ms)" in out
    chk = json.loads(p.verify_report.read_text(encoding="utf-8"))["check"]
    assert chk["result"] == "fail"
    assert [c["name"] for c in chk["checks"] if not c["passed"]] == ["sync (c) speech starts"]


# --- check rules, without media --------------------------------------------------

def info(**over) -> dict:
    v = {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
         "r_frame_rate": "30/1", "nb_frames": "2387", "duration": "79.566667"}
    a = {"codec_type": "audio", "codec_name": "aac", "duration": "79.560000"}
    v.update(over.pop("v", {}))
    a.update(over.pop("a", {}))
    return {"streams": [v, a], "format": {"duration": over.pop("duration", "79.566667")}}


def failed(checks: list[dict]) -> list[str]:
    return [c["name"] for c in checks if not c["passed"]]


def test_format_checks_pass_on_a_good_file():
    assert failed(check.format_checks(info(), CONFIG)) == []


@pytest.mark.parametrize("over,name", [
    ({"v": {"width": 1280, "height": 720}}, "resolution"),
    ({"v": {"codec_name": "hevc"}}, "video codec"),
    ({"v": {"r_frame_rate": "25/1"}}, "fps"),
    ({"a": {"codec_name": "mp3"}}, "audio codec"),
    ({"duration": "94.2"}, "duration"),
    ({"duration": "41.0"}, "duration"),
])
def test_format_checks_catch_each_problem(over, name):
    assert failed(check.format_checks(info(**over), CONFIG)) == [name]


def test_format_checks_without_an_audio_stream():
    i = info()
    i["streams"] = i["streams"][:1]
    assert "audio stream" in failed(check.format_checks(i, CONFIG))


def test_frame_count_must_equal_the_timing_total():
    t = timing()
    want = int(math.floor(t["total_s"] * 30 + 0.5))
    assert check.frame_count_check(info(v={"nb_frames": str(want)}), t, 30)["passed"]
    assert not check.frame_count_check(info(v={"nb_frames": str(want - 1)}), t, 30)["passed"]


@pytest.mark.parametrize("audio_s,ok", [("79.566667", True), ("79.534", True), ("79.53", False), ("79.61", False)])
def test_stream_lengths_differ_by_at_most_one_frame(audio_s, ok):
    assert check.stream_duration_check(info(a={"duration": audio_s}), 30)["passed"] is ok


def test_speech_start_check_names_the_late_scenes():
    t = timing()
    starts = [s["start_s"] for s in t["scenes"]]
    good = check.speech_start_check([s + 0.04 for s in starts], t, 0.1)
    assert good["passed"] and all(s["offset_ms"] == 40.0 for s in good["scenes"])
    late = [s + (0.25 if i == 2 else 0.0) for i, s in enumerate(starts)]
    bad = check.speech_start_check(late, t, 0.1)
    assert not bad["passed"] and bad["detail"].endswith("scene 3 (+250 ms)")
    assert not check.speech_start_check([], t, 0.1)["passed"]


def test_speech_onsets_from_silencedetect(monkeypatch, tmp_path):
    log = ("[silencedetect @ 0x1] silence_start: 6.05\n[silencedetect @ 0x1] silence_end: 6.61 | silence_duration: 0.56\n"
           "[silencedetect @ 0x1] silence_start: 20.1\n[silencedetect @ 0x1] silence_end: 20.75 | silence_duration: 0.65\n")
    monkeypatch.setattr(check, "tool", lambda name: name)
    monkeypatch.setattr(check, "_run", lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "", log))
    assert check.speech_onsets(tmp_path / "x.mp4", check.DEFAULTS) == [0.0, 6.61, 20.75]
    opens_silent = "[silencedetect @ 0x1] silence_start: 0\n[silencedetect @ 0x1] silence_end: 0.3 | x\n"
    monkeypatch.setattr(check, "_run", lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "", opens_silent))
    assert check.speech_onsets(tmp_path / "x.mp4", check.DEFAULTS) == [0.3]


# --- mux rules, without media ----------------------------------------------------

def test_music_gain_puts_the_music_duck_db_under_the_voice():
    assert mux.music_gain_db(voice_db=-24.0, music_db=-14.5, duck_db=-20) == -29.5
    assert mux.music_gain_db(voice_db=-24.0, music_db=-50.0, duck_db=-20) == 6.0


def test_filter_graph_keeps_the_voice_level_and_trims_the_music():
    g = mux.filter_graph(79.55, -29.5, mux.settings(CONFIG))
    assert "amix=inputs=2:duration=longest" in g and "normalize=0" in g
    assert "apad=whole_dur=79.550000,atrim=end=79.550000[mix]" in g
    assert "atrim=0:79.550000" in g and "volume=-29.50dB" in g
    assert "afade=t=in:st=0:d=1.000" in g and "afade=t=out:st=77.550:d=2.000" in g


def test_mux_command_copies_the_video(monkeypatch, tmp_path):
    monkeypatch.setattr(mux, "tool", lambda name: name)
    cmd = mux.mux_command(tmp_path / "v.mp4", tmp_path / "m.mp3", tmp_path / "o.mp4", 70.0, -30.0,
                          mux.settings(CONFIG))
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"           # music loops when shorter
    assert ["-map", "0:v:0"] == cmd[cmd.index("-map"):cmd.index("-map") + 2]


def test_config_names_a_music_file_in_assets():
    assert str(CONFIG["music"]["file"]).startswith("assets/music/")
    assert CONFIG["music"]["duck_db"] == -20


def test_mono_voice_is_copied_to_both_channels_at_full_level():
    g = mux.filter_graph(70.0, -30.0, mux.settings(CONFIG), voice_channels=1, music_channels=2)
    voice, music = g.split(";")[:2]
    assert voice.startswith("[0:a:0]pan=stereo|c0=c0|c1=c0,") and "pan=" not in music


@media
@pytest.mark.skipif(os.environ.get("A2V_RENDER_TESTS") != "1",
                    reason="set A2V_RENDER_TESTS=1 to render the whole fixture video")
def test_real_render_then_mux_and_check(tmp_path, monkeypatch):
    """The whole back half on the fixture: Remotion render, then mux and check. Uses
    the real music file from config when it is in assets/music/, else the test tone."""
    from pipeline import render
    from tests.test_render import voiced_project

    if render.setup_problem(REPO) is not None:
        pytest.skip("Remotion not installed (npm ci in render/)")
    root, art = voiced_project(tmp_path)
    real = REPO / str(CONFIG["music"]["file"])
    if real.exists():
        dest = root / str(CONFIG["music"]["file"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(real, dest)
    else:
        write_music(root / "assets" / "music" / "test-bed.wav")
        set_music(root, "assets/music/test-bed.wav")
    monkeypatch.setattr(render, "render_dir", lambda r: REPO / "render")
    assert main(["run", str(art), "--from", "render"], root=root) == exitcodes.OK
    p = ArticlePaths.for_article(art, root=root)
    chk = json.loads(p.verify_report.read_text(encoding="utf-8"))["check"]
    assert chk["result"] == "pass", [c for c in chk["checks"] if not c["passed"]]
