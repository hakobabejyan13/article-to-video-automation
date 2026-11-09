"""Find the numbers a piece of text states (PLAN.md section 4, checks 3 and 4).

- Cardinals: digits (`$3,000`, `8.9%`, `68,631`, `48/50`, `2.6x`, years) and number
  words (`nine`, `twenty`, `twenty-one`, `one hundred`). Thousands separators and
  units are removed; values are compared exactly, so 8.9 never matches 9.
  `1 million` and `1,000,000` are the same value.
- Ordinals, kept apart: `first`, `1st`, `#1`, `No. 1`, `ranked 1`, `number one`.
  An ordinal is never counted as a cardinal, so "ranked first" cannot be supported
  by a plain "1".
- `(1)`-style list markers inside a sentence are ordinals of that sentence.
- Money: an amount written with a currency (`$3,000`, `GBP 1,500`) also yields a
  (currency, value) pair, so "$1,500" cannot be supported by "GBP 1,500".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pipeline.textnorm import normalize

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000,
          "trillion": 1_000_000_000_000}
ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
    "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "hundredth": 100,
}
CURRENCY_CODES = {"USD", "GBP", "EUR", "CAD", "AUD", "JPY", "INR", "CHF", "NZD", "SEK"}
CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"
# "1 million", "1.5 billion"; short forms only when attached: "$5M", "10k", "2bn".
_SCALE_SUFFIX = r"(?:\s?(?P<scale>million|billion|trillion|thousand)\b|(?P<short>bn|[mMkK])\b)?"

# Ordinals written with digits.
_DIGIT_ORDINAL_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b", re.I)
_HASH_ORDINAL_RE = re.compile(r"(?<![\w&])#\s?(\d+)\b")
# "No. 1" needs the period: "No 12-month commitment" is not an ordinal.
_NO_ORDINAL_RE = re.compile(r"\b(?:No\.|Nr\.|[Nn]umber)\s?(\d+)\b")
_RANKED_RE = re.compile(
    r"\b(?:ranked|rank|placed|place|positioned|position)\s+(?:at\s+|as\s+)?(?:No\.\s?|number\s+|#\s?)?(\d+)\b",
    re.I,
)
# "(1) Acme, (2) ..." list markers inside a sentence; one or two digits only.
_PAREN_MARKER_RE = re.compile(r"(?<![\w$£€])\((\d{1,2})\)(?=\s)")
_NUMBER_ORDINAL_WORD_RE = re.compile(r"\bnumber\s+(" + "|".join(UNITS) + r")\b", re.I)

_MONEY_RE = re.compile(
    r"(?P<cur>[$£€¥₹]|\b(?:" + "|".join(CURRENCY_CODES) + r")\b)\s?(?P<num>" + _NUM + r")" + _SCALE_SUFFIX,
    re.I,
)
_CARDINAL_RE = re.compile(r"(?<![\w.])(?P<num>" + _NUM + r")(?![\d])" + _SCALE_SUFFIX)
_WORD_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")


def canon(value: Decimal) -> str:
    """Canonical text for a number: no separators, no trailing zeros."""
    q = value.normalize()
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scale_of(m: re.Match) -> str | None:
    return m.group("scale") or m.group("short")


def _to_decimal(num: str, scale: str | None = None) -> Decimal | None:
    try:
        value = Decimal(num.replace(",", ""))
    except InvalidOperation:
        return None
    if scale:
        s = scale.lower()
        value *= {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000,
                  "bn": 1_000_000_000, "billion": 1_000_000_000,
                  "trillion": 1_000_000_000_000}[s]
    return value


@dataclass
class Numbers:
    cardinals: set[str] = field(default_factory=set)
    ordinals: set[str] = field(default_factory=set)
    money: set[tuple[str, str]] = field(default_factory=set)

    def __or__(self, other: "Numbers") -> "Numbers":
        return Numbers(self.cardinals | other.cardinals, self.ordinals | other.ordinals,
                       self.money | other.money)

    def is_empty(self) -> bool:
        return not (self.cardinals or self.ordinals)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace spans with spaces so later patterns do not see them again."""
    chars = list(text)
    for a, b in spans:
        for k in range(a, b):
            chars[k] = " "
    return "".join(chars)


