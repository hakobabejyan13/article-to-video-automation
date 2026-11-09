"""`sentences` stage: split the article into numbered sentences and table rows.

Plain code, no LLM (PLAN.md sections 0 and 3). Output entries:

    {"n": 12, "section": "...", "line": 11, "kind": "text", "text": "..."}

- `kind` is `text`, `list_item`, `quote` (inside a blockquote), `table_header` or
  `table_row`. Table rows also keep `"cells": {"<header>": "<value>", ...}`.
- The first sentence of an ordered-list item keeps the item's number as
  `"marker": "3."`, so the checker can treat it as an ordinal.
- `line` is the line number in the article file (front matter included), so a
  person can open the file at that line.
- `section` is the text of the nearest heading above.
- Every `text` is normalised (textnorm.normalize) and is found verbatim in the
  normalised article (`normalized_article`).

The file written is `scenes/<id>.sentences.json`:

    {"article": "<id>", "body_sha256": "...", "count": N, "sentences": [...]}

`body_sha256` lets the checker notice a sentences file that is older than the article.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline import exitcodes
from pipeline.textnorm import fix_chars, normalize

# Tokens that end with a period but do not end a sentence (case-sensitive).
ABBREVIATIONS = {
    "e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "a.m.", "p.m.",
    "Inc.", "Ltd.", "Co.", "Corp.", "LLC.", "St.", "No.", "Nos.", "Fig.", "Vol.",
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "Gen.", "Gov.", "Sen.", "Rep.",
    "U.S.", "U.K.", "U.N.", "E.U.",
    "Jan.", "Feb.", "Mar.", "Apr.", "Jun.", "Jul.", "Aug.", "Sep.", "Sept.", "Oct.",
    "Nov.", "Dec.",
}

_HEADING_RE = re.compile(r"^#{1,6}(?:\s+(.*?))?\s*#*\s*$")
_SETEXT_RE = re.compile(r"^(=+|-+)\s*$")
_HR_RE = re.compile(r"^(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
_FENCE_RE = re.compile(r"^(```|~~~)")
_QUOTE_RE = re.compile(r"^(?:>\s?)+")
_BULLET_RE = re.compile(r"^[-*+]\s+")
_ORDERED_RE = re.compile(r"^(\d{1,9})([.)])\s+")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$")
_PIPE_SPLIT_RE = re.compile(r"(?<!\\)\|")
_BOUNDARY_RE = re.compile(r"[.!?]+[\"')\]]*\s+")
_SENTENCE_START = set("\"'$#(£€[")


def _is_table_sep(line: str) -> bool:
    return "-" in line and bool(_TABLE_SEP_RE.match(line.strip()))


def table_cells(line: str) -> list[str]:
    """Cells of one Markdown table line, normalised. Escaped pipes stay in the cell."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [normalize(c) for c in _PIPE_SPLIT_RE.split(s)]


def strip_block_markers(line: str) -> str:
    """Remove a heading's #, blockquote >, and a list marker from the start of a line."""
    s = _QUOTE_RE.sub("", line.strip())
    m = _HEADING_RE.match(s)
    if m:
        return m.group(1) or ""
    s = _BULLET_RE.sub("", s)
    s = _ORDERED_RE.sub("", s)
    return s


def normalized_article(body: str) -> str:
    """The whole article as one normalised string, for verbatim checks.

    Line by line, independent of the sentence splitter: block markers removed,
    table rows written as their cells joined by " | ", separator rows dropped,
    then inline Markdown removed and whitespace collapsed.
    """
    lines = [_QUOTE_RE.sub("", fix_chars(raw).strip()) for raw in re.split(r"\r?\n", body)]
    out, in_table = [], False
    for k, s in enumerate(lines):
        if not s or "|" not in s:
            in_table = False
        if not s or _HR_RE.match(s) or _SETEXT_RE.match(s):
            continue
        if _is_table_sep(s) and in_table:
            continue
        if not in_table and "|" in s and k + 1 < len(lines) and _is_table_sep(lines[k + 1]):
            in_table = True
        if in_table:
            out.append(" | ".join(table_cells(s)))
            continue
        out.append(normalize(strip_block_markers(s)))
    return " ".join(x for x in out if x)


def split_sentences(text: str) -> list[tuple[int, str]]:
    """Split normalised text into sentences. Returns (start offset, sentence)."""
    parts: list[tuple[int, str]] = []
    start = 0
    for m in _BOUNDARY_RE.finditer(text):
        nxt = text[m.end() : m.end() + 1]
        if not nxt or not (nxt.isupper() or nxt.isdigit() or nxt in _SENTENCE_START):
            continue
        before = text[start : m.end()].split()
        last = before[-1] if before else ""
        last_core = last.rstrip("\"')]")
        if last_core in ABBREVIATIONS or re.fullmatch(r"[A-Z]\.", last_core):
            continue
        sentence = text[start : m.end()].strip()
        if sentence:
            parts.append((start, sentence))
        start = m.end()
    tail = text[start:].strip()
    if tail:
        parts.append((start, tail))
    return parts


@dataclass
class _Block:
    kind: str  # text | list_item | quote
    pieces: list[tuple[int, str]] = field(default_factory=list)  # (file line, normalised text)
    marker: str | None = None


