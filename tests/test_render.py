"""Render stage (T5a). Frame math and props need nothing; the tests marked `remotion`
run the real Remotion project in render/ and skip when `npm ci` has not been run
there. The full fixture video is rendered only with A2V_RENDER_TESTS=1 (slow on the
laptop)."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import exitcodes, render, stages
from pipeline.cli import main
from pipeline.config import load as load_config

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
GOOD = FIX / "verify" / "good.scenes.json"
ARTICLE = FIX / "verify" / "article-fixture.md"
TIMING = FIX / "render" / "good.timing.json"   # written by the tts stage with a fake voice
CONFIG = load_config(REPO / "pipeline" / "config.yaml")

HAS_REMOTION = render.setup_problem(REPO) is None
remotion = pytest.mark.skipif(not HAS_REMOTION, reason="Remotion not installed (npm ci in render/)")
full_render = pytest.mark.skipif(os.environ.get("A2V_RENDER_TESTS") != "1",
                                 reason="set A2V_RENDER_TESTS=1 to render the whole fixture video")
HAS_AUDIO = all(importlib.util.find_spec(m) is not None for m in ("numpy", "soundfile"))


def good_doc() -> dict:
    """The good scenes fixture with the durations the timing fixture gives it."""
    doc = json.loads(GOOD.read_text(encoding="utf-8"))
    timing = json.loads(TIMING.read_text(encoding="utf-8"))
    for s, t in zip(doc["scenes"], timing["scenes"]):
        s["duration_s"] = t["duration_s"]
    return doc


def good_timing() -> dict:
    return json.loads(TIMING.read_text(encoding="utf-8"))


# --- frames ------------------------------------------------------------------

def fake_timing(durations: list[float]) -> dict:
    scenes, start = [], 0.0
    for i, d in enumerate(durations, 1):
        scenes.append({"id": i, "file": f"scene-{i:02d}.wav", "start_s": round(start, 3),
                       "duration_s": d, "lines": [{"start_s": round(start, 3), "duration_s": d - 0.6}]})
        start += d
    return {"total_s": round(start, 3), "sample_rate": 24000, "scenes": scenes}


@pytest.mark.parametrize("fps", [24, 25, 30, 60])
@pytest.mark.parametrize("durations", [
    [6.417, 9.983, 11.05, 8.333, 7.2, 12.517, 4.3],
    [1.016, 1.016, 1.016, 1.016],     # every scene rounds up on its own
    [1.049, 1.049, 1.049, 1.049],     # every scene rounds down on its own
    [72.5],
])
def test_scene_frames_add_up_to_the_total(durations, fps):
    t = fake_timing(durations)
    frames = render.scene_frames(t, fps)
    assert sum(n for _, n in frames) == render.total_frames(t, fps) == math.floor(t["total_s"] * fps + 0.5)
    nxt = 0
    for (start, n), sc in zip(frames, t["scenes"]):
        assert start == nxt
        assert abs(start / fps - sc["start_s"]) <= 0.5 / fps + 1e-9  # each scene starts on time
        nxt += n


def test_timing_fixture_frames():
    t = good_timing()
    frames = render.scene_frames(t, 30)
    assert sum(n for _, n in frames) == render.total_frames(t, 30)
    assert 60 * 30 <= render.total_frames(t, 30) <= 90 * 30


# --- props -------------------------------------------------------------------

def test_props_follow_scenes_and_timing():
    doc, t = good_doc(), good_timing()
    props = render.build_props(doc, t, CONFIG)
    assert (props["width"], props["height"], props["fps"]) == (1920, 1080, 30)
    assert props["durationInFrames"] == render.total_frames(t, 30)
    assert sum(s["durationInFrames"] for s in props["scenes"]) == props["durationInFrames"]
    for p, s, ts in zip(props["scenes"], doc["scenes"], t["scenes"]):
        assert p["id"] == s["id"] and p["audio"] == ts["file"]
        assert [o["text"] for o in p["onScreen"]] == [o["text"] for o in s["on_screen"]]
        assert len(p["lineStarts"]) == len(s["voiceover"]) and p["lineStarts"][0] == 0
        assert p["lineStarts"] == sorted(p["lineStarts"])
        assert all(0 <= x < p["durationInFrames"] for x in p["lineStarts"])
    # Items keep only what is drawn: label and value, never source ids.
    chart = next(p for p in props["scenes"] if p["visual"]["type"] == "bar_chart")
    assert chart["visual"]["items"][0] == {"label": "Northwind Cycles", "value": "18"}


def test_source_tag_from_config_on_publisher_and_company_scenes():
    props = render.build_props(good_doc(), good_timing(), CONFIG)
    tags = {s["id"]: s["sourceTag"] for s in props["scenes"]}
    assert tags[1] == "Source: Northwind Cycles"                    # publisher scene
    assert tags[5] == "Source: Acme Bike Lab, via Northwind Cycles"  # company scene
    assert tags[7] is None                                          # claim_owner none
    doc = good_doc()
    owners = {s["id"]: s["claim_owner"] for s in doc["scenes"]}
    assert all((tags[i] is not None) == (owners[i] != "none") for i in tags)


def test_source_tag_text_never_comes_from_the_scenes_file():
    doc = good_doc()
    doc["scenes"][0]["source_tag"] = "Source: trust me"   # an LLM-made tag is ignored
    doc["scenes"][0]["visual"]["source_tag"] = "Source: trust me"
    props = render.build_props(doc, good_timing(), CONFIG)
    assert props["scenes"][0]["sourceTag"] == "Source: Northwind Cycles"
    assert "trust me" not in json.dumps(props)


@pytest.mark.parametrize("name,want", [
    ("Northwind Cycles", "Source: Northwind Cycles' guide"),
    ("Acme", "Source: Acme's guide"),
])
def test_possessive(name, want):
    from pipeline.docs import fill_tag
    assert fill_tag("Source: {publisher}'s guide", publisher=name) == want


def test_scenes_changed_after_tts_are_refused():
    doc, t = good_doc(), good_timing()
    doc["scenes"][2]["duration_s"] += 1.0
    with pytest.raises(render.RenderInputError, match="scene 3"):
        render.build_props(doc, t, CONFIG)
    doc = good_doc()
    doc["scenes"].pop()
    with pytest.raises(render.RenderInputError, match="run --from tts"):
        render.build_props(doc, t, CONFIG)


def test_render_stage_is_registered():
    assert stages.STAGES["render"] is render.run


def test_fit_failure_is_found_in_remotion_output():
    out = "noise\nError: Scene 4: the bullet 2 does not fit its 1530x150 px box even at the minimum font size of 36 px.\nmore"
    assert render.fit_failure(out).startswith("Scene 4: the bullet 2 does not fit")
    assert render.fit_failure("Error: something else") is None


def test_missing_remotion_is_a_setup_error(tmp_path, monkeypatch, capsys):
    project = voiced_project(tmp_path) if HAS_AUDIO else None
    if project is None:
        pytest.skip("numpy/soundfile not installed")
    root, art = project
    monkeypatch.setattr(render, "render_dir", lambda r: tmp_path / "no-render")
    assert main(["run", str(art), "--from", "render"], root=root) == exitcodes.SETUP
    assert "npm ci" in capsys.readouterr().out


# --- the real Remotion project -----------------------------------------------

def voiced_project(tmp_path: Path):
    """A project folder with the fixture article verified and voiced by a fake voice
    (the same steps the tts tests use). Returns (root, article path)."""
    import numpy as np

    from pipeline import paths, sentences, tts
    from pipeline.frontmatter import read_article

    root = tmp_path / "proj"
    for folder in paths.FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "pipeline" / "config.yaml", root / "pipeline" / "config.yaml")
    art = root / "source" / "article-fixture.md"
    art.write_bytes(ARTICLE.read_bytes())
    meta, body = read_article(art)
    sdata = sentences.build(body, "article-fixture", sentences.body_line_offset(art))
    sentences.write_json(root / "scenes" / "article-fixture.sentences.json", sdata)
    (root / "scenes" / "article-fixture.scenes.json").write_bytes(GOOD.read_bytes())
    assert main(["run", str(art), "--from", "verify", "--review"], root=root) == 0

    class Voice:
        sample_rate = 24000

        def synth(self, text):
            n = int(len(text.split()) * 0.4 * self.sample_rate)
            return (0.1 * np.sin(np.arange(n) / 10)).astype("float32")

    saved = dict(stages.STAGES)
    try:
        stages.STAGES["tts"] = lambda ctx: tts.run(ctx, synth=Voice())
        for name in ("render", "mux", "check"):
            stages.STAGES[name] = lambda ctx: exitcodes.OK
        assert main(["run", str(art), "--from", "tts"], root=root) == exitcodes.OK
    finally:
        stages.STAGES.clear()
        stages.STAGES.update(saved)
    return root, art


@pytest.mark.skipif(not HAS_AUDIO, reason="numpy/soundfile not installed")
def test_timing_fixture_is_what_the_tts_stage_writes(tmp_path):
    root, _ = voiced_project(tmp_path)
    written = json.loads((root / "audio" / "article-fixture" / "timing.json").read_text(encoding="utf-8"))
    assert written == good_timing()


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """Bundle the Remotion project once for the still and composition tests."""
    out = tmp_path_factory.mktemp("bundle") / "build"
    node = render.find_node()
    cmd = [node, str(render.CLI_JS), "bundle", render.ENTRY, f"--out-dir={out}"]
    res = subprocess.run(cmd, cwd=REPO / "render", capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=600)
    assert res.returncode == 0, res.stdout + res.stderr
    return out


def remotion_cli(bundle_dir: Path, args: list[str], props: dict, tmp_path: Path):
    pfile = tmp_path / "props.json"
    pfile.write_bytes(json.dumps(props).encode("utf-8"))
    cmd = [render.find_node(), str(render.CLI_JS), args[0], str(bundle_dir), *args[1:], f"--props={pfile}"]
    return subprocess.run(cmd, cwd=REPO / "render", capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)


def scene_still(bundle_dir, props, scene_index, tmp_path, name):
    """Render the last-but-ten frame of one scene (everything has appeared)."""
    s = props["scenes"][scene_index]
    frame = s["from"] + s["durationInFrames"] - 10
    out = tmp_path / f"{name}.png"
    res = remotion_cli(bundle_dir, ["still", render.COMPOSITION, str(out), f"--frame={frame}"], props, tmp_path)
    return res, out


def gray_crop_mean(png: Path, x: int, y: int, w: int, h: int) -> float:
    """Mean brightness (0-255) of a region, read with FFmpeg (no image library)."""
    import numpy as np

    res = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", f"crop={w}:{h}:{x}:{y},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return float(np.frombuffer(res.stdout, dtype=np.uint8).mean())


@remotion
def test_composition_length_equals_the_timing_total(bundle, tmp_path):
    """PLAN.md section 4 (a), checked on the real composition."""
    t = good_timing()
    props = render.build_props(good_doc(), t, CONFIG)
    res = remotion_cli(bundle, ["compositions", "--log=verbose"], props, tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    line = next(ln for ln in res.stdout.splitlines() if ln.strip().startswith(render.COMPOSITION))
    parts = line.split()
    assert parts[1] == "30" and parts[2] == "1920x1080"
    assert int(parts[3]) == render.total_frames(t, 30) == math.floor(t["total_s"] * 30 + 0.5)


@remotion
def test_composition_refuses_frames_that_do_not_add_up(bundle, tmp_path):
    props = render.build_props(good_doc(), good_timing(), CONFIG)
    props["durationInFrames"] += 1
    res = remotion_cli(bundle, ["compositions"], props, tmp_path)
    assert res.returncode != 0
    assert "add up to" in res.stdout + res.stderr


LONG = ("This headline is far longer than any headline should be, so the renderer has to "
        "shrink it and wrap it over several lines before it fits inside its box")
LONG_BULLET = "A bullet with a lot of words that would overflow at the largest size but fits once it shrinks"


def long_text_props():
    doc = good_doc()
    doc["scenes"][0]["on_screen"][0]["text"] = LONG
    doc["scenes"][0]["on_screen"][1]["text"] = LONG + ", and a sub line that is just as long as it is"
    bullets = doc["scenes"][5]["on_screen"]
    bullets[1]["text"] = LONG_BULLET
    bullets[2]["text"] = LONG_BULLET + " and then some more words"
    doc["scenes"][4]["on_screen"][0]["text"] = LONG + ". " + LONG
    return render.build_props(doc, good_timing(), CONFIG)


@remotion
@pytest.mark.parametrize("index", [0, 4, 5])   # disclosure card, quote, bullets
def test_long_text_fits(bundle, tmp_path, index):
    res, png = scene_still(bundle, long_text_props(), index, tmp_path, f"long-{index}")
    assert res.returncode == 0, res.stdout + res.stderr
    normal_props = render.build_props(good_doc(), good_timing(), CONFIG)
    _, normal = scene_still(bundle, normal_props, index, tmp_path, f"normal-{index}")
    # The outer margins stay empty background, as in the normal scene (text that
    # overflowed its box would show up there).
    for region in [(0, 0, 1920, 60), (0, 0, 110, 900), (1810, 0, 110, 1080)]:
        assert gray_crop_mean(png, *region) == pytest.approx(gray_crop_mean(normal, *region), abs=0.5)


@remotion
def test_text_that_cannot_fit_fails_with_the_scene_number(bundle, tmp_path):
    doc = good_doc()
    doc["scenes"][5]["on_screen"][1]["text"] = " ".join(["overflowing"] * 120)
    props = render.build_props(doc, good_timing(), CONFIG)
    res, _ = scene_still(bundle, props, 0, tmp_path, "too-long")
    assert res.returncode != 0
    assert render.fit_failure(res.stdout + res.stderr).startswith("Scene 6: the bullet 1 does not fit")


@remotion
def test_source_tag_is_drawn_on_publisher_scenes_only(bundle, tmp_path):
    props = render.build_props(good_doc(), good_timing(), CONFIG)
    # The tag sits bottom left: x 140.., y about 950-1016.
    region = (140, 950, 800, 70)
    _, pub = scene_still(bundle, props, 0, tmp_path, "publisher")      # claim_owner publisher
    _, comp = scene_still(bundle, props, 4, tmp_path, "company")       # company:<name>
    _, none = scene_still(bundle, props, 6, tmp_path, "none")          # claim_owner none
    base = gray_crop_mean(none, *region)
    assert gray_crop_mean(pub, *region) > base + 8
    assert gray_crop_mean(comp, *region) > base + 8


@remotion
@full_render
def test_fixture_renders_at_1920x1080_30fps(tmp_path, monkeypatch):
    root, art = voiced_project(tmp_path)
    monkeypatch.setattr(render, "render_dir", lambda r: REPO / "render")
    for name in ("mux", "check"):
        monkeypatch.setitem(stages.STAGES, name, lambda ctx: exitcodes.OK)
    assert main(["run", str(art), "--from", "render"], root=root) == exitcodes.OK
    mp4 = root / "render" / "out" / "article-fixture.mp4"
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,duration",
                          "-of", "json", str(mp4)], capture_output=True, text=True, timeout=60)
    streams = json.loads(res.stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["codec_name"], v["width"], v["height"], v["r_frame_rate"]) == ("h264", 1920, 1080, "30/1")
    t = json.loads((root / "audio" / "article-fixture" / "timing.json").read_text(encoding="utf-8"))
    assert int(v["nb_frames"]) == render.total_frames(t, 30)
    assert abs(float(a["duration"]) - float(v["duration"])) <= 1 / 30 + 0.03


# --- data scenes (T5b) -------------------------------------------------------

def scene_of(doc: dict, vtype: str) -> dict:
    return next(s for s in doc["scenes"] if s["visual"]["type"] == vtype)


def test_data_items_reach_the_props_unchanged():
    """Every label and value drawn by a data scene is the string in the scenes JSON."""
    doc = good_doc()
    props = render.build_props(doc, good_timing(), CONFIG)
    seen = set()
    for p, s in zip(props["scenes"], doc["scenes"]):
        if "items" in s["visual"]:
            seen.add(s["visual"]["type"])
            assert p["visual"]["items"] == [{"label": i["label"], "value": i["value"]} for i in s["visual"]["items"]]
    assert seen == {"big_number", "bar_chart", "price_cards"}


def test_bar_lengths_follow_the_values():
    props = render.build_props(good_doc(), good_timing(), CONFIG)
    chart = next(p for p in props["scenes"] if p["visual"]["type"] == "bar_chart")
    values = [float(i["value"]) for i in chart["visual"]["items"]]          # 18, 16, 15
    assert chart["visual"]["scale"] == [round(v / max(values), 6) for v in values]
    assert chart["visual"]["scale"][0] == 1.0
    assert all("scale" not in p["visual"] for p in props["scenes"] if p["visual"]["type"] != "bar_chart")


@pytest.mark.parametrize("values,scale", [
    (["8.9%", "91%"], [round(8.9 / 91, 6), 1.0]),
    (["$3,000", "$1,500", "$0"], [1.0, 0.5, 0.0]),
    (["EUR 30", "EUR 45.5"], [round(30 / 45.5, 6), 1.0]),
])
def test_bar_values_with_one_unit(values, scale):
    scene = {"id": 9, "visual": {"type": "bar_chart", "items": [{"label": f"L{i}", "value": v} for i, v in enumerate(values)]}}
    assert render.bar_scale(scene) == scale


@pytest.mark.parametrize("values,why", [
    (["about 18", "16"], "not a plain number"),
    (["10-20", "16"], "not a plain number"),
    (["18 points", "16 points"], "not a plain number"),
    (["Top", "16"], "not a plain number"),
    (["-4", "16"], "not a plain number"),
    (["$18", "16"], "mix units"),
    (["18%", "EUR 16"], "mix units"),
    (["0", "0", "0"], "every bar value is 0"),
])
def test_bar_value_that_is_not_a_plain_number_fails_with_the_scene_number(values, why):
    doc = good_doc()
    chart = scene_of(doc, "bar_chart")
    for item, v in zip(chart["visual"]["items"], values):
        item["value"] = v
    with pytest.raises(render.RenderInputError, match=f"scene {chart['id']}: .*{why}"):
        render.build_props(doc, good_timing(), CONFIG)


@pytest.mark.skipif(not HAS_AUDIO, reason="numpy/soundfile not installed")
def test_render_stage_stops_on_a_bad_bar_value_before_remotion(tmp_path, capsys, monkeypatch):
    root, art = voiced_project(tmp_path)
    scenes_file = root / "scenes" / "article-fixture.scenes.json"
    doc = json.loads(scenes_file.read_text(encoding="utf-8"))
    scene_of(doc, "bar_chart")["visual"]["items"][0]["value"] = "about 18"
    scenes_file.write_bytes(json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"))
    monkeypatch.setattr(render, "run_remotion", lambda *a, **k: pytest.fail("Remotion must not start"))
    assert main(["run", str(art), "--from", "render"], root=root) == exitcodes.CHECK_FAILED
    assert "scene 2: bar 1 (Northwind Cycles) has the value 'about 18'" in capsys.readouterr().out


# The count-up rules live in render/src/countup.ts (no imports), run here with Node,
# which strips the TypeScript types itself (Node 22.18 and later).
COUNTUP = REPO / "render" / "src" / "countup.ts"
HAS_NODE = render.find_node() is not None


def run_countup(script: str, data) -> object:
    js = (f"import({json.dumps(COUNTUP.as_uri())}).then((m) => {{ const data = {json.dumps(data)};\n"
          f"{script}\n}}).catch((e) => {{ console.error(e); process.exit(1); }});")
    res = subprocess.run([render.find_node(), "--input-type=module", "-e", js], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
    return json.loads(res.stdout)


@pytest.mark.skipif(not HAS_NODE, reason="node not on PATH")
def test_count_up_only_animates_a_number_in_the_value():
    values = ["9 of 12", "EUR 30", "$3,000 a month", "8.9%", "122%", "GBP 1,500 a month", "18", "2024", "007", "0", "Free"]
    steps = [i / 20 for i in range(21)]
    out = run_countup("console.log(JSON.stringify(data.values.map((v) => data.steps.map((p) => m.countUpText(v, p)))))",
                      {"values": values, "steps": steps})
    num = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
    for value, shown in zip(values, out):
        assert shown[-1] == value                       # progress 1: the value as written
        m = num.search(value)
        for s in shown:
            if m is None or value in ("2024", "007", "0"):
                assert s == value                       # nothing to count, or not counted
                continue
            n = num.search(s)
            # Only the first number changes; the text around it never does.
            assert s[:n.start()] == value[:m.start()] and s[n.end():] == value[m.end():]
            target = float(m.group().replace(",", ""))
            assert 0 <= float(n.group().replace(",", "")) <= target
            decimals = len(m.group().split(".")[1]) if "." in m.group() else 0
            assert (len(n.group().split(".")[1]) if "." in n.group() else 0) == decimals
        assert shown[0] != value or m is None or value in ("2024", "007", "0")


@pytest.mark.skipif(not HAS_NODE, reason="node not on PATH")
def test_last_frames_show_every_value_exactly():
    """Whatever the voiceover timing, every data item has finished counting well
    before its scene ends: the last frames show the JSON value unchanged."""
    props = render.build_props(good_doc(), good_timing(), CONFIG)
    cases = []
    for s in props["scenes"]:
        if "items" in s["visual"]:
            cases.append({"frames": s["durationInFrames"], "lineStarts": s["lineStarts"],
                          "values": [i["value"] for i in s["visual"]["items"]]})
    # Odd timings too: very short scenes, and line starts near the very end.
    cases.append({"frames": 40, "lineStarts": [0], "values": ["9 of 12"]})
    cases.append({"frames": 300, "lineStarts": [280, 290, 299], "values": ["$45", "EUR 30", "$60"]})
    cases.append({"frames": 20, "lineStarts": [], "values": ["18", "16", "15", "14", "13", "12", "11", "10", "9", "8"]})
    script = """
