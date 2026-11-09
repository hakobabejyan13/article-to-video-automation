"""Text normalisation shared by the splitter, the checker and the fact sheet.

PLAN.md section 4: curly quotes and apostrophes to straight, non-breaking spaces to
spaces, whitespace runs to one space, Markdown markup removed, front matter removed
(the caller passes the body only).
"""

from __future__ import annotations

import re

_CHAR_MAP = {
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "„": '"',  # low double quote
    "″": '"',  # double prime
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "‚": "'",  # low single quote
    "′": "'",  # prime
    " ": " ",  # non-breaking space
    " ": " ",  # narrow non-breaking space
    " ": " ",  # figure space
    " ": " ",  # thin space
    "​": "",  # zero-width space
    "﻿": "",  # byte order mark
}
_CHAR_RE = re.compile("|".join(map(re.escape, _CHAR_MAP)))

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_CODE_RE = re.compile(r"`+([^`]*)`+")
_STAR_RE = re.compile(r"(\*\*\*|\*\*|\*|~~)(?=\S)(.+?)(?<=\S)\1")
# Underscores inside a word (snake_case) are not emphasis in Markdown.
_UNDERSCORE_RE = re.compile(r"(?<![\w])(___|__|_)(?=\S)(.+?)(?<=\S)\1(?![\w])")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~\"'])")
_SPACE_RE = re.compile(r"\s+")


def fix_chars(text: str) -> str:
    """Curly quotes to straight, odd spaces to plain spaces."""
    return _CHAR_RE.sub(lambda m: _CHAR_MAP[m.group(0)], text)


def strip_inline_markdown(text: str) -> str:
    """Remove inline Markdown (links, images, emphasis, code, HTML tags), keep the words."""
    s = _HTML_COMMENT_RE.sub("", text)
    s = _IMAGE_RE.sub("", s)
    s = _LINK_RE.sub(r"\1", s)
    s = _REF_LINK_RE.sub(r"\1", s)
    s = _AUTOLINK_RE.sub(r"\1", s)
    s = _HTML_TAG_RE.sub("", s)
    s = _CODE_RE.sub(r"\1", s)
    # Emphasis can nest (***x*** or **_x_**); a few passes remove every level.
    for _ in range(3):
        new = _UNDERSCORE_RE.sub(r"\2", _STAR_RE.sub(r"\2", s))
        if new == s:
            break
        s = new
    # Bold that opens on one line and closes on the next leaves a lone marker.
    s = s.replace("**", "").replace("__", "")
    s = _ESCAPE_RE.sub(r"\1", s)
    return s


def collapse_spaces(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


def normalize(text: str) -> str:
    """Full normalisation for one piece of inline text."""
    return collapse_spaces(strip_inline_markdown(fix_chars(text)))


def fold(text: str) -> str:
    """Normalised and lower-cased, for case-insensitive comparisons."""
    return normalize(text).lower()
