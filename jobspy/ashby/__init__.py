"""Ashby job boards, through the public posting API (no login).

api.ashbyhq.com/posting-api/job-board/<org> lists every open job with its
description, workplace type and, when published, compensation. The org is
the slug in jobs.ashbyhq.com/<org>.
"""

from __future__ import annotations

from jobspy.ats import read_boards, format_description, get_json, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Ashby")

API = "https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"


class Ashby(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.ASHBY, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        orgs = (scraper_input.company_boards or {}).get("ashby", [])
        def read(org):
            data = get_json(API.format(org=org))
            if not data:
                log.debug(f"board {org} not found or unreadable")
                return []
            return [p for p in (self._to_post(org, i, scraper_input) for i in data.get("jobs", [])) if p]

        return JobResponse(jobs=read_boards(orgs, read))

    def _to_post(self, org: str, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        if item.get("isListed") is False:
            return None
        posted = parse_timestamp(item.get("publishedAt"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        description = format_description(item.get("descriptionHtml"), scraper_input)
        title = item.get("title") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = [item.get("location")] + [
            s.get("location") for s in item.get("secondaryLocations") or []
        ]
        places = [p for p in places if p]
        workplace = item.get("workplaceType")
        label = ", ".join(places) + (f" ({workplace})" if workplace else "")
        return JobPost(
            id=f"ashby-{item.get('id')}",
            source_board=f"ashby:{org}",
            title=title,
            company_name=org,
            job_url=item.get("jobUrl"),
            job_url_direct=item.get("applyUrl"),
            location=Location(city=label) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=bool(item.get("isRemote")) or workplace == "Remote",
            listing_type=item.get("employmentType"),
            location_restrictions=places or None,
        )
