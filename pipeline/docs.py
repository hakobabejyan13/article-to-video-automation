"""`docs` stage: script and fact sheet (PLAN.md section 4). No LLM.

Writes output/<id>/script.md, factsheet.md and factsheet.csv. The fact sheet has one
row per claim: each voiceover line, each on-screen text with source_ids, and each
visual item. Timecodes are filled only when audio/<id>/timing.json exists (after the
tts stage); before that the column shows "-".

timing.json (written by the tts stage, T4):

    {"total_s": 74.2,
     "scenes": [{"id": 1, "start_s": 0.0, "duration_s": 6.4,
                 "lines": [{"start_s": 0.0, "duration_s": 6.4}]}, ...]}

`lines` is optional (one entry per voiceover line); without it, every row of a scene
gets the scene's start time.

The stage refuses to run (exit 1) unless verify-report.json says "pass" for the
current scenes file, so a fact sheet can never come from unchecked scenes.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from pipeline import exitcodes
from pipeline.claims import Claim, content_sha256, iter_claims

CSV_COLUMNS = [
    "scene", "timecode", "element", "text", "spoken", "attributed_to",
    "sentence_numbers", "cited_sentences", "section", "line",
]

ELEMENT_LABEL = {
    "voiceover": "voiceover",
    "headline": "headline",
    "sub": "subheadline",
    "bullet": "bullet",
    "quote": "quote",
    "bar": "bar",
    "price card": "price card",
    "big number": "big number",
}


def timecode(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total_tenths = int(seconds * 10 + 0.5)  # half up, not banker's rounding
    m, rest = divmod(total_tenths, 600)
    return f"{m}:{rest // 10:02d}.{rest % 10}"


def load_timing(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _scene_times(timing: dict | None) -> dict:
    """{scene id: (start, [line starts] or None)}"""
    out = {}
    if not timing:
        return out
    for s in timing.get("scenes") or []:
        lines = s.get("lines")
        out[s.get("id")] = (s.get("start_s"), [ln.get("start_s") for ln in lines] if lines else None)
    return out


def attributed_to(owner: str, publisher: str) -> str:
    if owner == "publisher":
        return f"{publisher} (publisher)"
    if owner.startswith("company:"):
        return f"{owner.split(':', 1)[1].strip()} (company), via {publisher}"
    return "-"


def _claim_time(c: Claim, times: dict) -> float | None:
    start, lines = times.get(c.scene_id, (None, None))
    if c.kind == "voiceover" and lines:
        k = int(c.where.split("[")[1].rstrip("]"))
        if k < len(lines):
            return lines[k]
    return start


def fact_rows(doc: dict, sentences_data: dict, publisher: str, timing: dict | None) -> list[dict]:
    by_n = {e["n"]: e for e in sentences_data.get("sentences") or []}
    times = _scene_times(timing)
    rows = []
    for c in iter_claims(doc):
        if not c.source_ids:
            continue  # text that makes no claim (no numbers, checked by verify)
        cited = [by_n[i] for i in c.source_ids if i in by_n]
        spoken = c.spoken if c.spoken and c.spoken != c.text else ""
        rows.append({
            "scene": c.scene_id,
            "timecode": timecode(_claim_time(c, times)),
            "element": ELEMENT_LABEL.get(c.element, c.element),
            "text": c.text,
            "spoken": spoken,
            "attributed_to": attributed_to(c.claim_owner, publisher),
            "sentence_numbers": [e["n"] for e in cited],
            "cited_sentences": [e["text"] for e in cited],
            "section": [e.get("section", "") for e in cited],
            "line": [e.get("line") for e in cited],
        })
    return rows


def _md_cell(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _dedupe(values: list) -> list:
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def factsheet_md(doc: dict, rows: list[dict], report: dict, timed: bool) -> str:
    art = doc["article"]
    v = report.get("verify", {})
    stats = v.get("stats", {})
    out = [
        f"# Fact sheet: {art['title']}",
        "",
        f"- Article: `{art['id']}`, publisher: {art['publisher']}, promotional: "
        f"{'yes' if art['promotional'] else 'no'}",
        f"- Checker: **{v.get('result', 'unknown').upper()}** ({v.get('checked_at', '-')}), "
        f"{stats.get('claims', len(rows))} claims, {stats.get('voiceover_words', '-')} voiceover words, "
        f"{stats.get('sections_cited', '-')} sections cited",
        f"- Timecodes: {'from audio timing' if timed else 'not yet (filled after the tts stage)'}",
        "",
        "## Review warnings",
        "",
    ]
    warnings = v.get("warnings") or []
    if warnings:
        for w in warnings:
            loc = f"scene {w['scene']} {w.get('where', '')}".strip() + ": " if "scene" in w else ""
            out.append(f"- [{w['check']}] {loc}{w['message']}")
    else:
        out.append("None.")
    out += [
        "",
        "Every claim below must be read against its cited sentence. The checker cannot tell "
        "whether a real sentence supports the claim it is used for.",
        "",
        "## Claims",
        "",
        "| Scene | Time | Element | Text | Spoken as | Attributed to | Sentence | Cited sentence (verbatim) | Section | Line |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append("| " + " | ".join([
            str(r["scene"]),
            r["timecode"],
            r["element"],
            _md_cell(r["text"]),
            _md_cell(r["spoken"]) if r["spoken"] else "",
            _md_cell(r["attributed_to"]),
            ", ".join(str(n) for n in r["sentence_numbers"]),
            "<br>".join(f"[{n}] {_md_cell(t)}" for n, t in zip(r["sentence_numbers"], r["cited_sentences"])),
            _md_cell("; ".join(_dedupe(r["section"]))),
            ", ".join(str(x) for x in _dedupe(r["line"])),
        ]) + " |")
    return "\n".join(out) + "\n"


def factsheet_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        w.writerow([
            r["scene"], r["timecode"], r["element"], r["text"], r["spoken"], r["attributed_to"],
            "; ".join(str(n) for n in r["sentence_numbers"]),
            "\n".join(f"[{n}] {t}" for n, t in zip(r["sentence_numbers"], r["cited_sentences"])),
            "; ".join(_dedupe(r["section"])),
            "; ".join(str(x) for x in _dedupe(r["line"])),
        ])
    return buf.getvalue()


def script_md(doc: dict, timing: dict | None, report: dict, source_tags: dict) -> str:
    art = doc["article"]
    times = _scene_times(timing)
    durations = {s.get("id"): s.get("duration_s") for s in (timing or {}).get("scenes") or []}
    stats = report.get("verify", {}).get("stats", {})
    total = (timing or {}).get("total_s")
    out = [
        f"# Script: {art['title']}",
        "",
        f"Article `{art['id']}`, publisher {art['publisher']}. "
        f"{len(doc['scenes'])} scenes, {stats.get('voiceover_words', '-')} voiceover words"
        + (f", {total:.1f} s of voiceover." if isinstance(total, (int, float)) else ", not voiced yet."),
        "",
    ]
    for scene in doc["scenes"]:
        sid = scene["id"]
        start = times.get(sid, (None, None))[0]
        vis = scene["visual"]
        vtype = vis["type"] + (f" ({vis['variant']})" if vis.get("variant") else "")
        head = f"## Scene {sid}"
        if start is not None:
            dur = durations.get(sid)
            head += f" ({timecode(start)}" + (f", {dur:.1f} s)" if isinstance(dur, (int, float)) else ")")
        out += [head, "", f"Visual: {vtype}. Claims by: {attributed_to(scene['claim_owner'], art['publisher'])}.", ""]
        tag = source_tags.get(sid)
        if tag:
            out += [f"Source tag on screen: {tag}", ""]
        out += ["**Voiceover**", ""]
        lines_t = times.get(sid, (None, None))[1]
        for k, line in enumerate(scene["voiceover"]):
            t = f"[{timecode(lines_t[k])}] " if lines_t and k < len(lines_t) else ""
            cite = f" (sentences {', '.join(str(i) for i in line['source_ids'])})" if line["source_ids"] else ""
            out.append(f"- {t}{line['text']}{cite}")
            spoken = line.get("spoken")
            if spoken and spoken != line["text"]:
                out.append(f"  - Spoken as: {spoken}")
        if scene["on_screen"]:
            out += ["", "**On screen**", ""]
            for item in scene["on_screen"]:
                out.append(f"- {ELEMENT_LABEL.get(item['role'], item['role'])}: {item['text']}")
        if vis.get("items"):
            out += ["", f"**{vis['type'].replace('_', ' ').capitalize()}**", ""]
            for item in vis["items"]:
                out.append(f"- {item['label']}: {item['value']}")
        out.append("")
    return "\n".join(out)


def fill_tag(template: str, **names: str) -> str:
    """Fill a source tag template. "{name}'s" becomes "Name'" for a name ending in s
    ("Example Shops' guide", not "Example Shops's guide")."""
    for key, name in names.items():
        if name.endswith(("s", "S")):
            template = template.replace("{" + key + "}'s", "{" + key + "}'")
    return template.format(**names)


def source_tags(doc: dict, cfg: dict) -> dict:
    """The fixed on-screen source tag per scene (PLAN.md section 2), from config."""
    pub = doc["article"]["publisher"]
    out = {}
    for s in doc["scenes"]:
        owner = s["claim_owner"]
        if owner == "publisher":
            out[s["id"]] = fill_tag(cfg["source_tag"]["publisher"], publisher=pub)
        elif owner.startswith("company:"):
            out[s["id"]] = fill_tag(cfg["source_tag"]["company"],
                                    publisher=pub, company=owner.split(":", 1)[1].strip())
    return out


def write_text(path: Path, text: str, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\ufeff" if bom else "").encode("utf-8") + text.encode("utf-8"))


def run(ctx) -> int:
    """Stage entry point."""
    from pipeline import sentences, verify

    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix()  # noqa: E731
    for f in (p.sentences, p.scenes, p.verify_report):
        if not f.exists():
            print(f"error: {rel(f)} not found; run the earlier stages first")
            return exitcodes.SETUP
    doc = json.loads(p.scenes.read_text(encoding="utf-8"))
    report = verify.load_report(p.verify_report)
    v = report.get("verify") or {}
    if v.get("result") != "pass":
        print(f"error: {rel(p.verify_report)} does not say pass; fix the scenes and run --from verify")
        return exitcodes.CHECK_FAILED
    if v.get("scenes_sha256") != content_sha256(doc):
        print(f"error: {rel(p.scenes)} changed after it was checked; run --from verify")
        return exitcodes.CHECK_FAILED
    sdata = sentences.load(p.sentences)
    timing = load_timing(p.timing)
    if timing is not None and timing.get("scenes_sha256") != content_sha256(doc):
        # A timing.json from an older scenes file would put wrong timecodes in the review.
        print(f"note: {rel(p.timing)} belongs to an older scenes file; writing without timecodes")
        timing = None
    rows = fact_rows(doc, sdata, ctx.meta["publisher"], timing)
    write_text(p.factsheet_md, factsheet_md(doc, rows, report, timing is not None))
    # BOM so Excel on Windows opens the CSV as UTF-8.
    write_text(p.factsheet_csv, factsheet_csv(rows), bom=True)
    write_text(p.script, script_md(doc, timing, report, source_tags(doc, ctx.config)))
    when = "with timecodes" if timing else "without timecodes"
    print(f"{len(rows)} claims -> {rel(p.factsheet_md)}, {rel(p.factsheet_csv)}; "
          f"script -> {rel(p.script)} ({when})")
    return exitcodes.OK
