"""Prize-string parsing and conversion to a single comparison currency (PHP).

Prize fields in the wild are HTML fragments, entity-encoded symbols, ranges,
and shorthand like "$1.5M". Everything funnels through `parse_prize`, which is
deliberately conservative: when it cannot find a defensible number it returns
None so the listing ranks as "prize unknown" rather than "prize zero".
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Dict, Optional

#: PHP per one unit of the given currency. Rough mid-market figures — good
#: enough to rank a $50,000 hackathon above a PHP 100,000 one, which is all
#: this tool needs. Override with `--fx-file` for anything precision-sensitive.
DEFAULT_RATES_PHP: Dict[str, float] = {
    "PHP": 1.0,
    "USD": 58.0,
    "USDT": 58.0,
    "USDC": 58.0,
    "EUR": 63.0,
    "GBP": 74.0,
    "SGD": 43.0,
    "AUD": 38.0,
    "CAD": 42.0,
    "NZD": 35.0,
    "CHF": 66.0,
    "HKD": 7.4,
    "TWD": 1.8,
    "CNY": 8.1,
    "JPY": 0.39,
    "KRW": 0.042,
    "INR": 0.69,
    "MYR": 13.0,
    "THB": 1.7,
    "IDR": 0.0036,
    "VND": 0.0023,
    "AED": 15.8,
    "SAR": 15.5,
    "BRL": 10.5,
}

#: Symbols and informal prefixes mapped to ISO codes. Multi-character keys must
#: be matched before bare "$", which the alternation below handles by length.
CURRENCY_SYMBOLS: Dict[str, str] = {
    "₱": "PHP",
    "php": "PHP",
    "p": "PHP",  # "P500,000" is standard in Philippine press.
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "s$": "SGD",
    "sgd": "SGD",
    "a$": "AUD",
    "c$": "CAD",
    "hk$": "HKD",
    "nt$": "TWD",
    "nz$": "NZD",
    "rm": "MYR",
    "rp": "IDR",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "rs": "INR",
    "¥": "JPY",
    "₩": "KRW",
    "฿": "THB",
    "₫": "VND",
    "₦": "NGN",
    "د.إ": "AED",
}

_MULTIPLIERS = {"k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0}

# Longest-first so "hk$" wins over "$" and "usd" over "us$".
_SYMBOL_ALT = "|".join(
    re.escape(sym) for sym in sorted(CURRENCY_SYMBOLS, key=len, reverse=True)
)
_ISO_ALT = "|".join(sorted(DEFAULT_RATES_PHP, key=len, reverse=True))

# A symbol prefix must start a token, otherwise the "p" -> PHP alias fires on
# the tail of words like "Top". The trailing lookaheads keep "25,000 kilometres"
# from reading as 25 million and "25,000 USDollars" from reading as USD.
_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<pre>%s)?\s*"
    # Indian grouping first: "2,50,000" is one number (250k), and the western
    # pattern would otherwise match only its "50,000" tail.
    r"(?P<num>\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<mult>[kmb])(?![A-Za-z]))?"
    r"(?:\s*(?P<post>(?:%s)(?![A-Za-z])))?" % (_SYMBOL_ALT, _ISO_ALT),
    re.IGNORECASE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# Phrases that put a number in a non-prize role ("top 3 teams", "5 winners").
_NON_PRIZE_CONTEXT = re.compile(
    r"\b(team|teams|winner|winners|place|places|slot|slots|participant|"
    r"participants|hour|hours|day|days|week|weeks|member|members)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str

    def to_php(self, rates: Optional[Dict[str, float]] = None) -> Optional[float]:
        table = rates if rates is not None else DEFAULT_RATES_PHP
        rate = table.get(self.currency.upper())
        if rate is None:
            return None
        return self.amount * rate


def strip_markup(text: str) -> str:
    """Flatten an HTML fragment to plain text.

    Devpost returns prizes as `"$<span data-currency-value>25,000</span>"`, and
    other sources hand back entity-encoded symbols such as `&#36;`.
    """
    if text is None:
        return ""
    flat = _TAG_RE.sub(" ", str(text))
    flat = html.unescape(flat)
    return flat.replace("\xa0", " ").strip()


def parse_prize(text: Optional[str], default_currency: str = "USD") -> Optional[Money]:
    """Extract the headline prize from a free-text prize field.

    Takes the largest defensible amount found, which is the right call for
    ranking: strings like "$25,000 in prizes, $5,000 grand prize" or
    "PHP 100,000 - PHP 500,000" should both surface their ceiling.

    `default_currency` is used when a bare number or a bare "$" is found; each
    adapter passes the currency its platform actually denominates in.
    """
    flat = strip_markup(text)
    if not flat:
        return None

    best: Optional[Money] = None
    for match in _AMOUNT_RE.finditer(flat):
        money = _interpret(match, flat, default_currency)
        if money is None:
            continue
        # Compare in PHP so "€10,000" beats "$5,000" rather than 10000 > 5000.
        if best is None or _rank_value(money) > _rank_value(best):
            best = money
    return best


def _rank_value(money: Money) -> float:
    php = money.to_php()
    return php if php is not None else money.amount


def _interpret(match: "re.Match[str]", haystack: str, default_currency: str) -> Optional[Money]:
    raw_num = match.group("num")
    try:
        amount = float(raw_num.replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None

    pre = (match.group("pre") or "").strip().lower()
    post = (match.group("post") or "").strip().upper()
    mult = (match.group("mult") or "").lower()

    currency: Optional[str] = None
    if post in DEFAULT_RATES_PHP:
        currency = post
    elif pre:
        currency = CURRENCY_SYMBOLS.get(pre)

    has_marker = currency is not None
    if mult:
        amount *= _MULTIPLIERS[mult]

    if not has_marker:
        # No currency marker: only trust the number if it is unambiguously a
        # money-sized figure, and never if it reads as a year or a count.
        if _YEAR_RE.match(raw_num) and not mult:
            return None
        if "," not in raw_num and not mult:
            return None
        if _has_non_prize_context(haystack, match):
            return None
        currency = default_currency

    return Money(amount=amount, currency=(currency or default_currency).upper())


def _has_non_prize_context(haystack: str, match: "re.Match[str]") -> bool:
    """True when the words hugging the number make it a count, not an amount."""
    window = haystack[max(0, match.start() - 16) : match.end() + 16]
    return bool(_NON_PRIZE_CONTEXT.search(window))


def load_rates(path: Optional[str]) -> Dict[str, float]:
    """Load a `{"USD": 58.2, ...}` PHP-rate override file, merged over defaults."""
    rates = dict(DEFAULT_RATES_PHP)
    if not path:
        return rates
    with open(path, "r", encoding="utf-8") as handle:
        override = json.load(handle)
    for code, value in override.items():
        try:
            rates[str(code).upper()] = float(value)
        except (TypeError, ValueError):
            continue
    return rates


def format_php(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    if amount >= 1_000_000:
        return f"₱{amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"₱{amount / 1_000:.0f}K"
    return f"₱{amount:.0f}"
