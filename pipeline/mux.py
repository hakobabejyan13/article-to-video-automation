"""`mux` stage: FFmpeg lays the music bed under the voice (PLAN.md sections 0 and 2).

1. Checks that render/out/<id>.mp4 belongs to audio/<id>/timing.json (its video is
   round(total_s * fps) frames long), so an old render is never muxed.
2. Measures the mean loudness of the voice track and of the music file
   (FFmpeg `volumedetect`) and sets the music gain so the music's mean level sits
   `music.duck_db` below the voice's (about -20 dB). The same setting gives the same
   balance for any track and any voice.
3. Copies the video stream unchanged and mixes the music under the voice: the music
   loops if it is shorter than the video, fades in and out, and the mix is cut to the
   video's exact length.
   Writes output/<id>/<id>.mp4 (AAC audio).

The music file is the one in `music.file` (a path from the project folder). Nothing
here names a track, an article or a publisher.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

from pipeline import exitcodes

# Optional music keys and their defaults (music.file and music.duck_db are in config.yaml).
DEFAULTS = {
    "fade_in_s": 1.0,
    "fade_out_s": 2.0,
    "audio_bitrate": "192k",
    "sample_rate": 48000,
    "timeout_s": 900,
}

MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf) dB")


class MuxError(ValueError):
    """An input problem the person has to fix (exit 1 or 2, see `code`)."""

    def __init__(self, message: str, code: int = exitcodes.SETUP):
        super().__init__(message)
        self.code = code


def settings(config: dict) -> dict:
    out = dict(DEFAULTS)
    out.update(config.get("music") or {})
    return out


def tool(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        raise MuxError(f"{name} not found on PATH (install FFmpeg, see docs/workflow.md)")
    return exe


def _run(cmd: list[str], timeout_s: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout_s)


def probe(path: Path, timeout_s: float = 120) -> dict:
    """ffprobe streams and format of a media file, as JSON."""
    res = _run([tool("ffprobe"), "-v", "error", "-show_entries",
                "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,"
                "duration,sample_rate,channels:format=duration",
                "-of", "json", str(path)], timeout_s)
    if res.returncode != 0:
        raise MuxError(f"ffprobe cannot read {path.name}: {res.stderr.strip()[-300:]}")
    return json.loads(res.stdout or "{}")


def stream(info: dict, kind: str) -> dict | None:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == kind), None)


def mean_volume(path: Path, timeout_s: float, stream_spec: str = "a:0") -> float:
    """Mean level in dBFS of one audio stream (FFmpeg volumedetect)."""
    res = _run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-map", f"0:{stream_spec}",
                "-af", "volumedetect", "-f", "null", "-"], timeout_s)
    m = MEAN_VOLUME.search(res.stderr or "")
    if res.returncode != 0 or not m:
        raise MuxError(f"cannot measure the loudness of {path.name}: {(res.stderr or '').strip()[-300:]}")
    if m.group(1) == "-inf":
        raise MuxError(f"{path.name} is silent", exitcodes.CHECK_FAILED)
    return float(m.group(1))


def music_gain_db(voice_db: float, music_db: float, duck_db: float) -> float:
    """Gain for the music so its mean level is `duck_db` relative to the voice's."""
    return round(voice_db + float(duck_db) - music_db, 2)


def music_file(root: Path, config: dict) -> Path:
    name = (config.get("music") or {}).get("file")
    if not name:
        raise MuxError("music.file is not set in pipeline/config.yaml (a file in assets/music/)")
    path = Path(name)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        raise MuxError(f"music file not found: {name} (music.file in pipeline/config.yaml); "
                       f"see docs/licenses.md for the track and where to download it")
    return path


def to_stereo(channels: int, sr: int) -> str:
    """Filter that makes a stream stereo at `sr`. A mono stream is copied to both
    channels at full level (a plain upmix would lower it by 3 dB per channel)."""
    pre = "pan=stereo|c0=c0|c1=c0," if channels == 1 else ""
    return f"{pre}aformat=sample_fmts=fltp:sample_rates={sr}:channel_layouts=stereo"


