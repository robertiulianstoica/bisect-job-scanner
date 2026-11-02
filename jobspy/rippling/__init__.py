"""Rippling Recruiting boards, through the public board API:
api.rippling.com/platform/api/ats/v1/board/<slug>/jobs lists every opening
(no date, no description); .../jobs/<uuid> has both, plus the pay range.

Only engineering titles are read in full, so a board of sales and data-centre
roles costs one request.
"""

from __future__ import annotations

from jobspy.ats import format_description, get_json, matches_search, parse_timestamp, read_boards, within_hours
from jobspy.model import Compensation, CompensationInterval, JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger
from jobspy.workday import ENGINEERING

log = create_logger("Rippling")

API = "https://api.rippling.com/platform/api/ats/v1/board"
INTERVALS = {"YEAR": CompensationInterval.YEARLY, "MONTH": CompensationInterval.MONTHLY,
             "HOUR": CompensationInterval.HOURLY}


class Rippling(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.RIPPLING, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        def read(slug):
            listed = get_json(f"{API}/{slug}/jobs")
            if not isinstance(listed, list):
                log.debug(f"board {slug} not found or unreadable")
                return []
            posts = []
            # The list repeats an opening once per work location.
            unique = {item.get("uuid"): item for item in listed if item.get("uuid")}
            for item in unique.values():
                if ENGINEERING.search(item.get("name") or ""):
                    post = self._to_post(slug, item, scraper_input)
                    if post:
                        posts.append(post)
            return posts

        return JobResponse(jobs=read_boards((scraper_input.company_boards or {}).get("rippling", []), read))

    def _to_post(self, slug: str, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        detail = get_json(f"{API}/{slug}/jobs/{item.get('uuid')}")
        if not detail:
            return None
        posted = parse_timestamp(detail.get("createdOn"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        title = detail.get("name") or item.get("name") or ""
        description = format_description(description_html(detail), scraper_input)
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = [p for p in detail.get("workLocations") or [] if p]
        label = ", ".join(places) or (item.get("workLocation") or {}).get("label")
        return JobPost(
            id=f"rippling-{detail.get('uuid') or item.get('uuid')}",
            source_board=f"rippling:{slug}",
            title=title,
            company_name=detail.get("companyName") or slug,
            job_url=detail.get("url") or item.get("url"),
            location=Location(city=label) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote="remote" in (label or "").lower(),
            listing_type=((detail.get("employmentType") or {}).get("id")),
            compensation=pay(detail.get("payRangeDetails")),
            location_restrictions=places or None,
        )


def description_html(detail: dict) -> str | None:
    """The description is a dict of HTML sections (company, role) or a plain string."""
    value = detail.get("description")
    if isinstance(value, dict):
        return "".join(v for v in value.values() if isinstance(v, str))
    return value


def pay(ranges) -> Compensation | None:
    """The widest stated range when every range shares one currency and period."""
    ranges = [r for r in ranges or [] if r.get("rangeStart") or r.get("rangeEnd")]
    if not ranges or len({(r.get("currency"), r.get("frequency")) for r in ranges}) != 1:
        return None
    first = ranges[0]
    return Compensation(
        interval=INTERVALS.get(first.get("frequency")),
        min_amount=min(r.get("rangeStart") or r.get("rangeEnd") for r in ranges),
        max_amount=max(r.get("rangeEnd") or r.get("rangeStart") for r in ranges),
        currency=first.get("currency"),
    )
