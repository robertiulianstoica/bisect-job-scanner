"""LaraJobs, the Laravel job board, through its RSS feed (larajobs.com/feed).

The feed carries title, company, location, tags and salary but no
description; the tags stand in for it when matching the search.
"""

from __future__ import annotations

from jobspy.ats import matches_search, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.rss import fetch_items, pub_date, text

FEED = "https://larajobs.com/feed"
NS = {"job": "https://larajobs.com"}


class LaraJobs(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.LARAJOBS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        jobs = []
        for item in fetch_items(FEED):
            posted = pub_date(item)
            if not within_hours(posted, scraper_input.hours_old):
                continue
            title = text(item, "title") or ""
            tags = text(item, "job:tags", NS) or ""
            location = text(item, "job:location", NS)
            salary = text(item, "job:salary", NS)
            description = f"Tags: {tags}" + (f"\nSalary: {salary}" if salary else "")
            # Every LaraJobs role is Laravel; the search only narrows it further.
            if not matches_search(scraper_input.search_term, title, description, "Laravel PHP"):
                continue
            link = text(item, "link")
            jobs.append(JobPost(
                id=f"larajobs-{link.rsplit('/', 1)[-1] if link else title}",
                title=title,
                company_name=text(item, "job:company", NS),
                job_url=link,
                location=Location(city=location) if location else None,
                description=description,
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=bool(location and "remote" in location.lower()),
                listing_type=text(item, "job:job_type", NS),
            ))
        return JobResponse(jobs=jobs[: scraper_input.results_wanted])
