"""Convert a .docx to plain text with the standard library, and check a copy.

    python -m pipeline.tools.docx_text convert brief.docx docs/brief.md
    python -m pipeline.tools.docx_text check brief.docx docs/brief.md

Each Word paragraph becomes one line; empty paragraphs become blank lines.
`check` compares the two texts word for word (whitespace-separated tokens) and
exits 1 at the first difference.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def paragraphs(docx: Path) -> list[str]:
    with zipfile.ZipFile(docx) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    if body is None:
        return []
    out = []
    for p in body.iter(f"{W}p"):
        parts = []
        for el in p.iter():
            if el.tag == f"{W}t":
                parts.append(el.text or "")
            elif el.tag == f"{W}tab":
                parts.append("\t")
            elif el.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
            elif el.tag == f"{W}noBreakHyphen":
                parts.append("-")
        out.append("".join(parts))
    return out


def to_text(docx: Path) -> str:
    return "\n".join(paragraphs(docx)) + "\n"


def compare(docx: Path, text_file: Path) -> tuple[bool, str]:
    a = to_text(docx).split()
    b = Path(text_file).read_text(encoding="utf-8").split()
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            ctx_a = " ".join(a[max(0, i - 5) : i + 5])
            ctx_b = " ".join(b[max(0, i - 5) : i + 5])
            return False, f"word {i + 1} differs: {x!r} vs {y!r}\n  docx: {ctx_a}\n  text: {ctx_b}"
    if len(a) != len(b):
        return False, f"word counts differ: docx {len(a)}, text {len(b)}"
    return True, f"match: {len(a)} words, identical"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.tools.docx_text")
    ap.add_argument("action", choices=["convert", "check"])
    ap.add_argument("docx", type=Path)
    ap.add_argument("text_file", type=Path)
    args = ap.parse_args(argv)
    if args.action == "convert":
        args.text_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.text_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(to_text(args.docx))
        print(f"wrote {args.text_file}")
    ok, msg = compare(args.docx, args.text_file)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
