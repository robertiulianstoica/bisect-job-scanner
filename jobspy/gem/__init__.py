"""Gem job boards, through the public job board API (no login).

api.gem.com/job_board/v0/<slug>/job_posts/ lists every open job with its
description, location and workplace type, in much the same shape as
Greenhouse's board API. The slug is the one in jobs.gem.com/<slug>.
"""

from __future__ import annotations

from jobspy.ats import read_boards, format_description, get_json, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Gem")

API = "https://api.gem.com/job_board/v0/{slug}/job_posts/"


class Gem(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.GEM, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        slugs = (scraper_input.company_boards or {}).get("gem", [])

        def read(slug):
            data = get_json(API.format(slug=slug))
            if not isinstance(data, list):
                log.debug(f"board {slug} not found or unreadable")
                return []
            return [p for p in (self._to_post(slug, i, scraper_input) for i in data) if p]

        return JobResponse(jobs=read_boards(slugs, read))

    def _to_post(self, slug: str, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        posted = parse_timestamp(item.get("first_published_at") or item.get("created_at"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        description = format_description(item.get("content"), scraper_input)
        title = item.get("title") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = [(item.get("location") or {}).get("name")] + [
            (o.get("location") or {}).get("name") for o in item.get("offices") or []
        ]
        places = list(dict.fromkeys(p for p in places if p))
        workplace = item.get("location_type")
        label = ", ".join(places) + (f" ({workplace})" if workplace else "")
        return JobPost(
            id=f"gem-{item.get('id')}",
            source_board=f"gem:{slug}",
            title=title,
            company_name=slug,
            job_url=item.get("absolute_url"),
            location=Location(city=label) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=workplace == "remote",
            listing_type=item.get("employment_type"),
            location_restrictions=places or None,
        )
