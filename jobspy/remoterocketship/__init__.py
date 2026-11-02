"""Remote Rocketship (remoterocketship.com), an aggregator of remote jobs
with per-country pages, e.g. /country/romania/jobs/php-developer.

The list is HTML; each job page carries a JobPosting.
"""

from __future__ import annotations

import html
import re

from jobspy.ats import format_description, matches_search, parse_timestamp, within_hours
from jobspy.jsonld import fetch_page, job_posting, json_ld
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

BASE = "https://www.remoterocketship.com"
# ScraperInput.location is the country page, e.g. "romania"; the roles are fixed.
ROLES = ("php-developer", "laravel-developer", "full-stack-developer", "backend-developer")
MAX_DETAILS = 40


class RemoteRocketship(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.REMOTE_ROCKETSHIP, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        country = (scraper_input.location or "romania").lower().replace(" ", "-")
        links: dict[str, str] = {}
        for role in ROLES:
            page = fetch_page(f"{BASE}/country/{country}/jobs/{role}") or ""
            for item in json_ld(page):
                if item.get("@type") != "ItemList":
                    continue
                for element in item.get("itemListElement") or []:
                    url = element.get("url") or ""
                    if "/jobs/" in url:
                        links.setdefault(url, url.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
        jobs = []
        for url, title in list(links.items())[:MAX_DETAILS]:
            data = job_posting(fetch_page(url))
            if not data:
                continue
            posted = parse_timestamp(data["posted"])
            if not within_hours(posted, scraper_input.hours_old):
                continue
            description = format_description(data["description"], scraper_input)
            if not matches_search(scraper_input.search_term, data["title"] or title, description):
                continue
            allowed = data["allowed"] or data["places"]
            jobs.append(JobPost(
                id=f"rocketship-{url.rstrip('/').rsplit('/', 1)[-1]}",
                title=data["title"] or title,
                company_name=data["company"],
                job_url=url,
                location=Location(city=", ".join(allowed or ["Remote"]) + " (remote)"),
                description=description,
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=True,
                location_restrictions=allowed or None,
            ))
        return JobResponse(jobs=jobs)
