"""No Fluff Jobs (nofluffjobs.com), the Polish / Central European tech board
where every advert states a salary and B2B contracts are the norm.

Search is the JSON API behind the site (POST /api/search/posting).
"""

from __future__ import annotations

import requests

from jobspy.ats import DEFAULT_HEADERS, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.model import Compensation, CompensationInterval, JobPost, JobResponse, Location, Scraper, ScraperInput, Site

API = "https://nofluffjobs.com/api/search/posting"
JOB = "https://nofluffjobs.com/job/{url}"


class NoFluffJobs(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.NOFLUFFJOBS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        seen: dict[str, JobPost] = {}
        params = {"page": 1, "pageSize": 100, "salaryCurrency": "EUR", "salaryPeriod": "month", "region": "pl", "language": "en-GB"}
        for term in search_terms(scraper_input.search_term) or [""]:
            query = f"{term} remote" if scraper_input.is_remote else term
            try:
                response = requests.post(API, params=params, json={"rawSearch": query},
                                         headers={**DEFAULT_HEADERS, "Content-Type": "application/json"}, timeout=30)
                postings = response.json().get("postings", []) if response.status_code == 200 else []
            except (requests.RequestException, ValueError):
                postings = []
            for item in postings:
                post = self._to_post(item, scraper_input)
                if post:
                    seen.setdefault(post.id, post)
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])

    def _to_post(self, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        posted = parse_timestamp(item.get("posted"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        title = item.get("title") or ""
        tiles = " ".join(t.get("value", "") for t in (item.get("tiles") or {}).get("values", []))
        if not matches_search(scraper_input.search_term, title, item.get("technology"), tiles):
            return None
        places = item.get("location", {}).get("places", [])
        remote = item.get("fullyRemote") or any(p.get("city") == "Remote" for p in places)
        countries = sorted({(p.get("country") or {}).get("name") for p in places if p.get("country")})
        cities = [p.get("city") for p in places if p.get("city") and p.get("city") != "Remote"][:3]
        label = ", ".join(cities + countries) + (" (remote)" if remote else "")
        salary = item.get("salary") or {}
        compensation = None
        if salary.get("from"):
            compensation = Compensation(
                interval=CompensationInterval.MONTHLY if (salary.get("period") or "").lower() == "month" else CompensationInterval.YEARLY,
                min_amount=salary.get("from"), max_amount=salary.get("to"), currency=salary.get("currency") or "EUR",
            )
        return JobPost(
            id=f"nofluff-{item.get('id')}",
            title=title,
            company_name=item.get("name"),
            job_url=JOB.format(url=item.get("url")),
            location=Location(city=label) if label else None,
            description=f"{title}. {item.get('technology') or ''}. {tiles}. Contract: {salary.get('type') or '?'}",
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=bool(remote),
            listing_type=salary.get("type"),
            job_level=", ".join(item.get("seniority") or []) or None,
            compensation=compensation,
            location_restrictions=countries or None,
        )
