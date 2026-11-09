"""`scenes` stage: the LLM writes the scenes JSON (PLAN.md sections 0-3).

1. Build the prompt from `pipeline/prompts/scenes.md`, config.yaml, the front matter
   and the numbered sentences file.
2. Call the LLM (pipeline.llm; provider, models and key from `llm.*` in config).
3. Assemble the scenes document in the schema's shape. The LLM supplies the scenes
   only: `article.id` comes from the file name, `article.title` from the article's
   first heading, `publisher` and `promotional` from the front matter, and `spoken`
   and `duration_s` start as null (the tts stage fills them). The LLM cites
   sentences by number; no cited text is copied into the scenes file.
4. Run pipeline.verify.check_document. On failure, send the error lines back with the
   previous answer, up to `llm.max_retries` more times.

Writes `scenes/<id>.scenes.json` (also when the checker still fails, so a person can
look at it and `output/<id>/verify-report.json` says why), plus a run log and every
raw answer in `output/<id>/llm/`.

Exit codes: 0 pass, 1 checker still fails after the retries, 2 setup problem,
3 every model of the provider failed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline import exitcodes, llm, sentences, verify

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "scenes.md"
SCHEMA_PATH = verify.SCHEMA_PATH

DEFAULT_SCENE_HINT = "6-9"


# ------------------------------------------------------------------ prompt

def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def llm_schema() -> dict:
    """The response schema sent to the LLM: just the scenes, in the main schema's
    terms (types, roles, variants from scenes.schema.json), without the article block
    and the fields code fills in. Kept simple so both providers accept it."""
    s = _schema()["$defs"]
    ids = {"type": "array", "items": {"type": "integer"}}
    text = {"type": "string"}

    def obj(props: dict, required: list[str]) -> dict:
        return {"type": "object", "properties": props, "required": required,
                "additionalProperties": False}

    item = obj({"label": text, "value": text, "source_ids": ids}, ["label", "value", "source_ids"])
    visual = obj({
        "type": {"type": "string", "enum": s["visual"]["properties"]["type"]["enum"]},
        "variant": {"type": "string", "enum": s["visual"]["properties"]["variant"]["enum"]},
        "icon": text,
        "items": {"type": "array", "items": item},
    }, ["type"])
    on_screen = obj({
        "role": {"type": "string", "enum": s["on_screen_text"]["properties"]["role"]["enum"]},
        "text": text, "source_ids": ids,
    }, ["role", "text", "source_ids"])
    line = obj({"text": text, "source_ids": ids}, ["text", "source_ids"])
    scene = obj({
        "id": {"type": "integer"},
        "claim_owner": text,
        "visual": visual,
        "on_screen": {"type": "array", "items": on_screen},
        "voiceover": {"type": "array", "items": line},
    }, ["id", "claim_owner", "visual", "on_screen", "voiceover"])
    return obj({"scenes": {"type": "array", "items": scene}}, ["scenes"])


def format_entry(e: dict) -> str:
    kind = e.get("kind", "text")
    if kind == "list_item":
        label = f"list item {e['marker']}" if e.get("marker") else "list item"
    else:
        label = kind.replace("_", " ")
    return f"[{e['n']}] ({e.get('section', '')}) {label}: {e.get('text', '')}"


def _quote_list(words) -> str:
    return ", ".join(f'"{w}"' for w in words)


def _apply_blocks(text: str, promotional: bool) -> str:
    def repl(m: re.Match) -> str:
        want_promo = m.group(1) is None  # "if promotional" vs "if not promotional"
        return m.group(2) if want_promo == promotional else ""

    return re.sub(r"<!-- if (not )?promotional -->\n(.*?)<!-- end -->\n", repl, text, flags=re.S)


def build_prompt(sentences_data: dict, meta: dict, cfg: dict, template: str | None = None) -> str:
    if template is None:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    template = re.sub(r"\A<!--.*?-->\n", "", template, count=1, flags=re.S)  # header comment
    publisher = meta["publisher"]
    promotional = bool(meta["promotional"])
    lo, hi = verify.word_range(cfg)
    lo_s, hi_s = cfg["video"]["target_seconds"]
    rw = cfg["review_warnings"]
    entries = sentences_data["sentences"]
    values = {
        "publisher": publisher,
        "publish_words": _quote_list(cfg["disclosure_words"]["publish"]),
        "rank_words": _quote_list(cfg["disclosure_words"]["rank"]),
        "attribution_phrases": _quote_list(p.format(publisher=publisher)
                                           for p in cfg["attribution_phrases"]),
        "word_lo": str(lo),
        "word_hi": str(hi),
        "seconds": f"{lo_s}-{hi_s}",
        "wpm": str(cfg["speech"]["words_per_minute"]),
        "visual_types": ", ".join(_schema()["$defs"]["visual"]["properties"]["type"]["enum"]),
        "inference_words": _quote_list(rw["inference_words"]),
        "judging_words": _quote_list(rw["judging_words"]),
        "min_sections": str(rw["min_sections"]),
        "scene_hint": str(cfg["llm"].get("scene_count") or DEFAULT_SCENE_HINT),
        "sentence_count": str(len(entries)),
        "sentences": "\n".join(format_entry(e) for e in entries),
    }
    text = _apply_blocks(template, promotional)

    def fill(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"prompt template uses an unknown placeholder {{{{{key}}}}}")
        return values[key]

    # the sentences go in last, so text inside them is never treated as a placeholder
    body, _, tail = text.partition("{{sentences}}")
    return re.sub(r"\{\{(\w+)\}\}", fill, body) + values["sentences"] + re.sub(r"\{\{(\w+)\}\}", fill, tail)


def retry_prompt(base: str, previous_answer: str, error_lines: list[str],
                 warning_lines: list[str] | None = None) -> str:
    parts = [base, "", "## Your previous answer", "", previous_answer.strip(), "",
             "## The checker rejected it",
             "", "Fix every error below and return the full corrected JSON (all scenes):", ""]
    parts += [f"- {e}" for e in error_lines]
    if warning_lines:
        parts += ["", "Review warnings (do not fail, but fix them if you can):", ""]
        parts += [f"- {w}" for w in warning_lines]
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------ assembling

def article_title(body: str, meta: dict, fallback: str) -> str:
    if isinstance(meta.get("title"), str) and meta["title"].strip():
        return meta["title"].strip()
    for line in body.splitlines():
        m = re.match(r"^#\s+(.+?)\s*#*\s*$", line.strip())
        if m:
            from pipeline.textnorm import normalize

            return normalize(m.group(1))
    return fallback


class AnswerError(ValueError):
    """The answer is not JSON of the expected shape (sent back like a checker error)."""


def parse_answer(text: str) -> dict:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", t, flags=re.S)
    if m:
        t = m.group(1)
    try:
        data = json.loads(t)
    except json.JSONDecodeError as exc:
        raise AnswerError(f"the answer is not valid JSON: {exc}") from None
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise AnswerError('the answer must be a JSON object {"scenes": [...]}')
    return data


def assemble(answer: dict, article_id: str, title: str, meta: dict) -> dict:
    """The scenes document: the LLM's scenes plus the fields code owns."""
    scenes = []
    for sc in answer["scenes"]:
        if not isinstance(sc, dict):
            scenes.append(sc)  # the schema check reports it
            continue
        sc = dict(sc)
        visual = sc.get("visual")
        if isinstance(visual, dict):
            visual = dict(visual)
            if visual.get("type") != "card":
                visual.pop("variant", None)  # a variant only means something on a card
            if visual.get("icon") in ("", None):
                visual.pop("icon", None)
            if visual.get("items") == [] and visual.get("type") in ("card", "bullets", "quote"):
                visual.pop("items", None)
            sc["visual"] = visual
        if isinstance(sc.get("voiceover"), list):
            sc["voiceover"] = [
                ({**line, "spoken": None} if isinstance(line, dict) else line) for line in sc["voiceover"]
            ]
        sc["duration_s"] = None
        scenes.append(sc)
    return {
        "article": {"id": article_id, "title": title, "publisher": meta["publisher"],
                    "promotional": bool(meta["promotional"])},
        "scenes": scenes,
    }


