"""`tts` stage: spoken text, one audio clip per scene, length check (PLAN.md sections 0, 2, 4).

1. Refuses to run unless output/<id>/verify-report.json says pass for the current
   scenes file (same rule as the docs stage), so no unchecked text is voiced.
2. Makes `voiceover[].spoken` from `voiceover[].text` with the rules in
   pipeline/lexicon.yaml. The checked `text` is never changed.
3. Voices each scene line by line (Kokoro by default), cuts each line clip's leading
   silence to tts.lead_in_s (about 50 ms), joins the lines with a short pause, adds
   a short tail after the scene's last line, and writes
   audio/<id>/scene-NN.wav.
4. If the total is outside video.target_seconds, stops with exit 1 and the length
   message (PLAN.md section 4). The scene clips stay for listening; timing.json is
   not written (an old one is removed) and the scenes file is not changed, so the
   later stages cannot start from a voiceover of the wrong length.
5. Otherwise fills `spoken` and `scenes[].duration_s` in the scenes file and writes
   audio/<id>/timing.json:

    {"total_s": 74.2, "sample_rate": 24000, ...,
     "scenes": [{"id": 1, "file": "scene-01.wav", "start_s": 0.0, "duration_s": 6.4,
                 "lines": [{"start_s": 0.0, "duration_s": 5.8}]}, ...]}

   Times are in seconds from the start of the video. A scene's duration includes its
   pauses and tail, so the scene start times add up exactly to the total.

The voice is behind `make_synth`, so tests use a fake one and need neither Kokoro nor
the network.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from pipeline import exitcodes
from pipeline.claims import content_sha256, voiceover_text
from pipeline.verify import count_words

LEXICON_PATH = Path(__file__).resolve().parent / "lexicon.yaml"

# Optional tts keys and their defaults (the required ones are in pipeline/config.py).
DEFAULTS = {
    "line_pause_s": 0.35,  # silence between two voiceover lines of one scene
    "scene_tail_s": 0.6,   # silence after a scene's last line, before the next scene
    "lead_in_s": 0.05,     # silence kept before speech at the start of each line clip
    "trim_db": -45,        # a sample below this level (dBFS) counts as leading silence
    "repo_id": "hexgrad/Kokoro-82M",
}


class LexiconError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    replace: str


def load_lexicon(path: Path = LEXICON_PATH) -> list[Rule]:
    import yaml

    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise LexiconError(f"lexicon file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise LexiconError(f"lexicon file is not valid YAML: {exc}") from None
    rules = []
    for k, r in enumerate(data.get("rules") or []):
        if not isinstance(r, dict) or "pattern" not in r or "replace" not in r:
            raise LexiconError(f"lexicon rule {k + 1} needs 'pattern' and 'replace'")
        try:
            rules.append(Rule(re.compile(str(r["pattern"])), str(r["replace"])))
        except re.error as exc:
            raise LexiconError(f"lexicon rule {k + 1} has a bad pattern: {exc}") from None
    return rules


def apply_lexicon(text: str, rules: list[Rule]) -> str:
    for r in rules:
        text = r.pattern.sub(r.replace, text)
    return re.sub(r"\s+", " ", text).strip()


# --- voices ---------------------------------------------------------------------

class Synth(Protocol):
    sample_rate: int

    def synth(self, text: str):  # -> 1-D float numpy array
        ...


class KokoroSynth:
    """Kokoro-82M through the `kokoro` package (Apache-2.0). Loaded once per run."""

    sample_rate = 24000

    def __init__(self, tts_cfg: dict):
        from kokoro import KPipeline

        self.voice = tts_cfg["voice"]
        self.speed = float(tts_cfg["speed"])
        self.pipeline = KPipeline(lang_code=tts_cfg["lang_code"], repo_id=tts_cfg.get("repo_id", DEFAULTS["repo_id"]))

    def synth(self, text: str):
        import numpy as np

        parts = []
        for result in self.pipeline(text, voice=self.voice, speed=self.speed):
            if result.audio is not None:
                parts.append(result.audio.detach().cpu().numpy().astype("float32"))
        return np.concatenate(parts) if parts else np.zeros(0, dtype="float32")


PROVIDERS: dict[str, Callable[[dict], Synth]] = {"kokoro": KokoroSynth}


class TTSSetupError(RuntimeError):
    pass


def make_synth(tts_cfg: dict) -> Synth:
    provider = tts_cfg["provider"]
    if provider not in PROVIDERS:
        raise TTSSetupError(f"tts.provider {provider!r} is not known; use one of: {', '.join(PROVIDERS)}")
    try:
        return PROVIDERS[provider](tts_cfg)
    except ImportError as exc:
        raise TTSSetupError(f"cannot load the {provider} voice ({exc}); run pip install -r requirements.txt") from None


# --- timing and length ----------------------------------------------------------

def tts_settings(cfg: dict) -> dict:
    return {**DEFAULTS, **cfg["tts"]}


def length_message(total_s: float, lo: float, hi: float) -> str:
    return (f"Voiceover is {total_s:.1f} s; the target is {lo:g}-{hi:g} s. Shorten the scenes and run "
            f"`--from scenes`, or change video.target_seconds.")


def scene_file(scene_id) -> str:
    return f"scene-{int(scene_id):02d}.wav"


def trim_leading_silence(samples, sample_rate: int, lead_in_s: float, trim_db: float):
    """Cut a clip's leading silence down to `lead_in_s` (Kokoro starts each clip with
    about 300 ms of silence, which made the check stage's sync (c) fail; open issue 30).

    Silence is every sample whose level is below `trim_db` dBFS, the same level the
    check stage's silencedetect uses by default. A clip that is all silence, or whose
    lead-in is already shorter than `lead_in_s`, is returned unchanged."""
    import numpy as np

    a = np.asarray(samples, dtype="float32")
    loud = np.flatnonzero(np.abs(a) >= 10 ** (float(trim_db) / 20))
    if not len(loud):
        return a
    cut = int(loud[0]) - int(round(lead_in_s * sample_rate))
    return a[cut:] if cut > 0 else a


def build_scene_audio(lines_audio: list, sample_rate: int, pause_s: float, tail_s: float):
    """Join one scene's line clips. Returns (samples, [(line start, line duration)], duration)."""
    import numpy as np

    pause = np.zeros(int(round(pause_s * sample_rate)), dtype="float32")
    tail = np.zeros(int(round(tail_s * sample_rate)), dtype="float32")
    chunks, lines, pos = [], [], 0
    for k, a in enumerate(lines_audio):
        if k:
            chunks.append(pause)
            pos += len(pause)
        lines.append((pos / sample_rate, len(a) / sample_rate))
        chunks.append(np.asarray(a, dtype="float32"))
        pos += len(a)
    chunks.append(tail)
    pos += len(tail)
    return np.concatenate(chunks), lines, pos / sample_rate


