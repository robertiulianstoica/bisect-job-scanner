"""devjob.ro, a Romanian developer job board (sister of swissdevjobs.ch),
through its RSS feed of every open job (devjob.ro/rss).

Titles read "<role> @ <company> [<salary>]"; the description starts with the
salary and the requirements.
"""

from __future__ import annotations

import html
import re

from jobspy.ats import format_description, matches_search, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.rss import fetch_items, pub_date, text

FEED = "https://devjob.ro/rss"
NS = {"content": "http://purl.org/rss/1.0/modules/content/"}


class DevJobRo(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.DEVJOB_RO, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        jobs = []
        for item in fetch_items(FEED):
            posted = pub_date(item)
            if not within_hours(posted, scraper_input.hours_old):
                continue
            raw_title = html.unescape(text(item, "title") or "")
            match = re.match(r"(.*?)\s+@\s+(.*?)(?:\s+\[(.*)\])?$", raw_title)
            role, company, salary = (match.groups() if match else (raw_title, None, None))
            body = text(item, "content:encoded", NS) or text(item, "description")
            description = format_description(body, scraper_input)
            if not matches_search(scraper_input.search_term, role, description):
                continue
            link = (text(item, "link") or "").split("?")[0]
            where = re.search(r"(?i)(fully remote|remote|hybrid|on-site|onsite)[^.\n]{0,60}", description or "")
            label = "Romania" + (f" ({where.group(1).lower()})" if where else "")
            jobs.append(JobPost(
                id=f"devjobro-{link.rsplit('/', 1)[-1]}",
                title=role,
                company_name=company,
                job_url=link,
                location=Location(city=label),
                description=(f"Salary: {salary}\n" if salary else "") + (description or ""),
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=bool(where and "remote" in where.group(1).lower()),
                location_restrictions=["Romania"],
            ))
        return JobResponse(jobs=jobs[: scraper_input.results_wanted])
