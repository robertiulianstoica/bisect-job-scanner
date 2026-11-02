"""Workday career sites, through the JSON API behind them (no login).

<tenant>.wd<N>.myworkdayjobs.com/<site> is backed by
POST /wday/cxs/<tenant>/<site>/jobs (a page of 20 postings, with facets) and
GET /wday/cxs/<tenant>/<site><externalPath> (one posting with its text).
The board slug is "<tenant>.wd<N>/<site>", e.g. "adobe.wd5/external_experienced".

Large companies list thousands of jobs worldwide, not in date order, so a
board is narrowed to one country through the site's own facets (named
differently per company: locationCountry, locationHierarchy1, ...), and only
titles that look like engineering roles have their description read.
"""

from __future__ import annotations

import re

import requests

from jobspy.ats import DEFAULT_HEADERS, format_description, get_json, matches_search, parse_timestamp, read_boards, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Workday")

PAGE = 20
MAX_PAGES = 10
DEFAULT_COUNTRY = "Romania"
ENGINEERING = re.compile(
    r"engineer|developer|programmer|architect|full.?stack|back.?end|front.?end|software|devops|\bsre\b|tech(nical)? lead",
    re.IGNORECASE,
)
# Tenants whose Workday name is not the company's own (the rest are title-cased).
COMPANY_NAMES = {
    "db": "Deutsche Bank", "dxctechnology": "DXC Technology", "nxp": "NXP", "hp": "HP", "hpe": "HPE",
    "nvidia": "NVIDIA", "crowdstrike": "CrowdStrike", "kla": "KLA", "paypal": "PayPal", "thermofisher": "Thermo Fisher",
}


def parse_slug(slug: str) -> tuple[str, str, str] | None:
    """'adobe.wd5/external_experienced' -> (host, tenant, site)."""
    match = re.fullmatch(r"([a-z0-9-]+)\.(wd\d+)/([A-Za-z0-9_-]+)", slug.strip(), re.IGNORECASE)
    if not match:
        return None
    tenant, instance, site = match.groups()
    return f"{tenant}.{instance}.myworkdayjobs.com", tenant, site


def country_facet(facets: list, country: str) -> dict[str, list[str]]:
    """The one facet that narrows the board to a country, as appliedFacets.

    Every facet value whose name starts with the country is a candidate
    ("Romania", "Romania, Remote"); the facet whose matches cover the most
    jobs wins, so two facets are never combined (they would intersect).
    """
    best: tuple[int, str, list[str]] | None = None

    def walk(items):
        nonlocal best
        for facet in items or []:
            values = facet.get("values") or []
            if values and "facetParameter" in values[0]:
                walk(values)
                continue
            hits = [v for v in values if (v.get("descriptor") or "").lower().startswith(country.lower())]
            if hits:
                total = sum(v.get("count") or 0 for v in hits)
                if best is None or total > best[0]:
                    best = (total, facet["facetParameter"], [v["id"] for v in hits])

    walk(facets)
    return {best[1]: best[2]} if best else {}


def post_json(url: str, body: dict, timeout: int = 30):
    try:
        response = requests.post(url, json=body, headers={**DEFAULT_HEADERS, "Content-Type": "application/json"}, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


class Workday(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.WORKDAY, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        slugs = (scraper_input.company_boards or {}).get("workday", [])
        country = scraper_input.location or DEFAULT_COUNTRY

        def read(slug):
            parsed = parse_slug(slug)
            if not parsed:
                log.debug(f"board {slug}: not a Workday slug")
                return []
            host, tenant, site = parsed
            api = f"https://{host}/wday/cxs/{tenant}/{site}"
            first = post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
            if not first:
                log.debug(f"board {slug} not found or unreadable")
                return []
            facets = country_facet(first.get("facets") or [], country)
            if not facets:
                return []  # no jobs in that country
            posts = []
            for page in range(MAX_PAGES):
                data = post_json(f"{api}/jobs", {"appliedFacets": facets, "limit": PAGE, "offset": page * PAGE, "searchText": ""})
                listed = (data or {}).get("jobPostings") or []
                for item in listed:
                    if ENGINEERING.search(item.get("title") or ""):
                        post = self._to_post(api, tenant, item, scraper_input)
                        if post:
                            posts.append(post)
                if len(listed) < PAGE:
                    break
            return posts

        return JobResponse(jobs=read_boards(slugs, read))

    def _to_post(self, api: str, tenant: str, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        detail = get_json(f"{api}{item.get('externalPath')}")
        info = (detail or {}).get("jobPostingInfo")
        if not info:
            return None
        posted = parse_timestamp(info.get("startDate"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        title = info.get("title") or item.get("title") or ""
        description = format_description(info.get("jobDescription"), scraper_input)
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = [info.get("location")] + list(info.get("additionalLocations") or [])
        places = list(dict.fromkeys(p for p in places if p))
        remote = info.get("remoteType") or ""
        label = ", ".join(places) + (f" ({remote})" if remote else "")
        req = info.get("jobReqId") or (item.get("bulletFields") or [None])[0] or item.get("externalPath")
        return JobPost(
            id=f"workday-{tenant}-{req}",
            source_board=f"workday:{api.split('//')[1].split('.myworkdayjobs')[0]}/{api.rsplit('/', 1)[1]}",
            title=title,
            company_name=COMPANY_NAMES.get(tenant.lower(), tenant.title()),
            job_url=info.get("externalUrl"),
            location=Location(city=label) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote="remote" in (remote + label).lower(),
            listing_type=info.get("timeType"),
            location_restrictions=places or None,
        )