class _Splitter:
    def __init__(self, line_offset: int):
        self.offset = line_offset
        self.entries: list[dict] = []
        self.section = ""
        self.block: _Block | None = None

    def add(self, **entry) -> None:
        entry = {"n": len(self.entries) + 1, "section": self.section, **entry}
        self.entries.append(entry)

    def flush(self) -> None:
        b, self.block = self.block, None
        if b is None or not b.pieces:
            return
        joined, starts, pos = [], [], 0
        for _, text in b.pieces:
            starts.append(pos)
            joined.append(text)
            pos += len(text) + 1
        text = " ".join(joined)
        first = True
        for off, sentence in split_sentences(text):
            idx = max(i for i, s in enumerate(starts) if s <= off)
            entry = {"line": b.pieces[idx][0], "kind": b.kind, "text": sentence}
            if first and b.marker:
                entry["marker"] = b.marker
            first = False
            self.add(**entry)

    def start_block(self, kind: str, marker: str | None = None) -> _Block:
        self.flush()
        self.block = _Block(kind=kind, marker=marker)
        return self.block

    def run(self, body: str) -> list[dict]:
        lines = re.split(r"\r?\n", body)
        i, fence = 0, None
        while i < len(lines):
            raw = fix_chars(lines[i])
            lineno = i + 1 + self.offset
            stripped = raw.strip()
            i += 1

            if fence:
                if stripped.startswith(fence):
                    fence = None
                continue
            m = _FENCE_RE.match(stripped)
            if m:
                self.flush()
                fence = m.group(1)
                continue
            if stripped.startswith("<!--"):
                self.flush()
                while "-->" not in stripped and i < len(lines):
                    stripped = lines[i].strip()
                    i += 1
                continue

            in_quote = bool(_QUOTE_RE.match(stripped))
            content = _QUOTE_RE.sub("", stripped).strip()

            if not content:
                self.flush()
                continue

            # Setext heading: a single paragraph line underlined with === or ---.
            if (
                _SETEXT_RE.match(content)
                and not in_quote
                and self.block is not None
                and self.block.kind == "text"
                and len(self.block.pieces) == 1
            ):
                self.section = self.block.pieces[0][1]
                self.block = None
                continue
            if _HR_RE.match(content):
                self.flush()
                continue

            h = _HEADING_RE.match(content)
            if h and content.startswith("#"):
                self.flush()
                self.section = normalize(h.group(1) or "")
                continue

            # Table: a line with pipes followed by a separator row.
            if "|" in content and i < len(lines) and _is_table_sep(_QUOTE_RE.sub("", lines[i].strip())):
                self.flush()
                headers = table_cells(content)
                self.add(line=lineno, kind="table_header", text=" | ".join(headers))
                i += 1  # separator row
                while i < len(lines):
                    row = _QUOTE_RE.sub("", fix_chars(lines[i]).strip())
                    if not row or "|" not in row:
                        break
                    cells = table_cells(row)
                    names = _unique_headers(headers, len(cells))
                    self.add(
                        line=i + 1 + self.offset,
                        kind="table_row",
                        text=" | ".join(cells),
                        cells={names[k]: cells[k] for k in range(len(cells))},
                    )
                    i += 1
                continue

            kind = "quote" if in_quote else "text"
            mb, mo = _BULLET_RE.match(content), _ORDERED_RE.match(content)
            if mb or mo:
                marker = f"{mo.group(1)}{mo.group(2)}" if mo else None
                block = self.start_block("quote" if in_quote else "list_item", marker)
                content = content[(mb or mo).end() :]
            elif self.block is not None and (
                self.block.kind == kind
                # a plain line right after a list item continues that item
                or (not in_quote and self.block.kind == "list_item")
            ):
                block = self.block
            else:
                block = self.start_block(kind)
            text = normalize(content)
            if text:
                block.pieces.append((lineno, text))
        self.flush()
        return self.entries


def _unique_headers(headers: list[str], n_cells: int) -> list[str]:
    """Header names for n cells: blanks become 'column N', duplicates get ' (2)'."""
    names, seen = [], {}
    for k in range(n_cells):
        h = headers[k] if k < len(headers) and headers[k] else f"column {k + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        names.append(h)
    return names


def split_article(body: str, line_offset: int = 0) -> list[dict]:
    """Numbered entries for an article body. `line_offset` = lines before the body."""
    return _Splitter(line_offset).run(body)


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def body_line_offset(article: Path) -> int:
    """Number of file lines before the body (the front matter block and its fences)."""
    from pipeline.frontmatter import split_bytes

    data = Path(article).read_bytes()
    _, body = split_bytes(data)
    prefix = data[: len(data) - len(body)]
    return prefix.count(b"\n")


def build(body: str, article_id: str, line_offset: int = 0) -> dict:
    entries = split_article(body, line_offset)
    return {
        "article": article_id,
        "body_sha256": body_sha256(body),
        "count": len(entries),
        "sentences": entries,
    }


def write_json(path: Path, data: object) -> None:
    """UTF-8 JSON with LF line endings on every OS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


class SentencesError(ValueError):
    pass


def load(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SentencesError(f"sentences file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SentencesError(f"sentences file is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("sentences"), list):
        raise SentencesError("sentences file must be an object with a 'sentences' list")
    return data


def run(ctx) -> int:
    """Stage entry point."""
    offset = body_line_offset(ctx.paths.article)
    data = build(ctx.body, ctx.paths.id, offset)
    if not data["sentences"]:
        print("error: the article has no text to split", flush=True)
        return exitcodes.SETUP
    write_json(ctx.paths.sentences, data)
    kinds: dict[str, int] = {}
    for e in data["sentences"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
    print(f"{data['count']} entries ({summary}) -> {ctx.paths.sentences.relative_to(ctx.paths.root).as_posix()}")
    return exitcodes.OK
