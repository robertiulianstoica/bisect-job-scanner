"""Lever job boards, through the public postings API (no login).

api.lever.co/v0/postings/<company>?mode=json, or api.eu.lever.co for
companies hosted in the EU; both are tried. The company is the slug in
jobs.lever.co/<company>.
"""

from __future__ import annotations

from jobspy.ats import read_boards, format_description, get_json, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Lever")

APIS = (
    "https://api.lever.co/v0/postings/{company}?mode=json",
    "https://api.eu.lever.co/v0/postings/{company}?mode=json",
)


class Lever(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.LEVER, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        companies = (scraper_input.company_boards or {}).get("lever", [])
        def read(company):
            data = None
            for api in APIS:
                data = get_json(api.format(company=company))
                if isinstance(data, list) and data:
                    break
            if not isinstance(data, list):
                log.debug(f"board {company} not found or unreadable")
                return []
            return [p for p in (self._to_post(company, i, scraper_input) for i in data) if p]

        return JobResponse(jobs=read_boards(companies, read))

    def _to_post(self, company: str, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        posted = parse_timestamp(item.get("createdAt"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        body = (item.get("description") or "") + "".join(
            f"<h3>{block.get('text', '')}</h3>{block.get('content', '')}"
            for block in item.get("lists") or []
        ) + (item.get("additional") or "")
        description = format_description(body, scraper_input)
        title = item.get("text") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        categories = item.get("categories") or {}
        places = categories.get("allLocations") or (
            [categories["location"]] if categories.get("location") else []
        )
        workplace = item.get("workplaceType")
        label = ", ".join(places) + (f" ({workplace})" if workplace else "")
        return JobPost(
            id=f"lever-{item.get('id')}",
            source_board=f"lever:{company}",
            title=title,
            company_name=company,
            job_url=item.get("hostedUrl"),
            job_url_direct=item.get("applyUrl"),
            location=Location(city=label) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=workplace == "remote" or "remote" in label.lower(),
            listing_type=categories.get("commitment"),
            location_restrictions=places or None,
        )
