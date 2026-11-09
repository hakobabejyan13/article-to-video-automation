"""`verify` stage: the plain-code checker (PLAN.md section 4).

Hard checks (any error fails the run, exit 1):
  1 schema        JSON Schema, scene ids, article fields match the front matter,
                  every source_ids number exists, claim scenes cite every line
  2 verbatim      every sentence is found in the normalised article; quotes on
                  screen are found word for word in their cited sentences
  3 counts        every cardinal number (and currency amount) in a claim is in its
                  cited sentences; no rounding
  4 ordinals      every ordinal in a claim matches an ordinal in its cited sentences
                  (ordinal word, (1)-style marker, list number, rank column)
  5 pairing       each visual item's label and value appear in one cited sentence
                  or one table row
  6 no_claim      on-screen text without source_ids has no numbers
  7 attribution   (promotional articles) disclosure card first; publisher scenes
                  attribute; company scenes name the company
  8 length        total voiceover words inside the range from video.target_seconds
                  and speech.words_per_minute

Review warnings (listed, never fail): inference words, judging words not in the cited
sentences, citations from fewer than review_warnings.min_sections sections.

`check_document()` is the function the scenes stage (T3) calls in its retry loop;
`run()` is the stage entry point and writes output/<id>/verify-report.json.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline import exitcodes, numbers
from pipeline.claims import Claim, content_sha256, iter_claims, voiceover_text
from pipeline.sentences import body_sha256, normalized_article
from pipeline.textnorm import fold

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "scenes.schema.json"

DEFAULT_RANK_HEADERS = ["rank", "ranking", "position", "place", "#", "no.", "no"]


@dataclass
class Issue:
    check: str
    message: str
    scene: object = None
    where: str | None = None

    def text(self) -> str:
        loc = ""
        if self.scene is not None:
            loc = f"scene {self.scene}"
            if self.where:
                loc += f" {self.where}"
            loc += ": "
        return f"[{self.check}] {loc}{self.message}"

    def as_dict(self) -> dict:
        d = {"check": self.check, "message": self.message}
        if self.scene is not None:
            d["scene"] = self.scene
        if self.where:
            d["where"] = self.where
        return d


@dataclass
class Report:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.errors

    def error(self, check, message, scene=None, where=None):
        self.errors.append(Issue(check, message, scene, where))

    def warn(self, check, message, scene=None, where=None):
        self.warnings.append(Issue(check, message, scene, where))

    def as_dict(self) -> dict:
        return {
            "result": "pass" if self.passed else "fail",
            "errors": [e.as_dict() for e in self.errors],
            "warnings": [w.as_dict() for w in self.warnings],
            "stats": self.stats,
        }

    def error_lines(self) -> list[str]:
        return [e.text() for e in self.errors]


# ---------------------------------------------------------------- helpers

def word_range(cfg: dict) -> tuple[int, int]:
    lo_s, hi_s = cfg["video"]["target_seconds"]
    wpm = cfg["speech"]["words_per_minute"]
    return math.ceil(lo_s * wpm / 60), math.floor(hi_s * wpm / 60)


def count_words(text: str) -> int:
    return len(text.split())


def _rank_header_re(cfg: dict) -> re.Pattern:
    words = cfg.get("rank_headers") or DEFAULT_RANK_HEADERS
    alts = "|".join(re.escape(w.lower()) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"^(?:{alts})(?:\W|$)")


@dataclass
class SourceNumbers:
    cardinals: set[str]
    ordinals: set[str]
    money: set[tuple[str, str]]


def sentence_numbers(entry: dict, rank_re: re.Pattern) -> SourceNumbers:
    """Numbers a sentence or table row supports. Rank-column cells count as ordinals only."""
    if entry.get("kind") == "table_row" and isinstance(entry.get("cells"), dict):
        total = numbers.Numbers()
        ords: set[str] = set()
        for header, cell in entry["cells"].items():
            n = numbers.extract(cell)
            if rank_re.match(fold(header)):
                ords |= n.cardinals | n.ordinals
            else:
                total = total | n
        return SourceNumbers(total.cardinals, total.ordinals | ords, total.money)
    n = numbers.extract(entry.get("text", ""))
    return SourceNumbers(n.cardinals, n.ordinals | numbers.extract_marker(entry.get("marker")), n.money)


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['.&][a-z0-9]+)*")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(fold(text))


def _stem(tok: str) -> str:
    if tok.endswith("'s") and len(tok) > 3:  # possessive: "Acme's" matches "Acme"
        return tok[:-2]
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok


def label_in(label: str, text: str) -> bool:
    """True if the label appears in the text: as a phrase, or every word of it does."""
    lab = fold(label).strip(" .,:;!?\"'")
    hay = fold(text)
    if lab and lab in hay:
        return True
    words = _tokens(label)
    if not words:
        return False
    have = {_stem(t) for t in _tokens(text)}
    return all(_stem(w) in have for w in words)


def value_in(value: str, text_or_cell_numbers: SourceNumbers, text: str) -> bool:
    v = numbers.extract(value)
    have = text_or_cell_numbers.cardinals | text_or_cell_numbers.ordinals
    if v.cardinals or v.ordinals:
        return (v.cardinals | v.ordinals) <= have
    return fold(value).strip(" .,:;!?\"'") in fold(text)


def _fmt_ids(ids) -> str:
    return "[" + ", ".join(str(i) for i in ids) + "]"


def _fmt_set(values) -> str:
    def key(v):
        try:
            return (0, float(v))
        except ValueError:
            return (1, v)

    return ", ".join(sorted(values, key=key)) if values else "none"


def _phrase_found(phrase: str, text: str) -> bool:
    p = fold(phrase)
    return bool(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", text))


# ---------------------------------------------------------------- the checker

def check_document(doc, sentences_data: dict, body: str, meta: dict, cfg: dict,
                   article_id: str | None = None) -> Report:
    """Run every check on a parsed scenes JSON. Never raises on bad input."""
    import jsonschema

    rep = Report()
    entries = sentences_data.get("sentences") or []
    by_n = {e.get("n"): e for e in entries if isinstance(e, dict)}
    publisher = meta.get("publisher", "")
    promotional = bool(meta.get("promotional"))
    rank_re = _rank_header_re(cfg)

    # ---- 1 schema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    for err in schema_errors[:30]:
        path = "/".join(str(p) for p in err.absolute_path) or "(top level)"
        rep.error("schema", f"{path}: {err.message}")
    if schema_errors:
        rep.stats = {"scenes": None}
        return rep  # the other checks need a well-formed document

    if sentences_data.get("body_sha256") and sentences_data["body_sha256"] != body_sha256(body):
        rep.error("schema", "the sentences file is older than the article (body changed); "
                  "run again from the sentences stage")

    art = doc["article"]
    if article_id is not None and art["id"] != article_id:
        rep.error("schema", f"article.id is {art['id']!r}, expected {article_id!r} (from the file name)")
    if art["publisher"] != publisher:
        rep.error("schema", f"article.publisher is {art['publisher']!r}, but the front matter says "
                  f"{publisher!r}; copy it from the front matter")
    if art["promotional"] != promotional:
        rep.error("schema", f"article.promotional is {art['promotional']}, but the front matter says "
                  f"{promotional}")

    scenes = doc["scenes"]
    ids = [s["id"] for s in scenes]
    if ids != list(range(1, len(scenes) + 1)):
        rep.error("schema", f"scene ids must be 1, 2, 3 ... in order; found {ids}")

    claims = iter_claims(doc)
    for c in claims:
        unknown = [i for i in c.source_ids if i not in by_n]
        if unknown:
            rep.error("schema", f"source_ids {unknown} do not exist (the sentences file has "
                      f"1-{len(entries)})", c.scene_id, c.where)
        if c.kind == "voiceover" and c.claim_owner != "none" and not c.source_ids:
            rep.error("schema", f"voiceover line in a {c.claim_owner} scene cites no sentence; "
                      "add source_ids, or set claim_owner to none if the scene makes no claim",
                      c.scene_id, c.where)

    def cited(c: Claim) -> list[dict]:
        return [by_n[i] for i in c.source_ids if i in by_n]

    def has_unknown(c: Claim) -> bool:
        # already reported above; checking against the remaining ids would only add noise
        return any(i not in by_n for i in c.source_ids)

    # ---- 2 verbatim
    norm_art = normalized_article(body)
    for e in entries:
        if e.get("text", "") not in norm_art:
            rep.error("verbatim", f"sentence {e.get('n')} is not found word for word in the article: "
                      f"{e.get('text', '')[:100]!r}; run again from the sentences stage")
    for c in claims:
        if c.kind == "on_screen" and c.element == "quote":
            q = fold(c.text).strip(" \"'")
            if not any(q in fold(e["text"]) for e in cited(c)):
                rep.error("verbatim", f"quote {c.text[:80]!r} is not word for word in its cited "
                          f"sentences {_fmt_ids(c.source_ids)}", c.scene_id, c.where)

    # ---- 3 counts and 4 ordinals
    for c in claims:
        n = numbers.extract(c.text)
        if n.is_empty() and not n.money:
            continue
        if not c.source_ids or has_unknown(c):
            continue  # no ids: reported by check 6; unknown ids: reported by check 1
        src = [sentence_numbers(e, rank_re) for e in cited(c)]
        have_card = set().union(*(s.cardinals for s in src)) if src else set()
        have_ord = set().union(*(s.ordinals for s in src)) if src else set()
        have_money = set().union(*(s.money for s in src)) if src else set()
        missing = n.cardinals - have_card
        if missing:
            rep.error("counts", f"number(s) {_fmt_set(missing)} in {c.text[:90]!r} are not in its cited "
                      f"sentences {_fmt_ids(c.source_ids)} (they state: {_fmt_set(have_card)}). "
                      "Use the article's exact numbers, no rounding", c.scene_id, c.where)
        for cur, val in sorted(n.money - have_money):
            if val in have_card:
                others = sorted(cu for cu, v in have_money if v == val)
                said = f" as {', '.join(others)}" if others else " without that currency"
                rep.error("counts", f"amount {cur} {val} has the wrong currency: the cited sentences "
                          f"{_fmt_ids(c.source_ids)} give {val}{said}", c.scene_id, c.where)
        bad_ord = n.ordinals - have_ord
        if bad_ord:
            hint = ""
            as_count = bad_ord & have_card
            if as_count:
                hint = f" ({_fmt_set(as_count)} appears there only as a count, which cannot support a rank)"
            rep.error("ordinals", f"ordinal(s) {_fmt_set(bad_ord)} in {c.text[:90]!r} have no matching "
                      f"ordinal, list number or rank column in the cited sentences "
                      f"{_fmt_ids(c.source_ids)}{hint}", c.scene_id, c.where)

    # ---- 5 label-value pairing
    for c in claims:
        if c.kind != "item" or has_unknown(c):
            continue
        ok = False
        for e in cited(c):
            if e.get("kind") == "table_row" and isinstance(e.get("cells"), dict):
                cells = list(e["cells"].values())
                if any(label_in(c.label, cell) for cell in cells) and value_in(
                    c.value, sentence_numbers(e, rank_re), e["text"]
                ):
                    ok = True
            elif label_in(c.label, e.get("text", "")) and value_in(
                c.value, sentence_numbers(e, rank_re), e.get("text", "")
            ):
                ok = True
            if ok:
                break
        if not ok:
            rep.error("pairing", f"label {c.label!r} and value {c.value!r} do not appear together in "
                      f"any one cited sentence or table row {_fmt_ids(c.source_ids)}",
                      c.scene_id, c.where)

    # ---- 6 no-claim text
    for c in claims:
        if c.source_ids or not numbers.has_number(c.text):
            continue
        if c.kind == "on_screen":
            rep.error("no_claim", f"on-screen text {c.text!r} has no source_ids but contains a number; "
                      "cite the sentence or remove the number", c.scene_id, c.where)
        else:
            rep.error("counts", f"{c.text[:90]!r} states a number but cites no sentence",
                      c.scene_id, c.where)

    # ---- 7 attribution (promotional articles)
    if promotional:
        pub = fold(publisher)
        first = scenes[0]
        vis = first["visual"]
        vo1 = fold(voiceover_text(first))
        if vis.get("type") != "card" or vis.get("variant") != "disclosure":
            rep.error("attribution", "the article is promotional, so scene 1 must be a card of "
                      "variant 'disclosure'", first["id"])
        dw = cfg["disclosure_words"]
        lacks = []
        if pub not in vo1:
            lacks.append(f"name {publisher}")
        if not any(_phrase_found(w, vo1) for w in dw["publish"]):
            lacks.append("say it publishes the piece (" + ", ".join(dw["publish"][:3]) + " ...)")
        if not any(_phrase_found(w, vo1) for w in dw["rank"]):
            lacks.append("say it ranks itself (" + ", ".join(dw["rank"][:3]) + " ...)")
        if lacks:
            rep.error("attribution", "the disclosure voiceover must " + "; ".join(lacks), first["id"], "voiceover")
        phrases = [p.format(publisher=publisher) for p in cfg["attribution_phrases"]]
        for s in scenes[1:]:
            vo = fold(voiceover_text(s))
            owner = s["claim_owner"]
            if owner == "publisher":
                if not any(_phrase_found(p, vo) for p in phrases):
                    rep.error("attribution", f"publisher claim without attribution; the voiceover needs "
                              f"one of: {', '.join(phrases[:5])} ...", s["id"], "voiceover")
            elif owner.startswith("company:"):
                name = owner.split(":", 1)[1].strip()
                if fold(name) not in vo:
                    rep.error("attribution", f"company claim: the voiceover must name {name} as the source",
                              s["id"], "voiceover")
                scene_ids = {i for c in claims if c.scene_index == scenes.index(s) for i in c.source_ids}
                if not any(fold(name) in fold(by_n[i]["text"]) for i in scene_ids if i in by_n):
                    rep.error("attribution", f"company {name!r} is not named in any sentence this scene cites",
                              s["id"])

    # ---- 8 length
    lo, hi = word_range(cfg)
    words = sum(count_words(c.text) for c in claims if c.kind == "voiceover")
    lo_s, hi_s = cfg["video"]["target_seconds"]
    wpm = cfg["speech"]["words_per_minute"]
    if not lo <= words <= hi:
        rep.error("length", f"the voiceover has {words} words; {lo_s}-{hi_s} s at {wpm} words per minute "
                  f"needs {lo}-{hi} words. {'Add' if words < lo else 'Cut'} about "
                  f"{(lo - words) if words < lo else (words - hi)} words, or change video.target_seconds")

    # ---- review warnings
    rw = cfg["review_warnings"]
    for c in claims:
        if c.kind == "item":
            continue
        t = fold(c.text)
        for w in rw["inference_words"]:
            if _phrase_found(w, t):
                rep.warn("inference", f"inference word {w!r} in {c.text[:90]!r}; check that the article "
                         "itself makes this link", c.scene_id, c.where)
        src = " ".join(fold(e["text"]) for e in cited(c))
        for w in rw["judging_words"]:
            if _phrase_found(w, t) and not _phrase_found(w, src):
                rep.warn("judging", f"judging word {w!r} is not in the cited sentences "
                         f"{_fmt_ids(c.source_ids)}", c.scene_id, c.where)
    all_ids = sorted({i for c in claims for i in c.source_ids if i in by_n})
    sections = sorted({by_n[i].get("section", "") for i in all_ids})
    if len(sections) < rw["min_sections"]:
        rep.warn("coverage", f"all citations come from {len(sections)} section(s) of the article "
                 f"(fewer than {rw['min_sections']}); the video may miss most of the article")

    rep.stats = {
        "scenes": len(scenes),
        "claims": sum(1 for c in claims if c.source_ids),
        "voiceover_words": words,
        "word_range": [lo, hi],
        "sentences_cited": len(all_ids),
        "sections_cited": len(sections),
    }
    return rep


# ---------------------------------------------------------------- stage

def build_report(rep: Report, article_id: str, scenes_doc) -> dict:
    data = {
        "article": article_id,
        "verify": {
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenes_sha256": content_sha256(scenes_doc) if isinstance(scenes_doc, dict) else None,
            **rep.as_dict(),
        },
    }
    return data


def load_report(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_report(path: Path, data: dict) -> None:
    """Write verify-report.json, keeping any other top-level keys (the T6 check stage adds 'check')."""
    from pipeline.sentences import write_json

    old = {}
    if Path(path).exists():
        try:
            old = load_report(path)
        except (json.JSONDecodeError, OSError):
            old = {}
    if not isinstance(old, dict):
        old = {}
    old.pop("check", None)  # a new verify makes any earlier final check stale
    old.update(data)
    write_json(path, old)


def run(ctx) -> int:
    """Stage entry point."""
    from pipeline import sentences

    p = ctx.paths
    rel = lambda x: x.relative_to(p.root).as_posix()  # noqa: E731
    try:
        sdata = sentences.load(p.sentences)
    except sentences.SentencesError as exc:
        print(f"error: {exc}")
        return exitcodes.SETUP
    if not p.scenes.exists():
        print(f"error: scenes file not found: {rel(p.scenes)}")
        return exitcodes.SETUP
    try:
        doc = json.loads(p.scenes.read_text(encoding="utf-8"))
        rep = check_document(doc, sdata, ctx.body, ctx.meta, ctx.config, article_id=p.id)
    except json.JSONDecodeError as exc:
        doc = None
        rep = Report()
        rep.error("schema", f"the scenes file is not valid JSON: {exc}")

    write_report(p.verify_report, build_report(rep, p.id, doc))
    s = rep.stats
    if rep.passed:
        print(f"PASS: {s['scenes']} scenes, {s['claims']} claims, {s['voiceover_words']} voiceover words "
              f"(range {s['word_range'][0]}-{s['word_range'][1]}), {s['sections_cited']} sections cited.")
    else:
        print(f"FAIL: {len(rep.errors)} error(s):")
        for line in rep.error_lines():
            print("  - " + line)
    if rep.warnings:
        print(f"{len(rep.warnings)} review warning(s):")
        for w in rep.warnings:
            print("  - " + w.text())
    print(f"Report: {rel(p.verify_report)}")
    return exitcodes.OK if rep.passed else exitcodes.CHECK_FAILED
