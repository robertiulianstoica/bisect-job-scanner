"""peviitor.ro, the Romanian job search engine that collects jobs from
company career sites, through the API behind its site
(api.peviitor.ro/v1/search/?q=<term>&page=<n>).

Results carry title, company, cities and a work mode (remote, hybrid,
on-site) but no description; the title stands in for it.
"""

from __future__ import annotations

import html

from jobspy.ats import get_json, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

API = "https://api.peviitor.ro/v1/search/"
MAX_PAGES = 5


class Peviitor(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.PEVIITOR, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        seen: dict[str, JobPost] = {}
        for term in search_terms(scraper_input.search_term) or [""]:
            for page in range(1, MAX_PAGES + 1):
                data = get_json(API, params={"q": term, "page": page})
                docs = ((data or {}).get("response") or {}).get("docs") or []
                if not docs:
                    break
                fresh = False
                for doc in docs:
                    posted = parse_timestamp(doc.get("date"))
                    if not within_hours(posted, scraper_input.hours_old):
                        continue
                    fresh = True
                    post = self._to_post(doc, posted, scraper_input)
                    if post and post.id not in seen:
                        seen[post.id] = post
                if not fresh:
                    break
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])

    def _to_post(self, doc: dict, posted, scraper_input: ScraperInput) -> JobPost | None:
        title = html.unescape(doc.get("title") or "")
        tags = " ".join(doc.get("tags") or [])
        if not matches_search(scraper_input.search_term, title, tags):
            return None
        mode = doc.get("workmode") or doc.get("remote") or ""
        cities = doc.get("city") or doc.get("location") or []
        label = "; ".join(cities) if cities else "Romania"
        return JobPost(
            id=f"peviitor-{doc.get('url')}",
            title=title,
            company_name=doc.get("company"),
            job_url=doc.get("url"),
            location=Location(city=f"{label} ({mode})" if mode else label),
            description=f"{title}. Tags: {tags}",
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=mode == "remote",
            location_restrictions=["Romania"],
        )
