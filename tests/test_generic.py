"""The pipeline stays generic (CLAUDE.md design principle, PLAN.md T7 done check).

Fails if a publisher name or an article id appears anywhere in the code under
pipeline/ or render/. Names come from the front matter of every article in source/
and in tests/fixtures/, ids from their file names; any `article-<digits>` is refused
too, so a new article is caught before its file even exists. Help texts use
`article-XX` as the example.
"""

import os
import re
from pathlib import Path

from pipeline.frontmatter import read_article

REPO = Path(__file__).resolve().parent.parent
CODE_DIRS = [REPO / "pipeline", REPO / "render"]
SKIP_PARTS = {"node_modules", "__pycache__", "out", ".cache"}
SKIP_NAMES = {"package-lock.json"}  # npm's own lock file, not code we write
CODE_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".ts", ".tsx", ".js", ".mjs", ".css"}
ANY_ARTICLE_ID = r"article-\d+"


def article_files() -> list[Path]:
    return sorted((REPO / "source").glob("*.md")) + sorted((REPO / "tests" / "fixtures").rglob("*.md"))


def forbidden_patterns() -> list[str]:
    pats = {ANY_ARTICLE_ID}
    for art in article_files():
        pats.add(re.escape(art.stem))
        meta, _ = read_article(art)
        for key in ("publisher", "company"):
            if meta.get(key):
                pats.add(re.escape(str(meta[key])))
        url = str(meta.get("url") or "")
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        if host:
            pats.add(re.escape(host))
    return sorted(pats)


def code_files(dirs: list[Path]) -> list[Path]:
    out = []
    for d in dirs:
        for here, subdirs, names in os.walk(d):
            subdirs[:] = [s for s in subdirs if s not in SKIP_PARTS]  # never walk node_modules
            out += [Path(here) / n for n in names
                    if Path(n).suffix in CODE_SUFFIXES and n not in SKIP_NAMES]
    return sorted(out)


def find_hits(dirs: list[Path], patterns: list[str]) -> list[str]:
    rx = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    hits = []
    for f in code_files(dirs):
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = rx.search(line)
            if m:
                hits.append(f"{f.relative_to(REPO).as_posix() if f.is_relative_to(REPO) else f}:{n}: {m.group(0)!r}")
    return hits


def test_names_come_from_the_articles():
    pats = forbidden_patterns()
    # At least the fixture publisher and the article ids are known.
    assert re.escape("Northwind Cycles") in pats
    assert re.escape("article-fixture") in pats


def test_no_publisher_or_article_id_in_code():
    files = code_files(CODE_DIRS)
    assert any(f.suffix == ".py" for f in files) and any(f.suffix == ".tsx" for f in files)
    hits = find_hits(CODE_DIRS, forbidden_patterns())
    assert not hits, "article-specific names in pipeline/ or render/ code:\n" + "\n".join(hits)


def test_the_check_catches_a_planted_name(tmp_path):
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline" / "x.py").write_bytes(b"NAME = 'Northwind Cycles'\n")
    (tmp_path / "pipeline" / "y.tsx").write_bytes(b"const f = 'scenes/article-07.json';\n")
    (tmp_path / "pipeline" / "z.py").write_bytes(b"OK = 'source/article-XX.md'\n")
    hits = find_hits([tmp_path / "pipeline"], forbidden_patterns())
    assert len(hits) == 2
    assert any("Northwind Cycles" in h for h in hits) and any("article-07" in h for h in hits)
