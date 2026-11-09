"""Number finder used by the checker (T2)."""

import pytest

from pipeline.numbers import extract, has_number


@pytest.mark.parametrize(
    "text, cardinals, ordinals",
    [
        ("starts at $3,000 a month", {"3000"}, set()),
        ("8.9% of what AI cited", {"8.9"}, set()),
        ("across 68,631 AI answers", {"68631"}, set()),
        ("Total: 48/50.", {"48", "50"}, set()),
        ("a 2.6x increase", {"2.6"}, set()),
        ("in September 2026", {"2026"}, set()),
        ("a 12-month campaign", {"12"}, set()),
        ("GBP 1,500 a month", {"1500"}, set()),
        ("nine companies and twenty prompts", {"9", "20"}, set()),
        ("Twenty-one of them", {"21"}, set()),
        ("one hundred and five", {"105"}, set()),
        ("under $1 million", {"1000000"}, set()),
        ("$5M budget and 10k users", {"5000000", "10000"}, set()),
        ("ranked first", set(), {"1"}),
        ("the 3rd and the 12th", set(), {"3", "12"}),
        ("ranked #1 on the list", set(), {"1"}),
        ("No. 3 overall", set(), {"3"}),
        ("ranked 2 overall", set(), {"2"}),
        ("(1) Acme, (2) Beta", set(), {"1", "2"}),
        ("the twenty-first shop", set(), {"21"}),
        ("No 12-month commitment", {"12"}, set()),
        ("(2026) report", {"2026"}, set()),
        ("B2B and Q1 plans", set(), set()),
        ("no numbers here", set(), set()),
    ],
)
def test_extract(text, cardinals, ordinals):
    n = extract(text)
    assert n.cardinals == cardinals
    assert n.ordinals == ordinals


def test_no_rounding():
    assert extract("8.9%").cardinals != extract("9%").cardinals
    assert extract("3.0").cardinals == extract("3").cardinals == {"3"}


def test_money_keeps_the_currency():
    assert extract("$1,500 and GBP 2,000 and EUR 30 and £5").money == {
        ("USD", "1500"), ("GBP", "2000"), ("EUR", "30"), ("GBP", "5"),
    }


def test_has_number():
    assert has_number("Top 5 picks")
    assert has_number("the first pick")
    assert not has_number("Read the full guide")
