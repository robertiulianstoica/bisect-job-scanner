"""Recruitee career sites, through each company's offers API:
<company>.recruitee.com/api/offers/ (also served on custom domains).
"""

from __future__ import annotations

from jobspy.ats import read_boards, format_description, get_json, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Recruitee")


class Recruitee(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.RECRUITEE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        def read(company):
            host = company if "." in company else f"{company}.recruitee.com"
            data = get_json(f"https://{host}/api/offers/")
            if not data:
                log.debug(f"board {company} not found or unreadable")
                return []
            return [p for p in (self._to_post(company, o, scraper_input) for o in data.get("offers", [])) if p]

        return JobResponse(jobs=read_boards((scraper_input.company_boards or {}).get("recruitee", []), read))

    def _to_post(self, company: str, offer: dict, scraper_input: ScraperInput) -> JobPost | None:
        if offer.get("status") not in (None, "published"):
            return None
        posted = parse_timestamp(offer.get("published_at") or offer.get("created_at"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        description = format_description((offer.get("description") or "") + (offer.get("requirements") or ""), scraper_input)
        title = offer.get("title") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = [l.get("country") or l.get("city") for l in offer.get("locations") or [] if l] or [offer.get("country")]
        places = [p for p in places if p]
        remote = bool(offer.get("remote"))
        label = offer.get("location") or ", ".join(places)
        return JobPost(
            id=f"recruitee-{offer.get('id')}",
            source_board=f"recruitee:{company}",
            title=title,
            company_name=offer.get("company_name") or company,
            job_url=offer.get("careers_url") or offer.get("url"),
            job_url_direct=offer.get("careers_apply_url"),
            location=Location(city=label + (" (remote)" if remote else "")) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=remote,
            listing_type=offer.get("employment_type_code"),
            location_restrictions=places or None,
        )
