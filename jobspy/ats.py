"""Helpers shared by the scrapers that read public job-board APIs
(Greenhouse, Ashby, Lever, Himalayas) rather than search pages.

These APIs return every open job for a company or a query, so the search
term and the age limit are applied here instead of by the site.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

from concurrent.futures import ThreadPoolExecutor

import requests

from jobspy.model import DescriptionFormat, ScraperInput
from jobspy.util import markdown_converter, plain_converter

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
}


def _parse_terms(search_term: str | None) -> list[tuple[str, bool]]:
    """(term, title_only) pairs; a term written title:"..." counts only in the title."""
    if not search_term:
        return []
    terms = []
    for part in re.split(r"\s+OR\s+", search_term, flags=re.IGNORECASE):
        part = part.strip()
        title_only = part.lower().startswith("title:")
        term = part[6:].strip() if title_only else part
        term = term.strip('"').strip()
        if term:
            terms.append((term, title_only))
    return terms


def search_terms(search_term: str | None, titles: bool = True) -> list[str]:
    """Split a LinkedIn-style query ('"PHP" OR "Symfony"') into plain terms.

    titles=False leaves out the title-only terms, for sites whose query is a
    fixed technology keyword rather than free text.
    """
    return [term for term, title_only in _parse_terms(search_term) if titles or not title_only]


def _has_term(term: str, text: str) -> bool:
    return re.search(rf"(?<![\w.+#-]){re.escape(term)}(?![\w+#-])", text, re.IGNORECASE) is not None


def matches_search(search_term: str | None, *texts: str | None) -> bool:
    """True when any term appears as a whole word in any of the texts.

    The first text is the title: title-only terms are looked for there alone.
    """
    terms = _parse_terms(search_term)
    if not terms:
        return True
    title = texts[0] if texts and texts[0] else ""
    haystack = " ".join(t for t in texts if t)
    return any(_has_term(term, title if title_only else haystack) for term, title_only in terms)


def parse_timestamp(value) -> datetime | None:
    """ISO strings and unix seconds or milliseconds, as an aware datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(value).strip()
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def within_hours(posted: datetime | None, hours_old: int | None) -> bool:
    if not hours_old or posted is None:
        return True
    return posted >= datetime.now(timezone.utc) - timedelta(hours=hours_old)


def format_description(raw_html: str | None, scraper_input: ScraperInput) -> str | None:
    """Job-board HTML (sometimes entity-escaped) in the requested format."""
    if not raw_html:
        return None
    text = html.unescape(raw_html) if "&lt;" in raw_html else raw_html
    if scraper_input.description_format == DescriptionFormat.HTML:
        return text
    if scraper_input.description_format == DescriptionFormat.PLAIN:
        return plain_converter(text)
    return markdown_converter(text)


def get_json(url: str, timeout: int = 30, params: dict | None = None):
    """GET a JSON document; None when the board does not exist or fails."""
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, params=params, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def read_boards(slugs: list[str], read_one, workers: int = 8) -> list:
    """Read many company boards in parallel; read_one(slug) returns a list of posts."""
    if not slugs:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(slugs))) as pool:
        results = pool.map(read_one, slugs)
    return [post for posts in results for post in posts]
