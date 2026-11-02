"""Personio career sites, through each company's XML feed:
<company>.jobs.personio.com/xml (older sites answer on .de).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from jobspy.ats import read_boards, DEFAULT_HEADERS, format_description, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger

log = create_logger("Personio")
DOMAINS = ("jobs.personio.com", "jobs.personio.de")


class Personio(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.PERSONIO, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        def read(company):
            root, domain = self._feed(company)
            if root is None:
                log.debug(f"board {company} not found or unreadable")
                return []
            return [p for p in (self._to_post(company, domain, pos, scraper_input) for pos in root.findall("position")) if p]

        return JobResponse(jobs=read_boards((scraper_input.company_boards or {}).get("personio", []), read))

    def _feed(self, company: str):
        for domain in DOMAINS:
            try:
                response = requests.get(f"https://{company}.{domain}/xml", headers=DEFAULT_HEADERS, timeout=30)
                if response.status_code == 200 and b"<workzag-jobs" in response.content[:500]:
                    return ET.fromstring(response.content), domain
            except (requests.RequestException, ET.ParseError):
                continue
        return None, None

    def _to_post(self, company, domain, position, scraper_input) -> JobPost | None:
        get = lambda tag: (position.findtext(tag) or "").strip()
        posted = parse_timestamp(get("createdAt"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        body = "".join(
            f"<h3>{(d.findtext('name') or '').strip()}</h3>{d.findtext('value') or ''}"
            for d in position.findall("./jobDescriptions/jobDescription")
        )
        description = format_description(body, scraper_input)
        title = get("name")
        if not matches_search(scraper_input.search_term, title, description):
            return None
        offices = [get("office")] + [o.text.strip() for o in position.findall("./additionalOffices/office") if o.text]
        offices = [o for o in offices if o]
        return JobPost(
            id=f"personio-{company}-{get('id')}",
            source_board=f"personio:{company}",
            title=title,
            company_name=company,
            job_url=f"https://{company}.{domain}/job/{get('id')}",
            location=Location(city=", ".join(offices)) if offices else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=any("remote" in o.lower() for o in offices),
            listing_type=get("employmentType") or None,
            location_restrictions=offices or None,
        )
