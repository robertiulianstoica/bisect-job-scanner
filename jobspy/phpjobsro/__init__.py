"""phpjobs.ro, a Romanian board for PHP jobs only.

The home page lists recent jobs (/jobs/<id>-<slug>/); each job page carries a
JobPosting, whose datePosted is written like "Jan. 9, 2023, 1:17 p.m.", and
which may still list old adverts, so the date is checked.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from jobspy.ats import format_description, matches_search, parse_timestamp, within_hours
from jobspy.jsonld import fetch_page, job_posting
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

BASE = "https://phpjobs.ro"
MAX_DETAILS = 40


def parse_django_date(value: str | None):
    """ISO, or Django's default "Jan. 9, 2023, 1:17 p.m." (month may be spelt out)."""
    parsed = parse_timestamp(value)
    if parsed or not value:
        return parsed
    cleaned = value.replace("a.m.", "AM").replace("p.m.", "PM").replace("Sept.", "Sep.").replace(".", "")
    cleaned = re.sub(r"\bnoon\b", "12 PM", re.sub(r"\bmidnight\b", "12 AM", cleaned))
    for fmt in ("%b %d, %Y, %I:%M %p", "%b %d, %Y, %I %p", "%B %d, %Y, %I:%M %p", "%B %d, %Y, %I %p", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class PhpJobsRo(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.PHPJOBS_RO, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        page = fetch_page(BASE + "/") or ""
        links = list(dict.fromkeys(re.findall(r'href="(/jobs/\d+-[^"/]+/)"', page)))[:MAX_DETAILS]
        jobs = []
        for path in links:
            url = BASE + path
            data = job_posting(fetch_page(url))
            if not data:
                continue
            posted = parse_django_date(data["posted"])
            if not within_hours(posted, scraper_input.hours_old):
                continue
            description = format_description(data["description"], scraper_input)
            # Every job here is PHP; the search only narrows further.
            if not matches_search(scraper_input.search_term, data["title"], description, "PHP"):
                continue
            allowed = data["allowed"]
            label = ", ".join(allowed or data["places"] or ["Romania"]) + (" (remote)" if data["remote"] else "")
            jobs.append(JobPost(
                id=f"phpjobsro-{path.strip('/').rsplit('/', 1)[-1].split('-', 1)[0]}",
                title=data["title"],
                company_name=data["company"],
                job_url=url,
                location=Location(city=label),
                description=description,
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=data["remote"],
                location_restrictions=allowed or None,
            ))
        return JobResponse(jobs=jobs)
