"""`check` stage: ffprobe and sync checks on the final file (PLAN.md section 4).

Checks, each written to output/<id>/verify-report.json under "check":
- format: 1920x1080 (video.width/height), H.264 video, AAC audio, video.fps, and a
  duration inside video.target_seconds;
- sync (a): the final video has round(total_s * fps) frames, the sum of the scene
  lengths in timing.json (the same rule the render stage uses);
- sync (b): the video and audio stream durations differ by at most one frame;
- sync (c): FFmpeg silencedetect finds each scene's speech starting within 100 ms of
  that scene's start in timing.json. It listens to the voice track that went into the
  final mix (render/out/<id>.mp4): in the final file the music fills the pauses, so
  silences cannot be found there. The final file's video stream is a copy of that
  render, and the mix starts the voice at 0, so the same times hold for it.

Exit 1 if any check fails, 0 if all pass.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pipeline import exitcodes
from pipeline.mux import MuxError, _run, probe, stream, tool

# Optional `check` keys and their defaults (no `check` section is needed in config.yaml).
DEFAULTS = {
    "silence_db": -45,            # below this level counts as silence
    "silence_min_s": 0.2,         # shortest silence silencedetect reports (scene tails are 0.6 s)
    "speech_start_tolerance_s": 0.1,
    "timeout_s": 300,
}

SILENCE = re.compile(r"silence_(start|end):\s*(-?[\d.]+)")


def settings(config: dict) -> dict:
    out = dict(DEFAULTS)
    out.update(config.get("check") or {})
    return out


def _fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0",):
        return None
    num, _, den = rate.partition("/")
    return float(num) / float(den or 1)


def result(name: str, passed: bool, detail: str, **values) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, **values}


def format_checks(info: dict, config: dict) -> list[dict]:
    video = config["video"]
    v, a = stream(info, "video"), stream(info, "audio")
    out = []
    if v is None:
        out.append(result("video stream", False, "the file has no video stream"))
    else:
        size = (int(v.get("width") or 0), int(v.get("height") or 0))
        want = (int(video["width"]), int(video["height"]))
        out.append(result("resolution", size == want, f"{size[0]}x{size[1]} (want {want[0]}x{want[1]})"))
        out.append(result("video codec", v.get("codec_name") == "h264", f"{v.get('codec_name')} (want h264)"))
        fps = _fps(v.get("r_frame_rate"))
        out.append(result("fps", fps is not None and abs(fps - float(video["fps"])) < 1e-6,
                          f"{v.get('r_frame_rate')} (want {video['fps']})"))
    if a is None:
        out.append(result("audio stream", False, "the file has no audio stream"))
    else:
        out.append(result("audio codec", a.get("codec_name") == "aac", f"{a.get('codec_name')} (want aac)"))
    lo, hi = (float(x) for x in video["target_seconds"])
    dur = float((info.get("format") or {}).get("duration") or 0)
    out.append(result("duration", lo <= dur <= hi, f"{dur:.2f} s (target {lo:g}-{hi:g} s)", seconds=round(dur, 3)))
    return out


def frame_count_check(info: dict, timing: dict, fps: int) -> dict:
    v = stream(info, "video") or {}
    want = int(math.floor(float(timing["total_s"]) * fps + 0.5))
    got = int(v.get("nb_frames") or 0)
    return result("sync (a) frames", got == want,
                  f"{got} frames in the video, {want} from timing.json ({timing['total_s']} s at {fps} fps)",
                  frames=got, expected=want)


def stream_duration_check(info: dict, fps: int) -> dict:
    v, a = stream(info, "video"), stream(info, "audio")
    if v is None or a is None or v.get("duration") is None or a.get("duration") is None:
        return result("sync (b) stream lengths", False, "a stream duration is missing")
    dv, da = float(v["duration"]), float(a["duration"])
    diff = abs(dv - da)
    limit = 1 / fps
    return result("sync (b) stream lengths", diff <= limit + 1e-6,
                  f"video {dv:.3f} s, audio {da:.3f} s, difference {diff * 1000:.0f} ms "
                  f"(at most {limit * 1000:.0f} ms)", difference_ms=round(diff * 1000, 1))


def speech_onsets(path: Path, cfg: dict) -> list[float]:
    """Times where speech starts: 0 unless the track opens with silence, then each
    silence_end that silencedetect reports."""
    res = _run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                "-af", f"silencedetect=noise={float(cfg['silence_db'])}dB:d={float(cfg['silence_min_s'])}",
                "-f", "null", "-"], float(cfg["timeout_s"]))
    if res.returncode != 0:
        raise MuxError(f"silencedetect failed on {path.name}: {(res.stderr or '').strip()[-300:]}")
    events = [(k, float(t)) for k, t in SILENCE.findall(res.stderr or "")]
    onsets = []
    if not events or events[0][0] != "start" or events[0][1] > 0.01:
        onsets.append(0.0)
    onsets += [t for k, t in events if k == "end"]
    return onsets


def speech_start_check(onsets: list[float], timing: dict, tolerance_s: float) -> dict:
    scenes, bad = [], []
    for sc in timing["scenes"]:
        start = float(sc["start_s"])
        near = min(onsets, key=lambda t: abs(t - start)) if onsets else None
        off = None if near is None else round((near - start) * 1000, 1)
        ok = near is not None and abs(near - start) <= tolerance_s + 1e-6
        scenes.append({"scene": sc["id"], "start_s": start,
                       "speech_s": None if near is None else round(near, 3), "offset_ms": off, "passed": ok})
        if not ok:
            bad.append(f"scene {sc['id']} ({'no speech found' if off is None else f'{off:+.0f} ms'})")
    detail = (f"speech starts within {tolerance_s * 1000:.0f} ms of every scene start ({len(scenes)} scenes)"
              if not bad else f"off by more than {tolerance_s * 1000:.0f} ms: " + ", ".join(bad))
    return result("sync (c) speech starts", not bad, detail, scenes=scenes)


def write_check(path: Path, data: dict) -> None:
    from pipeline.sentences import write_json

    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    report["check"] = data
    write_json(path, report)


def run(ctx) -> int:
    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix() if x.is_relative_to(p.root) else x.name  # noqa: E731
    for f in (p.timing, p.final_mp4, p.render_out, p.verify_report):
        if not f.exists():
            print(f"error: {rel(f)} not found; run the earlier stages first")
            return exitcodes.SETUP
    cfg = settings(ctx.config)
    fps = int(ctx.config["video"]["fps"])
    timing = json.loads(p.timing.read_text(encoding="utf-8"))
    try:
        info = probe(p.final_mp4)
        checks = format_checks(info, ctx.config)
        checks.append(frame_count_check(info, timing, fps))
        checks.append(stream_duration_check(info, fps))
        checks.append(speech_start_check(speech_onsets(p.render_out, cfg), timing,
                                         float(cfg["speech_start_tolerance_s"])))
    except MuxError as exc:
        print(f"error: {exc}")
        return exc.code
    except subprocess.TimeoutExpired:
        print(f"error: FFmpeg did not finish within {cfg['timeout_s']} s (check.timeout_s)")
        return exitcodes.SETUP

    passed = all(c["passed"] for c in checks)
    write_check(p.verify_report, {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file": rel(p.final_mp4),
        "music": (ctx.config.get("music") or {}).get("file"),
        "result": "pass" if passed else "fail",
        "checks": checks,
    })
    for c in checks:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print(("PASS: " if passed else "FAIL: ") + f"final checks on {rel(p.final_mp4)}; report: {rel(p.verify_report)}")
    return exitcodes.OK if passed else exitcodes.CHECK_FAILED