def _r(x: float) -> float:
    return round(x, 3)


def check_verified(p, doc: dict) -> str | None:
    """Same gate as the docs stage: an error message, or None when the scenes passed."""
    from pipeline import verify

    rel = lambda x: x.relative_to(p.root).as_posix()  # noqa: E731
    if not p.verify_report.exists():
        return f"{rel(p.verify_report)} not found; run --from verify"
    v = verify.load_report(p.verify_report).get("verify") or {}
    if v.get("result") != "pass":
        return f"{rel(p.verify_report)} does not say pass; fix the scenes and run --from verify"
    if v.get("scenes_sha256") != content_sha256(doc):
        return f"{rel(p.scenes)} changed after it was checked; run --from verify"
    return None


def run(ctx, synth: Synth | None = None) -> int:
    """Stage entry point. `synth` is for tests; normally the configured voice is loaded."""
    import soundfile

    from pipeline.sentences import write_json

    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix()  # noqa: E731
    if not p.scenes.exists():
        print(f"error: {rel(p.scenes)} not found; run the earlier stages first")
        return exitcodes.SETUP
    doc = json.loads(p.scenes.read_text(encoding="utf-8"))
    problem = check_verified(p, doc)
    if problem:
        print(f"error: {problem}")
        return exitcodes.CHECK_FAILED if p.verify_report.exists() else exitcodes.SETUP

    try:
        rules = load_lexicon()
    except LexiconError as exc:
        print(f"error: {exc}")
        return exitcodes.SETUP
    tcfg = tts_settings(ctx.config)
    for scene in doc["scenes"]:
        for line in scene["voiceover"]:
            line["spoken"] = apply_lexicon(line["text"], rules)

    t0 = time.monotonic()
    if synth is None:
        try:
            synth = make_synth(tcfg)
        except TTSSetupError as exc:
            print(f"error: {exc}")
            return exitcodes.SETUP
    load_s = time.monotonic() - t0
    sr = synth.sample_rate

    p.audio_dir.mkdir(parents=True, exist_ok=True)
    timing_scenes, start = [], 0.0
    t1 = time.monotonic()
    for scene in doc["scenes"]:
        clips = [trim_leading_silence(synth.synth(line["spoken"]), sr, float(tcfg["lead_in_s"]),
                                      float(tcfg["trim_db"]))
                 for line in scene["voiceover"]]
        samples, lines, dur = build_scene_audio(clips, sr, float(tcfg["line_pause_s"]), float(tcfg["scene_tail_s"]))
        name = scene_file(scene["id"])
        soundfile.write(str(p.audio_dir / name), samples, sr, subtype="PCM_16")
        timing_scenes.append({
            "id": scene["id"],
            "file": name,
            "start_s": _r(start),
            "duration_s": _r(dur),
            "lines": [{"start_s": _r(start + ls), "duration_s": _r(ld)} for ls, ld in lines],
        })
        scene["duration_s"] = _r(dur)
        print(f"  scene {scene['id']}: {dur:.1f} s -> {rel(p.audio_dir / name)}")
        start += dur
    synth_s = time.monotonic() - t1
    total = start

    words = sum(count_words(voiceover_text(s)) for s in doc["scenes"])
    wpm = words / total * 60 if total else 0.0
    print(f"Voiced {len(doc['scenes'])} scenes: {total:.1f} s, {words} words ({wpm:.0f} words per minute "
          f"including pauses); model load {load_s:.1f} s, speech {synth_s:.1f} s")

    lo, hi = ctx.config["video"]["target_seconds"]
    if not lo <= total <= hi:
        if p.timing.exists():
            p.timing.unlink()
        print(f"error: {length_message(total, lo, hi)}")
        return exitcodes.CHECK_FAILED

    write_json(p.timing, {
        "total_s": _r(total),
        "sample_rate": sr,
        "provider": tcfg["provider"],
        "voice": tcfg["voice"],
        "speed": tcfg["speed"],
        "words": words,
        "words_per_minute": round(wpm, 1),
        "scenes_sha256": content_sha256(doc),
        "scenes": timing_scenes,
    })
    write_json(p.scenes, doc)
    print(f"timing -> {rel(p.timing)}; spoken text and durations -> {rel(p.scenes)}")
    return exitcodes.OK