# ------------------------------------------------------------------ stage

def generate_scenes(sentences_data: dict, body: str, meta: dict, cfg: dict, article_id: str,
                    log=print, save_raw=None, **llm_kwargs):
    """The generate-and-check loop. Returns (doc or None, Report or None, attempts).

    Raises llm.ProviderUnavailable / llm.LLMSetupError from the adapters.
    """
    base = build_prompt(sentences_data, meta, cfg)
    schema = llm_schema()
    title = article_title(body, meta, article_id)
    max_retries = int(cfg["llm"]["max_retries"])
    prompt = base
    doc = rep = None
    for attempt in range(1, max_retries + 2):
        log(f"attempt {attempt} of {max_retries + 1}: {cfg['llm']['provider']} "
            f"({', '.join(llm.models_in_order(cfg['llm']))})")
        res = llm.generate(prompt, cfg["llm"], schema=schema, log=log, **llm_kwargs)
        tokens = res.usage.get("totalTokenCount") or (
            (res.usage.get("input_tokens") or 0) + (res.usage.get("output_tokens") or 0)) or "?"
        log(f"  {res.model}: answer in {res.seconds:.0f} s, {tokens} tokens")
        if save_raw:
            save_raw(attempt, res)
        try:
            answer = parse_answer(res.text)
        except AnswerError as exc:
            errors, warnings = [f"[schema] {exc}"], []
            log(f"  checker: {exc}")
        else:
            doc = assemble(answer, article_id, title, meta)
            rep = verify.check_document(doc, sentences_data, body, meta, cfg, article_id=article_id)
            words = rep.stats.get("voiceover_words") if rep.stats else None
            if rep.passed:
                log(f"  checker: PASS ({words} voiceover words, {len(rep.warnings)} review warning(s))")
                return doc, rep, attempt
            errors, warnings = rep.error_lines(), [w.text() for w in rep.warnings]
            log(f"  checker: {len(errors)} error(s)" + (f", {words} voiceover words" if words else ""))
            for e in errors:
                log(f"   - {e}")
        prompt = retry_prompt(base, res.text, errors, warnings)
    return doc, rep, max_retries + 1


