"""Stage registry and run order (PLAN.md section 0).

Each later task replaces a stub in STAGES with the real function. A stage
function takes a RunContext and returns an exit code (0 = continue).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pipeline import exitcodes
from pipeline.paths import ArticlePaths

# Stage names that `--from` accepts, in order.
STAGE_NAMES = ["sentences", "scenes", "verify", "docs", "tts", "render", "mux", "check"]

DESCRIPTIONS = {
    "sentences": "split the article into numbered sentences and table rows (no LLM)",
    "scenes": "LLM writes the scenes JSON, citing sentences by number",
    "verify": "plain-code checker; errors go back to the LLM up to llm.max_retries",
    "docs": "script and fact sheet (again after tts, with timecodes)",
    "tts": "spoken text from the lexicon, one audio clip per scene, length check",
    "render": "Remotion renders the video, audio inside each scene",
    "mux": "FFmpeg adds the ducked music bed",
    "check": "ffprobe and sync checks on the final file",
}

# The task that builds each stage (shown by the stubs).
BUILT_IN_TASK = {
    "sentences": "T2",
    "scenes": "T3",
    "verify": "T2",
    "docs": "T2",
    "tts": "T4",
    "render": "T5a",
    "mux": "T6",
    "check": "T6",
}

REVIEW = "review"

# Full run order. `docs` runs twice; the review gate sits after the first `docs`.
RUN_ORDER = ["sentences", "scenes", "verify", "docs", REVIEW, "tts", "docs", "render", "mux", "check"]


@dataclass
class RunContext:
    paths: ArticlePaths
    config: dict
    meta: dict
    body: str
    review: bool = False
    log: list[str] = field(default_factory=list)


def required_inputs(stage: str, p: ArticlePaths) -> list[Path]:
    """Files that must exist before `--from <stage>` may start."""
    needs = {
        "sentences": [p.article],
        "scenes": [p.article, p.sentences],
        "verify": [p.article, p.sentences, p.scenes],
        "docs": [p.article, p.sentences, p.scenes, p.verify_report],
        "tts": [p.article, p.sentences, p.scenes, p.verify_report],
        "render": [p.article, p.scenes, p.timing],
        "mux": [p.article, p.timing, p.render_out],
        "check": [p.article, p.timing, p.render_out, p.final_mp4, p.verify_report],
    }
    return needs[stage]


def plan_from(start: str | None) -> list[str]:
    """Steps to run: everything, or from the first occurrence of `start` on."""
    if start is None:
        return list(RUN_ORDER)
    if start not in STAGE_NAMES:
        raise ValueError(f"unknown stage: {start}")
    return RUN_ORDER[RUN_ORDER.index(start) :]


def _stub(name: str) -> Callable[[RunContext], int]:
    def run(ctx: RunContext) -> int:
        print(f"Stage '{name}' is not built yet (task {BUILT_IN_TASK[name]}).")
        return exitcodes.SETUP

    run.__name__ = f"{name}_stub"
    return run


STAGES: dict[str, Callable[[RunContext], int]] = {name: _stub(name) for name in STAGE_NAMES}


def _register_built_stages() -> None:
    """Replace the stubs of the stages that exist (imported late to keep `--help` fast)."""
    from pipeline import check, docs, mux, render, scenes, sentences, tts, verify

    STAGES["sentences"] = sentences.run
    STAGES["scenes"] = scenes.run
    STAGES["verify"] = verify.run
    STAGES["docs"] = docs.run
    STAGES["tts"] = tts.run
    STAGES["render"] = render.run
    STAGES["mux"] = mux.run
    STAGES["check"] = check.run


_register_built_stages()
