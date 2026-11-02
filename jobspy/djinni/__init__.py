"""Djinni (djinni.co), the Ukrainian / Eastern European tech board, where
many companies hire remotely across Europe.

The RSS feed per primary keyword gives title, link and date; each recent
job page carries a JobPosting with the company and the regions candidates
may apply from (applicantLocationRequirements).
"""

from __future__ import annotations

from jobspy.ats import format_description, matches_search, search_terms, within_hours
from jobspy.jsonld import fetch_page, job_posting
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.rss import fetch_items, pub_date, text

FEED = "https://djinni.co/jobs/rss/?primary_keyword={keyword}"
# Djinni's primary keywords; Symfony and Laravel roles sit under PHP.
KEYWORDS = {"php": "PHP", "symfony": "PHP", "laravel": "PHP", "python": "Python", "node.js": "Node.js",
            "typescript": "JavaScript", "react": "JavaScript", "full stack": "Fullstack"}


class Djinni(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.DJINNI, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        keywords = {KEYWORDS.get(t.lower(), t) for t in search_terms(scraper_input.search_term, titles=False)} or {"PHP"}
        seen: dict[str, JobPost] = {}
        for keyword in keywords:
            for item in fetch_items(FEED.format(keyword=keyword)):
                posted = pub_date(item)
                link = text(item, "link")
                if not link or link in seen or not within_hours(posted, scraper_input.hours_old):
                    continue
                title = text(item, "title") or ""
                description = format_description(text(item, "description"), scraper_input)
                if not matches_search(scraper_input.search_term, title, description):
                    continue
                data = job_posting(fetch_page(link)) or {}
                allowed = data.get("allowed") or []
                label = ", ".join(allowed or data.get("places") or ["location not stated"])
                if data.get("remote"):
                    label += " (remote)"
                seen[link] = JobPost(
                    id=f"djinni-{link.rstrip('/').rsplit('/', 1)[-1].split('-', 1)[0]}",
                    title=title,
                    company_name=data.get("company"),
                    job_url=link,
                    location=Location(city=label),
                    description=description,
                    date_posted=posted.date() if posted else None,
                    posted_at=posted,
                    is_remote=bool(data.get("remote")),
                    location_restrictions=allowed or None,
                )
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])