def run(ctx) -> int:
    """Stage entry point."""
    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix()  # noqa: E731
    try:
        sdata = sentences.load(p.sentences)
    except sentences.SentencesError as exc:
        print(f"error: {exc}")
        return exitcodes.SETUP
    if sdata.get("body_sha256") and sdata["body_sha256"] != sentences.body_sha256(ctx.body):
        print("error: the sentences file is older than the article; run again from the sentences stage")
        return exitcodes.SETUP

    llm_dir = p.output_dir / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    for old in llm_dir.glob("attempt-*.txt"):
        old.unlink()
    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        log_lines.append(msg)

    def save_raw(attempt: int, res) -> None:
        (llm_dir / f"attempt-{attempt}.txt").write_bytes(res.text.encode("utf-8"))

    log(f"started {datetime.now(timezone.utc).isoformat(timespec='seconds')}, "
        f"{sdata.get('count', len(sdata['sentences']))} sentences")
    code = exitcodes.OK
    try:
        doc, rep, attempts = generate_scenes(sdata, ctx.body, ctx.meta, ctx.config, p.id,
                                             log=log, save_raw=save_raw)
    except llm.LLMSetupError as exc:
        log(f"error: {exc}")
        code, doc, rep = exitcodes.SETUP, None, None
    except llm.ProviderUnavailable as exc:
        log(f"error: {exc}")
        log("Try again later, add models to llm.fallback_models, or switch llm.provider "
            "(see pipeline/config.yaml).")
        code, doc, rep = exitcodes.PROVIDER, None, None
    else:
        if doc is not None:
            sentences.write_json(p.scenes, doc)
            log(f"wrote {rel(p.scenes)}")
        if rep is not None:
            verify.write_report(p.verify_report, verify.build_report(rep, p.id, doc))
        if rep is None or not rep.passed:
            log(f"FAIL: the checker still fails after {attempts} attempt(s); see "
                f"{rel(p.verify_report)}. Fix the scenes file by hand and run --from verify, "
                "or run --from scenes again.")
            code = exitcodes.CHECK_FAILED
    (llm_dir / "run.log").write_bytes(("\n".join(log_lines) + "\n").encode("utf-8"))
    return code
