"""symfony.com/jobs, the official Symfony job board, through its RSS feed.

Titles read "<role> at <company>"; the description holds salary, contract
and location.
"""

from __future__ import annotations

import re

from jobspy.ats import format_description, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.rss import fetch_items, pub_date, text

FEED = "https://symfony.com/jobs.rss"


class SymfonyJobs(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.SYMFONY_JOBS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        jobs = []
        for item in fetch_items(FEED):
            posted = pub_date(item)
            if not within_hours(posted, scraper_input.hours_old):
                continue
            raw_title = text(item, "title") or ""
            role, _, company = raw_title.rpartition(" at ")
            description = format_description(text(item, "description"), scraper_input) or ""
            location = re.search(r"Location:\**\s*([^\n<]+)", description)
            link = text(item, "link")
            jobs.append(JobPost(
                id=f"symfony-{link.rsplit('/', 1)[-1] if link else raw_title}",
                title=(role or raw_title) + " (Symfony)" if "symfony" not in (role or raw_title).lower() else (role or raw_title),
                company_name=company or None,
                job_url=link,
                location=Location(city=location.group(1).strip()) if location else None,
                description=description,
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote="remote" in description.lower(),
            ))
        return JobResponse(jobs=jobs[: scraper_input.results_wanted])