def _word_numbers(text: str) -> tuple[set[str], set[str]]:
    """Cardinal and ordinal values written as words ("twenty-one", "one hundred", "third")."""
    cardinals: set[str] = set()
    ordinals: set[str] = set()
    words: list[str] = []
    for m in _WORD_RE.finditer(text):
        words.extend(m.group(0).lower().split("-"))

    i = 0
    while i < len(words):
        w = words[i]
        if w in ORDINAL_WORDS:
            ordinals.add(str(ORDINAL_WORDS[w]))
            i += 1
            continue
        if w not in UNITS and w not in TENS:
            i += 1
            continue
        total, current, is_ordinal = 0, 0, False
        prev = None  # kind of the previous word: unit | tens | scale
        j = i
        while j < len(words):
            x = words[j]
            if x in UNITS and prev in (None, "tens", "scale"):
                current += UNITS[x]
                prev = "unit"
            elif x in TENS and prev in (None, "scale"):
                current += TENS[x]
                prev = "tens"
            elif x in SCALES and prev is not None:
                current = max(current, 1) * SCALES[x]
                if SCALES[x] >= 1000:
                    total, current = total + current, 0
                prev = "scale"
            elif x == "and" and prev == "scale" and j + 1 < len(words) and (
                words[j + 1] in UNITS or words[j + 1] in TENS
            ):
                pass  # "one hundred and five"
            elif x in ORDINAL_WORDS and prev in ("tens", "scale") and ORDINAL_WORDS[x] < 10:
                current += ORDINAL_WORDS[x]  # "twenty-first"
                is_ordinal = True
                j += 1
                break
            else:
                break
            j += 1
        (ordinals if is_ordinal else cardinals).add(str(total + current))
        i = j
    return cardinals, ordinals


def extract(text: str) -> Numbers:
    """All numbers that `text` states, after normalisation."""
    s = normalize(text)
    out = Numbers()
    spans: list[tuple[int, int]] = []

    for rx in (_DIGIT_ORDINAL_RE, _HASH_ORDINAL_RE, _NO_ORDINAL_RE, _RANKED_RE, _PAREN_MARKER_RE):
        for m in rx.finditer(s):
            out.ordinals.add(canon(Decimal(m.group(1))))
            spans.append(m.span(1) if rx is _RANKED_RE else m.span())
    for m in _NUMBER_ORDINAL_WORD_RE.finditer(s):
        out.ordinals.add(str(UNITS[m.group(1).lower()]))
        spans.append(m.span())
    s = _blank(s, spans)

    for m in _MONEY_RE.finditer(s):
        value = _to_decimal(m.group("num"), _scale_of(m))
        if value is not None:
            cur = m.group("cur")
            code = CURRENCY_SYMBOLS.get(cur, cur.upper())
            out.money.add((code, canon(value)))

    digit_spans = []
    for m in _CARDINAL_RE.finditer(s):
        value = _to_decimal(m.group("num"), _scale_of(m))
        if value is not None:
            out.cardinals.add(canon(value))
            digit_spans.append(m.span())
    word_cards, word_ords = _word_numbers(_blank(s, digit_spans))
    out.cardinals |= word_cards
    out.ordinals |= word_ords
    return out


def extract_marker(marker: str | None) -> set[str]:
    """Ordinal from an ordered-list marker like '3.' or '3)'."""
    if not marker:
        return set()
    m = re.match(r"(\d+)", marker)
    return {canon(Decimal(m.group(1)))} if m else set()


def has_number(text: str) -> bool:
    n = extract(text)
    return bool(n.cardinals or n.ordinals)
