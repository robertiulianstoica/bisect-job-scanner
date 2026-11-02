"""Himalayas, the remote-only job board, through its public search API.

himalayas.app/jobs/api/search?q=<term>&country=<name>&sort=recent&page=<n>
returns 20 jobs a page. `country` keeps jobs open to that country (worldwide
ones included); pass it through ScraperInput.location, e.g. "Romania".
"""

from __future__ import annotations

from jobspy.ats import format_description, get_json, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.model import Compensation, CompensationInterval, JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Himalayas")

API = "https://himalayas.app/jobs/api/search"
PAGE_SIZE = 20
MAX_PAGES = 10


class Himalayas(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.HIMALAYAS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        seen: dict[str, JobPost] = {}
        for term in search_terms(scraper_input.search_term) or [""]:
            for page in range(1, MAX_PAGES + 1):
                params = {"q": term, "sort": "recent", "page": page}
                if scraper_input.location:
                    params["country"] = scraper_input.location
                data = get_json(API, params=params)
                if not data or not data.get("jobs"):
                    break
                fresh_on_page = False
                for item in data["jobs"]:
                    posted = parse_timestamp(item.get("pubDate"))
                    if not within_hours(posted, scraper_input.hours_old):
                        continue
                    fresh_on_page = True
                    post = self._to_post(item, posted, scraper_input)
                    if post and post.id not in seen:
                        seen[post.id] = post
                if not fresh_on_page or len(seen) >= scraper_input.results_wanted:
                    break
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])

    def _to_post(self, item: dict, posted, scraper_input: ScraperInput) -> JobPost | None:
        description = format_description(item.get("description"), scraper_input)
        title = item.get("title") or ""
        # Himalayas search is loose ("php" also matches peso salaries), so
        # require the term as a word in the text itself.
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = item.get("locationRestrictions") or []
        compensation = None
        if item.get("minSalary") or item.get("maxSalary"):
            period = (item.get("salaryPeriod") or "annual").lower()
            compensation = Compensation(
                interval=CompensationInterval.YEARLY if period.startswith("ann") else CompensationInterval.MONTHLY
                if period.startswith("month") else None,
                min_amount=item.get("minSalary"),
                max_amount=item.get("maxSalary"),
                currency=item.get("currency") or "USD",
            )
        return JobPost(
            id=f"himalayas-{item.get('guid')}",
            title=title,
            company_name=item.get("companyName"),
            job_url=item.get("applicationLink"),
            location=Location(city=", ".join(places) if places else "Worldwide"),
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=True,
            listing_type=item.get("employmentType"),
            job_level=", ".join(item.get("seniority") or []) or None,
            compensation=compensation,
            location_restrictions=places or None,
        )
