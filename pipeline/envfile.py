"""Minimal `.env` loader (own code; python-dotenv is deliberately not used).

Format, one entry per line:
    KEY=value
    export KEY=value          # "export " prefix is allowed
    KEY="value with spaces"   # double quotes: \\n, \\t, \\" and \\\\ escapes
    KEY='literal value'       # single quotes: taken as is
    # comment lines and blank lines are ignored
    KEY=value  # an unquoted value ends at " #"

Variables already set in the environment win over the file, unless
override=True. Values are never printed or put into error messages.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


class EnvFileError(ValueError):
    """A line in the .env file cannot be parsed. Never carries the value."""


def _unescape_double(raw: str) -> str:
    out, i = [], 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw) and raw[i + 1] in _ESCAPES:
            out.append(_ESCAPES[raw[i + 1]])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _closing_quote(raw: str, quote: str) -> int:
    """Index of the closing quote; in double quotes a backslash escapes the next char."""
    i = 1
    while i < len(raw):
        if quote == '"' and raw[i] == "\\":
            i += 2
            continue
        if raw[i] == quote:
            return i
        i += 1
    return -1


def _parse_value(raw: str, lineno: int, path: str) -> str:
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        quote = raw[0]
        end = _closing_quote(raw, quote)
        if end == -1:
            raise EnvFileError(f"{path}, line {lineno}: missing closing {quote}")
        rest = raw[end + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise EnvFileError(f"{path}, line {lineno}: unexpected text after the quoted value")
        inner = raw[1:end]
        return _unescape_double(inner) if quote == '"' else inner
    # unquoted: an inline comment starts at whitespace + '#'
    m = re.search(r"\s#", raw)
    if m:
        raw = raw[: m.start()]
    return raw.strip()


def parse_env(text: str, path: str = ".env") -> dict[str, str]:
    """Parse .env text into a dict. Raises EnvFileError on a bad line."""
    values: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if "=" not in stripped:
            raise EnvFileError(f"{path}, line {lineno}: expected KEY=value")
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if not _KEY.match(key):
            raise EnvFileError(f"{path}, line {lineno}: invalid variable name")
        values[key] = _parse_value(raw, lineno, path)
    return values


def load_env(path: Path, override: bool = False) -> dict[str, str]:
    """Load `path` into os.environ. Returns the keys it set (values included).

    A missing file is not an error: in the cloud there is no .env and the
    network adds the API key instead.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    # utf-8-sig drops the BOM that Windows Notepad may write
    text = path.read_text(encoding="utf-8-sig")
    applied: dict[str, str] = {}
    for key, value in parse_env(text, str(path.name)).items():
        if override or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied
