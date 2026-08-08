"""Prize parsing is the single highest-risk component: a misread prize
reorders the whole list, so the tricky real-world shapes are pinned here."""

from __future__ import annotations

import json

import pytest

from phhack.money import (
    DEFAULT_RATES_PHP,
    Money,
    format_php,
    load_rates,
    parse_prize,
    strip_markup,
)


@pytest.mark.parametrize(
    "text,expected_amount,expected_currency",
    [
        # Devpost wraps the figure in markup and prefixes the symbol.
        ("$<span data-currency-value>25,000</span>", 25_000, "USD"),
        ("&#36;10,000 in prizes", 10_000, "USD"),
        ("₱500,000", 500_000, "PHP"),
        ("PHP 1,000,000", 1_000_000, "PHP"),
        ("1,000,000 PHP", 1_000_000, "PHP"),
        ("P250,000 cash pool", 250_000, "PHP"),
        ("$1.5M", 1_500_000, "USD"),
        ("10k USD", 10_000, "USD"),
        ("€8,000", 8_000, "EUR"),
        # Indian lakh grouping, used by the INR-denominated sources.
        ("₹2,50,000", 250_000, "INR"),
        ("₹1,00,00,000", 10_000_000, "INR"),
    ],
)
def test_parses_common_prize_shapes(text, expected_amount, expected_currency):
    money = parse_prize(text)
    assert money is not None, text
    assert money.amount == pytest.approx(expected_amount)
    assert money.currency == expected_currency


def test_range_takes_the_ceiling():
    assert parse_prize("$10K - $50K").amount == pytest.approx(50_000)


def test_picks_largest_across_multiple_amounts():
    money = parse_prize("$5,000 grand prize out of $25,000 in total prizes")
    assert money.amount == pytest.approx(25_000)


def test_compares_across_currencies_by_php_value():
    # €10,000 (~₱630K) must beat $5,000 (~₱290K) even though 5000 < 10000
    # is false on the raw numbers only by coincidence of magnitude.
    money = parse_prize("$5,000 and €10,000")
    assert money.currency == "EUR"


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "Top 3 teams win swag",
        "1,500 participants expected",
        "Jan 08 - Mar 15, 2026",
        "$0",
        "Prizes to be announced",
    ],
)
def test_returns_none_rather_than_guessing(text):
    """An unparseable prize must be None, not zero.

    Zero would rank the listing below a ₱1 prize; None marks it 'unknown' and
    the ranker treats it accordingly.
    """
    assert parse_prize(text) is None


def test_multiplier_suffix_needs_a_word_boundary():
    # "25,000 kilometres" must not be read as 25 million.
    money = parse_prize("25,000 kilometres")
    assert money is not None
    assert money.amount == pytest.approx(25_000)


def test_symbol_alias_does_not_fire_mid_word():
    # The "P" -> PHP alias must not trigger on the tail of "Top".
    money = parse_prize("Top 40,000 lines", default_currency="USD")
    assert money.currency == "USD"


def test_iso_code_needs_a_word_boundary():
    money = parse_prize("25,000 USDollars", default_currency="PHP")
    assert money.currency == "PHP"


def test_default_currency_applies_to_bare_numbers():
    assert parse_prize("100,000", default_currency="PHP").currency == "PHP"
    assert parse_prize("100,000", default_currency="INR").currency == "INR"


def test_strip_markup_unescapes_entities():
    assert "$" in strip_markup("&#36;<b>10</b>")


def test_to_php_converts_and_reports_unknown_currency():
    assert Money(100, "USD").to_php() == pytest.approx(100 * DEFAULT_RATES_PHP["USD"])
    assert Money(100, "XYZ").to_php() is None


def test_load_rates_merges_over_defaults(tmp_path):
    path = tmp_path / "fx.json"
    path.write_text(json.dumps({"usd": 60.5, "bogus": "nope"}), encoding="utf-8")
    rates = load_rates(str(path))
    assert rates["USD"] == pytest.approx(60.5)
    assert rates["EUR"] == DEFAULT_RATES_PHP["EUR"]  # untouched
    assert "BOGUS" not in rates  # non-numeric override ignored


def test_format_php_scales_units():
    assert format_php(None) == "—"
    assert format_php(750) == "₱750"
    assert format_php(750_000) == "₱750K"
    assert format_php(2_500_000) == "₱2.5M"