def filter_graph(total_s: float, gain_db: float, cfg: dict, voice_channels: int = 2,
                 music_channels: int = 2) -> str:
    """Music: trimmed to the video, gain, fades; then mixed under the voice.
    `normalize=0` keeps the voice at its own level (amix would otherwise halve it).
    The mix is padded with silence and cut to exactly `total_s` (the video length):
    with duration=first, amix ended the mix about 80 ms before the voice on a real
    Remotion render, more than the one frame sync (b) allows."""
    fade_in = min(float(cfg["fade_in_s"]), total_s / 4)
    fade_out = min(float(cfg["fade_out_s"]), total_s / 4)
    sr = int(cfg["sample_rate"])
    return (
        f"[0:a:0]{to_stereo(voice_channels, sr)}[voice];"
        f"[1:a:0]{to_stereo(music_channels, sr)},atrim=0:{total_s:.6f},asetpts=N/SR/TB,volume={gain_db:.2f}dB,"
        f"afade=t=in:st=0:d={fade_in:.3f},afade=t=out:st={max(0.0, total_s - fade_out):.3f}:d={fade_out:.3f}[music];"
        f"[voice][music]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
        f"apad=whole_dur={total_s:.6f},atrim=end={total_s:.6f}[mix]"
    )


def mux_command(video: Path, music: Path, out: Path, total_s: float, gain_db: float, cfg: dict,
                voice_channels: int = 2, music_channels: int = 2) -> list[str]:
    return [
        tool("ffmpeg"), "-hide_banner", "-nostats", "-y",
        "-i", str(video),
        "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", filter_graph(total_s, gain_db, cfg, voice_channels, music_channels),
        "-map", "0:v:0", "-map", "[mix]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", str(cfg["audio_bitrate"]), "-ar", str(int(cfg["sample_rate"])),
        "-movflags", "+faststart",
        str(out),
    ]


def check_render_matches_timing(info: dict, timing: dict, fps: int) -> None:
    v = stream(info, "video")
    a = stream(info, "audio")
    if v is None or a is None:
        raise MuxError("the rendered video has no video or no audio stream; run --from render",
                       exitcodes.CHECK_FAILED)
    want = int(math.floor(float(timing["total_s"]) * fps + 0.5))
    got = int(v.get("nb_frames") or 0)
    if got and got != want:
        raise MuxError(f"the rendered video has {got} frames, timing.json needs {want} "
                       f"({timing['total_s']} s at {fps} fps): the render is older than the voiceover; "
                       f"run --from render", exitcodes.CHECK_FAILED)


def run(ctx) -> int:
    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix() if x.is_relative_to(p.root) else x.name  # noqa: E731
    for f in (p.timing, p.render_out):
        if not f.exists():
            print(f"error: {rel(f)} not found; run the earlier stages first")
            return exitcodes.SETUP
    cfg = settings(ctx.config)
    timeout = float(cfg["timeout_s"])
    try:
        music = music_file(p.root, ctx.config)
        timing = json.loads(p.timing.read_text(encoding="utf-8"))
        fps = int(ctx.config["video"]["fps"])
        rinfo = probe(p.render_out)
        check_render_matches_timing(rinfo, timing, fps)
        minfo = stream(probe(music), "audio")
        if minfo is None:
            raise MuxError(f"{rel(music)} has no audio stream")
        voice_ch = int(stream(rinfo, "audio").get("channels") or 2)
        music_ch = int(minfo.get("channels") or 2)
        total_s = int(math.floor(float(timing["total_s"]) * fps + 0.5)) / fps   # the video's length
        voice_db = mean_volume(p.render_out, timeout)
        music_db = mean_volume(music, timeout)
        gain = music_gain_db(voice_db, music_db, cfg["duck_db"])

        out = p.final_mp4
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".partial.mp4")
        print(f"Mixing {rel(music)} under the voice: voice {voice_db:.1f} dB, music {music_db:.1f} dB, "
              f"music gain {gain:+.1f} dB (music.duck_db {cfg['duck_db']})")
        t0 = time.monotonic()
        res = _run(mux_command(p.render_out, music, tmp, total_s, gain, cfg, voice_ch, music_ch), timeout)
        if res.returncode != 0:
            tmp.unlink(missing_ok=True)
            print("  " + "\n  ".join((res.stderr or "").strip().splitlines()[-15:]))
            raise MuxError(f"FFmpeg failed (exit {res.returncode}); see the output above")
        tmp.replace(out)
    except MuxError as exc:
        print(f"error: {exc}")
        return exc.code
    except subprocess.TimeoutExpired:
        print(f"error: FFmpeg did not finish within {timeout:.0f} s (music.timeout_s)")
        return exitcodes.SETUP
    print(f"Wrote {rel(out)} in {time.monotonic() - t0:.1f} s")
    return exitcodes.OK
