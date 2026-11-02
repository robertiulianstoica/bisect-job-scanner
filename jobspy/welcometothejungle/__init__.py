"""Welcome to the Jungle, through the public Algolia index behind its search.

The search page no longer lists results, but the index is public: the key
below is the client search key the site ships in window.env. `remote_only`
keeps fully remote roles; `hours_old` filters on the publication time.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from jobspy.ats import matches_search, search_terms
from jobspy.model import Compensation, CompensationInterval, JobPost, JobResponse, Location, Scraper, ScraperInput, Site

APP_ID = "CSEKHVMS53"
SEARCH_KEY = "4bd8f6215d0cc52b26430765769e65a0"
INDEX = "wttj_jobs_production_en"
URL = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX}/query"
HEADERS = {
    "X-Algolia-Application-Id": APP_ID,
    "X-Algolia-API-Key": SEARCH_KEY,
    "Content-Type": "application/json",
    "Referer": "https://www.welcometothejungle.com/",
    "Origin": "https://www.welcometothejungle.com",
}


class WelcomeToTheJungle(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.WELCOME_TO_THE_JUNGLE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        filters = "remote:fulltime" if scraper_input.is_remote else ""
        numeric = []
        if scraper_input.hours_old:
            numeric.append(f"published_at_timestamp>{int(time.time()) - scraper_input.hours_old * 3600}")
        seen: dict[str, JobPost] = {}
        for term in search_terms(scraper_input.search_term) or [""]:
            body = {"query": term, "hitsPerPage": 200, "filters": filters, "numericFilters": numeric}
            try:
                response = requests.post(URL, headers=HEADERS, json=body, timeout=30)
                hits = response.json().get("hits", []) if response.status_code == 200 else []
            except (requests.RequestException, ValueError):
                hits = []
            for hit in hits:
                post = self._to_post(hit, scraper_input)
                if post and post.id not in seen:
                    seen[post.id] = post
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])

    def _to_post(self, hit: dict, scraper_input: ScraperInput) -> JobPost | None:
        title = hit.get("name") or ""
        description = hit.get("summary") or ""
        if not matches_search(scraper_input.search_term, title, description, " ".join(hit.get("key_missions") or [])):
            return None
        org = hit.get("organization") or {}
        countries = sorted({o.get("country") or o.get("country_code") for o in hit.get("offices") or [] if o})
        cities = [o.get("city") for o in hit.get("offices") or [] if o and o.get("city")]
        compensation = None
        if hit.get("salary_minimum") or hit.get("salary_maximum"):
            period = (hit.get("salary_period") or "yearly").lower()
            compensation = Compensation(
                interval=CompensationInterval.MONTHLY if period.startswith("month") else CompensationInterval.YEARLY,
                min_amount=hit.get("salary_minimum"),
                max_amount=hit.get("salary_maximum"),
                currency=hit.get("salary_currency") or "EUR",
            )
        published = hit.get("published_at_timestamp")
        return JobPost(
            id=f"wttj-{hit.get('objectID')}",
            title=title,
            company_name=org.get("name"),
            job_url=f"https://www.welcometothejungle.com/en/companies/{org.get('slug')}/jobs/{hit.get('slug')}",
            location=Location(city=", ".join(cities + countries) + " (fully remote)"),
            description=description,
            date_posted=time.strftime("%Y-%m-%d", time.gmtime(published)) if published else None,
            posted_at=datetime.fromtimestamp(published, tz=timezone.utc) if published else None,
            is_remote=hit.get("remote") == "fulltime",
            listing_type=hit.get("contract_type"),
            compensation=compensation,
            location_restrictions=[c for c in countries if c] or None,
        )
