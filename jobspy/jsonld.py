"""schema.org JobPosting data, which many job pages embed as JSON-LD."""

from __future__ import annotations

import html
import json
import re

import requests

from jobspy.ats import DEFAULT_HEADERS

PAGE_HEADERS = {**DEFAULT_HEADERS, "Accept": "text/html,application/xhtml+xml"}


def fetch_page(url: str, timeout: int = 30) -> str | None:
    try:
        response = requests.get(url, headers=PAGE_HEADERS, timeout=timeout)
    except requests.RequestException:
        return None
    return response.text if response.status_code == 200 else None


def json_ld(page: str) -> list[dict]:
    """Every JSON-LD object on the page, @graph flattened."""
    found = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
            if isinstance(item, dict):
                found.append(item)
    return found


def job_posting(page: str | None) -> dict | None:
    """The page's JobPosting, flattened into the fields a JobPost needs."""
    if not page:
        return None
    posting = next((i for i in json_ld(page) if i.get("@type") == "JobPosting"), None)
    if not posting:
        return None
    org = posting.get("hiringOrganization") or {}
    places = []
    for place in _as_list(posting.get("jobLocation")):
        address = (place or {}).get("address") or {}
        if isinstance(address, dict):
            bits = [_country(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")]
            places.append(", ".join(b for b in bits if b))
    allowed = []
    for area in _as_list(posting.get("applicantLocationRequirements")):
        if isinstance(area, dict):
            address = area.get("address") or {}
            name = area.get("name") or _country(address.get("addressCountry")) or address.get("addressRegion")
            if name:
                allowed.append(str(name))
    remote = "TELECOMMUTE" in str(posting.get("jobLocationType") or "").upper()
    return {
        "title": html.unescape(posting.get("title") or ""),
        "company": org.get("name") if isinstance(org, dict) else str(org),
        "posted": posting.get("datePosted"),
        "description": posting.get("description"),
        "places": [p for p in places if p],
        "allowed": [a for a in allowed if a],
        "remote": remote,
        "employment": posting.get("employmentType"),
    }


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def _country(value) -> str | None:
    if isinstance(value, list):
        return ", ".join(filter(None, (_country(v) for v in value))) or None
    if isinstance(value, dict):
        return value.get("name")
    return str(value) if value else None