const out = [];
for (const c of data.cases) {
  for (const stagger of [6, 12, 14]) {
    const t = m.itemTimings(c.frames, c.lineStarts, c.values.length, stagger);
    out.push({c, last: c.values.map((v, i) => [c.frames - 1, c.frames - m.holdFrames(c.frames)].map((f) => m.valueAtFrame(v, f, t[i]))),
      ends: t.map((x) => x.start + x.frames)});
  }
}
console.log(JSON.stringify(out));"""
    for r in run_countup(script, {"cases": cases}):
        c = r["c"]
        for v, shown in zip(c["values"], r["last"]):
            assert set(shown) == {v}
        # From the hold on (the last 15 frames, or a third of a very short scene)
        # nothing moves; the stills in these tests are taken 10 frames from the end.
        assert max(r["ends"]) <= c["frames"] - min(15, c["frames"] // 3)


def teal_bars(png: Path) -> list[int]:
    """Lengths (px) of the accent-coloured bars in a frame, top to bottom."""
    import numpy as np

    res = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=60)
    img = np.frombuffer(res.stdout, dtype=np.uint8).reshape(1080, 1920, 3).astype(int)
    mask = (img[..., 0] < 140) & (img[..., 1] > 200) & (img[..., 2] > 170)
    bars, current = [], []
    for row in mask:
        idx = np.flatnonzero(row)
        width = int(idx[-1] - idx[0] + 1) if idx.size and idx.size > 0.9 * (idx[-1] - idx[0] + 1) else 0
        if width > 150:
            current.append(width)
        elif current:
            bars.append(max(current))
            current = []
    return bars


@remotion
def test_bars_are_drawn_to_the_lengths_of_the_values(bundle, tmp_path):
    doc = good_doc()
    chart = scene_of(doc, "bar_chart")
    for item, v in zip(chart["visual"]["items"], ["40", "10", "25"]):
        item["value"] = v
    props = render.build_props(doc, good_timing(), CONFIG)
    index = [s["id"] for s in props["scenes"]].index(chart["id"])
    res, png = scene_still(bundle, props, index, tmp_path, "bars")
    assert res.returncode == 0, res.stdout + res.stderr
    bars = teal_bars(png)
    assert len(bars) == 3
    for got, want in zip(bars, [40, 10, 25]):
        assert got / bars[0] == pytest.approx(want / 40, abs=0.01)


@remotion
@pytest.mark.parametrize("vtype", ["big_number", "bar_chart", "price_cards"])
def test_data_scene_renders(bundle, tmp_path, vtype):
    props = render.build_props(good_doc(), good_timing(), CONFIG)
    index = [s["visual"]["type"] for s in props["scenes"]].index(vtype)
    res, png = scene_still(bundle, props, index, tmp_path, vtype)
    assert res.returncode == 0, res.stdout + res.stderr
    # The data sits in the middle of the frame: brighter than the empty background.
    assert gray_crop_mean(png, 140, 380, 1640, 300) > gray_crop_mean(png, 140, 0, 1640, 60) + 5


@remotion
def test_data_value_that_cannot_fit_fails_with_the_scene_number(bundle, tmp_path):
    doc = good_doc()
    cards = scene_of(doc, "price_cards")
    cards["visual"]["items"][1]["value"] = " ".join(["EUR 30 per visit"] * 30)
    props = render.build_props(doc, good_timing(), CONFIG)
    res, _ = scene_still(bundle, props, 0, tmp_path, "too-long-card")
    assert res.returncode != 0
    assert render.fit_failure(res.stdout + res.stderr).startswith(f"Scene {cards['id']}: the card 2 value does not fit")
