"""eJobs (ejobs.ro), Romania's largest job board.

The search page lists titles and links (schema.org ItemList); each job page
carries a full JobPosting with date, company, location and description.
"""

from __future__ import annotations

from urllib.parse import quote

from jobspy.ats import format_description, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.jsonld import fetch_page, job_posting, json_ld
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

SEARCH = "https://www.ejobs.ro/locuri-de-munca/{term}"


class EJobs(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.EJOBS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        urls: dict[str, str] = {}
        for term in search_terms(scraper_input.search_term) or ["developer"]:
            for item in json_ld(fetch_page(SEARCH.format(term=quote(term.lower()))) or ""):
                entity = item.get("mainEntity") or {}
                for element in entity.get("itemListElement") or []:
                    name = (element.get("item") or {}).get("name") or ""
                    if element.get("url") and matches_search(scraper_input.search_term, name):
                        urls.setdefault(element["url"], name)
        jobs = []
        for url in list(urls)[: scraper_input.results_wanted]:
            data = job_posting(fetch_page(url))
            if not data:
                continue
            posted = parse_timestamp(data["posted"])
            if not within_hours(posted, scraper_input.hours_old):
                continue
            label = "; ".join(data["places"]) or "Romania"
            jobs.append(JobPost(
                id=f"ejobs-{url.rstrip('/').rsplit('/', 1)[-1]}",
                title=data["title"] or urls[url],
                company_name=data["company"],
                job_url=url,
                location=Location(city=label + (" (remote)" if data["remote"] else "")),
                description=format_description(data["description"], scraper_input),
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=data["remote"],
                location_restrictions=data["allowed"] or ["Romania"],
            ))
        return JobResponse(jobs=jobs)
