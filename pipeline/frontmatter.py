"""Front matter of an article file (PLAN.md section 3).

    ---
    publisher: <name as written in the article>
    promotional: true
    url: <optional>
    ---
    <article markdown, unchanged>

The article body is everything after the closing `---` line, byte for byte.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REQUIRED_KEYS = ("publisher", "promotional")


class FrontMatterError(ValueError):
    pass


def split_bytes(data: bytes) -> tuple[bytes | None, bytes]:
    """Return (front matter block without the fences, body). Body is exact bytes."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    first_nl = data.find(b"\n")
    if first_nl == -1 or data[:first_nl].rstrip(b"\r") != b"---":
        return None, data
    pos = first_nl + 1
    while True:
        nl = data.find(b"\n", pos)
        line_end = len(data) if nl == -1 else nl
        if data[pos:line_end].rstrip(b"\r") == b"---":
            body_start = len(data) if nl == -1 else nl + 1
            return data[first_nl + 1 : pos], data[body_start:]
        if nl == -1:
            raise FrontMatterError("front matter starts with '---' but has no closing '---' line")
        pos = nl + 1


def body_sha256(path: Path) -> str:
    _, body = split_bytes(Path(path).read_bytes())
    return hashlib.sha256(body).hexdigest()


def read_article(path: Path) -> tuple[dict, str]:
    """Return (front matter dict, body text). Raises FrontMatterError if invalid."""
    import yaml  # PyYAML; imported here so `doctor` works without it

    block, body = split_bytes(Path(path).read_bytes())
    if block is None:
        raise FrontMatterError(
            "no front matter. Add a block at the top of the file:\n"
            "---\npublisher: <name as written in the article>\npromotional: true\n---"
        )
    try:
        meta = yaml.safe_load(block.decode("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise FrontMatterError(f"front matter is not valid YAML: {exc}") from None
    if not isinstance(meta, dict):
        raise FrontMatterError("front matter must be a set of 'key: value' lines")
    missing = [k for k in REQUIRED_KEYS if meta.get(k) in (None, "")]
    if missing:
        raise FrontMatterError(
            "front matter is missing " + ", ".join(missing)
            + ". A person sets these, never the LLM."
        )
    if not isinstance(meta["promotional"], bool):
        raise FrontMatterError("front matter 'promotional' must be true or false")
    meta["publisher"] = str(meta["publisher"]).strip()
    return meta, body.decode("utf-8")
