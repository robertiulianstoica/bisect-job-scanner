"""Greenhouse job boards, through the public boards API (no login).

One request per company: boards-api.greenhouse.io/v1/boards/<token>/jobs
returns every open job with its full description. The board token is the
slug in job-boards.greenhouse.io/<token>.
"""

from __future__ import annotations

from jobspy.ats import read_boards, format_description, get_json, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Greenhouse")

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class Greenhouse(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.GREENHOUSE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        tokens = (scraper_input.company_boards or {}).get("greenhouse", [])
        def read(token):
            data = get_json(API.format(token=token))
            if not data:
                log.debug(f"board {token} not found or unreadable")
                return []
            return [p for p in (self._to_post(token, i, scraper_input) for i in data.get("jobs", [])) if p]

        return JobResponse(jobs=read_boards(tokens, read))

    def _to_post(self, token: str, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        posted = parse_timestamp(item.get("first_published") or item.get("updated_at"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        description = format_description(item.get("content"), scraper_input)
        title = item.get("title") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        location_name = (item.get("location") or {}).get("name")
        return JobPost(
            id=f"gh-{item.get('id')}",
            source_board=f"greenhouse:{token}",
            title=title,
            company_name=item.get("company_name") or token,
            job_url=item.get("absolute_url"),
            location=Location(city=location_name) if location_name else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=bool(location_name and "remote" in location_name.lower()),
        )
