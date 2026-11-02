"""Pay ranges written in an advert's text, kept as written.

Most European adverts give pay only in the text ("€60k–€80k", "PLN 18K -
PLN 22K", "USD 8,200-9,700/month", "60.000 - 75.000 EUR brutto"), so the
structured salary fields are nearly always empty. parse_salary finds the
first range and returns it in the advert's own currency and period; the
period is None when the advert does not say. Converting to yearly EUR
(yearly_eur) is for reports and views, not for storage.
"""

from __future__ import annotations

import re

# Approximate EUR value of one unit (2026-10). Good enough for comparing ranges.
TO_EUR = {
    "EUR": 1.0, "USD": 0.92, "GBP": 1.17, "CHF": 1.05, "PLN": 0.23, "RON": 0.20, "CZK": 0.040,
    "HUF": 0.0025, "SEK": 0.087, "NOK": 0.086, "DKK": 0.134, "CAD": 0.67, "AUD": 0.60,
}
SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "zł": "PLN", "lei": "RON", "kr": "SEK"}
CURRENCY = r"(?P<{name}>EUR|USD|GBP|CHF|PLN|RON|CZK|HUF|SEK|NOK|DKK|CAD|AUD|€|\$|£|zł|lei)"
NUMBER = r"(?P<{name}>\d{{1,3}}(?:[.,\s]\d{{3}})*(?:[.,]\d+)?)\s*(?P<{name}k>[kK])?"
RANGE = re.compile(
    CURRENCY.format(name="c1") + r"?\s*" + NUMBER.format(name="lo")
    + r"\s*(?:-|–|—|to|bis|a|à)\s*"
    + CURRENCY.format(name="c2") + r"?\s*" + NUMBER.format(name="hi")
    + r"\s*" + CURRENCY.format(name="c3") + r"?"
    + r"(?P<period>\s*(?:/|per|a|an|pro)?\s*(?:year|yr|annum|annual|month|mo|monat|monthly|hour|hr|h|jahr)\b)?",
    re.IGNORECASE,
)


def _number(text: str, k: str | None) -> float:
    digits = re.sub(r"[.,\s](?=\d{3}\b)", "", text).replace(",", ".")
    value = float(digits)
    return value * 1000 if k else value


def parse_salary(text: str | None) -> tuple[float, float, str, str | None] | None:
    """(min, max, currency, period) as written, or None. Period: year, month,
    hour, or None when the advert does not state it."""
    for match in RANGE.finditer(text or ""):
        code = next((match.group(g) for g in ("c1", "c2", "c3") if match.group(g)), None)
        if not code:
            continue  # a bare number range ("3-5 years") is not pay
        code = SYMBOLS.get(code, code).upper()
        try:
            low, high = _number(match["lo"], match["lok"] or match["hik"]), _number(match["hi"], match["hik"])
        except ValueError:
            continue
        if low > high:
            continue
        period_text = (match["period"] or "").lower()
        if re.search(r"hour|hr|\bh\b", period_text):
            period = "hour"
        elif re.search(r"month|mo\b|monat", period_text):
            period = "month"
        elif period_text:
            period = "year"
        else:
            period = None
        return low, high, code, period
    return None


def yearly_eur(low: float, high: float, currency: str, period: str | None) -> tuple[float, float] | None:
    """For reports: a range as yearly EUR, with fixed approximate rates. An
    unstated period is judged by size (under 300 EUR an hour, under 25k a month)."""
    rate = TO_EUR.get(currency)
    if rate is None:
        return None
    if period is None:
        eur = high * rate
        period = "hour" if eur < 300 else "month" if eur < 25_000 else "year"
    factor = {"year": 1, "month": 12, "hour": 1760}[period]
    low, high = low * rate * factor, high * rate * factor
    if not 12_000 <= high <= 500_000:
        return None  # not a salary range (prices, funding, headcounts)
    return low, high
