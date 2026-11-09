"""`render` stage: Remotion renders the video, each scene's audio inside its own
Sequence (PLAN.md sections 0 and 2).

1. Reads the scenes JSON and audio/<id>/timing.json and checks that they belong
   together (same scene ids, same durations), so a scenes file changed after `tts`
   cannot be rendered against old audio.
2. Turns the times into frames (`scene_frames`): scene boundaries are rounded, not
   scene lengths, so the scene lengths always add up to round(total_s * fps), the
   composition length (PLAN.md section 4 (a)).
3. Writes render/out/<id>.props.json: per scene its frames, WAV file, voiceover
   line starts, the on-screen text and the fixed source tag from config (never from
   the LLM). A bar_chart also gets `scale`, each bar's length as a share of the
   longest, read from the value strings (`bar_scale`); a value that is not a plain
   number stops here with its scene number (exit 1), before Remotion starts.
4. Runs the Remotion CLI in render/ with render.concurrency, audio/<id>/ as the
   public folder, and writes render/out/<id>.mp4. A text that does not fit even at
   render.min_font_px stops the render with its scene number (exit 1).
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
from pipeline.docs import source_tags

RENDER_DIR = "render"
ENTRY = "src/index.ts"
COMPOSITION = "Main"
CLI_JS = Path("node_modules") / "@remotion" / "cli" / "remotion-cli.js"

# Optional render keys and their defaults (render.concurrency is in config.yaml).
DEFAULTS = {
    "concurrency": 1,
    "min_font_px": 36,    # auto-fit never goes below this; below it the render fails
    "timeout_s": 3600,
}

FIT_ERROR = re.compile(r"Scene (\d+): the .*? does not fit[^\n]*")


class RenderInputError(ValueError):
    pass


# A bar value is one plain number, optionally with a currency in front ("$", "EUR ")
# or "%" after it, the same on every bar of the chart. Anything else ("about 18",
# "10-20", "18 points" next to "16") fails with the scene number instead of a guess.
BAR_VALUE = re.compile(
    r"^(?P<pre>[$\u20ac\u00a3\u00a5]|[A-Z]{3} )?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<post>%)?$")


def bar_scale(scene: dict) -> list[float]:
    """Bar lengths of a bar_chart scene: each value over the largest one (bars start
    at zero). The values are read from the strings in the scenes JSON, nothing else."""
    items = scene["visual"].get("items") or []
    nums, units = [], set()
    for i, item in enumerate(items, 1):
        m = BAR_VALUE.match(item["value"].strip())
        if not m:
            raise RenderInputError(
                f"scene {scene['id']}: bar {i} ({item['label']}) has the value {item['value']!r}, which is "
                f"not a plain number, so its bar length cannot be drawn. Use a value such as \"18\", "
                f"\"8.9%\" or \"$3,000\", or another visual type, and run --from scenes")
        units.add((m.group("pre") or "", m.group("post") or ""))
        nums.append(float(m.group("num").replace(",", "")))
    if len(units) > 1:
        raise RenderInputError(
            f"scene {scene['id']}: the bars mix units ({', '.join(repr(i['value']) for i in items)}), so their "
            f"lengths cannot be compared; run --from scenes")
    top = max(nums, default=0.0)
    if top <= 0:
        raise RenderInputError(f"scene {scene['id']}: every bar value is 0, nothing to draw; run --from scenes")
    return [round(n / top, 6) for n in nums]


def settings(config: dict) -> dict:
    out = dict(DEFAULTS)
    out.update(config.get("render") or {})
    return out


def _frame(seconds: float, fps: int) -> int:
    """Nearest frame, halves rounded up (the same rule everywhere)."""
    return int(math.floor(seconds * fps + 0.5))


def scene_frames(timing: dict, fps: int) -> list[tuple[int, int]]:
    """(from, durationInFrames) per scene. Boundaries are rounded, so the lengths add
    up to exactly `_frame(total_s)`, whatever the single scene lengths are."""
    bounds = [_frame(s["start_s"], fps) for s in timing["scenes"]] + [_frame(timing["total_s"], fps)]
    if bounds[0] != 0:
        raise RenderInputError("timing.json: the first scene does not start at 0 s")
    out = []
    for sc, a, b in zip(timing["scenes"], bounds, bounds[1:]):
        if b - a < 1:
            raise RenderInputError(f"timing.json: scene {sc['id']} is shorter than one frame")
        out.append((a, b - a))
    return out


def total_frames(timing: dict, fps: int) -> int:
    return _frame(timing["total_s"], fps)


def check_pair(doc: dict, timing: dict) -> None:
    """The scenes file and timing.json must describe the same voiceover."""
    ids = [s["id"] for s in doc["scenes"]]
    tids = [s["id"] for s in timing["scenes"]]
    if ids != tids:
        raise RenderInputError(f"timing.json has scenes {tids}, the scenes file has {ids}; run --from tts")
    for s, t in zip(doc["scenes"], timing["scenes"]):
        if s.get("duration_s") is None or abs(float(s["duration_s"]) - float(t["duration_s"])) > 0.0015:
            raise RenderInputError(
                f"scene {s['id']}: duration_s {s.get('duration_s')} in the scenes file, "
                f"{t['duration_s']} in timing.json; run --from tts")
        if len(t.get("lines", [])) != len(s["voiceover"]):
            raise RenderInputError(f"scene {s['id']}: timing.json lines do not match the voiceover; run --from tts")


def build_props(doc: dict, timing: dict, config: dict) -> dict:
    """Props of the Main composition (render/src/types.ts)."""
    check_pair(doc, timing)
    video = config["video"]
    fps = int(video["fps"])
    frames = scene_frames(timing, fps)
    tags = source_tags(doc, config)
    scenes = []
    for s, t, (start, length) in zip(doc["scenes"], timing["scenes"], frames):
        visual = {k: v for k, v in s["visual"].items() if k in ("type", "variant", "icon")}
        if "items" in s["visual"]:
            visual["items"] = [{"label": i["label"], "value": i["value"]} for i in s["visual"]["items"]]
        if s["visual"]["type"] == "bar_chart":
            visual["scale"] = bar_scale(s)
        scenes.append({
            "id": s["id"],
            "from": start,
            "durationInFrames": length,
            "audio": t["file"],
            "lineStarts": [max(0, _frame(ln["start_s"], fps) - start) for ln in t["lines"]],
            "sourceTag": tags.get(s["id"]),
            "visual": visual,
            "onScreen": [{"role": o["role"], "text": o["text"]} for o in s["on_screen"]],
        })
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "durationInFrames": total_frames(timing, fps),
        "minFontPx": int(settings(config)["min_font_px"]),
        "scenes": scenes,
    }


def find_node() -> str | None:
    return shutil.which("node")


def remotion_command(subcommand: list[str], props: Path, public_dir: Path | None,
                     extra: list[str] | None = None) -> list[str]:
    """`node <cli> <subcommand...> --props=<file> [--public-dir=<dir>]` (run in render/).
    Calls node directly, not npx, so it behaves the same in cmd.exe and bash."""
    node = find_node()
    if node is None:
        raise FileNotFoundError("node not found on PATH")
    cmd = [node, str(CLI_JS), *subcommand, f"--props={props.resolve()}"]
    if public_dir is not None:
        cmd.append(f"--public-dir={public_dir.resolve()}")
    return cmd + (extra or [])


def render_dir(root: Path) -> Path:
    """The Remotion project (tests point this at the real one)."""
    return root / RENDER_DIR


def setup_problem(root: Path) -> str | None:
    rdir = render_dir(root)
    if find_node() is None:
        return "node is not on PATH (install Node 24, see docs/workflow.md)"
    if not (rdir / CLI_JS).exists():
        return f"Remotion is not installed: run `npm ci` in {RENDER_DIR}/ (see docs/workflow.md)"
    return None


def run_remotion(cmd: list[str], cwd: Path, timeout_s: float) -> tuple[int, str]:
    """Run Remotion, echo its output, and return (exit code, output)."""
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines = []
    assert proc.stdout is not None
    start = time.monotonic()
    for line in proc.stdout:
        lines.append(line)
        print("  " + line.rstrip(), flush=True)
        if time.monotonic() - start > timeout_s:
            proc.kill()
            break
    code = proc.wait()
    return code, "".join(lines)


def fit_failure(output: str) -> str | None:
    m = FIT_ERROR.search(output)
    return m.group(0) if m else None


def run(ctx) -> int:
    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix()  # noqa: E731
    for f in (p.scenes, p.timing):
        if not f.exists():
            print(f"error: {rel(f)} not found; run the earlier stages first")
            return exitcodes.SETUP
    doc = json.loads(p.scenes.read_text(encoding="utf-8"))
    timing = json.loads(p.timing.read_text(encoding="utf-8"))
    try:
        props = build_props(doc, timing, ctx.config)
    except RenderInputError as exc:
        print(f"error: {exc}")
        return exitcodes.CHECK_FAILED
    for s in props["scenes"]:
        if not (p.audio_dir / s["audio"]).exists():
            print(f"error: {rel(p.audio_dir / s['audio'])} not found; run --from tts")
            return exitcodes.SETUP

    problem = setup_problem(p.root)
    if problem:
        print(f"error: {problem}")
        return exitcodes.SETUP

    out = p.render_out
    out.parent.mkdir(parents=True, exist_ok=True)
    props_file = out.with_suffix(".props.json")
    props_file.write_bytes(json.dumps(props, ensure_ascii=False, indent=2).encode("utf-8"))

    cfg = settings(ctx.config)
    cmd = remotion_command(
        ["render", ENTRY, COMPOSITION, str(out.resolve())], props_file, p.audio_dir,
        [f"--concurrency={int(cfg['concurrency'])}"],
    )
    print(f"Rendering {props['durationInFrames']} frames ({props['durationInFrames'] / props['fps']:.1f} s, "
          f"{len(props['scenes'])} scenes) at concurrency {cfg['concurrency']} -> {rel(out)}")
    t0 = time.monotonic()
    code, output = run_remotion(cmd, render_dir(p.root), float(cfg["timeout_s"]))
    took = time.monotonic() - t0
    if code != 0:
        fit = fit_failure(output)
        if fit:
            print(f"error: {fit}")
            return exitcodes.CHECK_FAILED
        print(f"error: Remotion failed (exit {code}) after {took:.0f} s; see the output above")
        return exitcodes.SETUP
    print(f"Rendered {rel(out)} in {took:.0f} s")
    return exitcodes.OK
