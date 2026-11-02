"""BestJobs (bestjobs.eu), one of Romania's largest job boards.

The search page ships its results in __NEXT_DATA__: title, company,
locations and the number of applications, but no posting date, so recency
comes from the scanner remembering what it has already seen.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from jobspy.ats import matches_search, search_terms
from jobspy.jsonld import fetch_page
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

SEARCH = "https://www.bestjobs.eu/ro/locuri-de-munca/{term}"
JOB = "https://www.bestjobs.eu/ro/loc-de-munca/{slug}"


class BestJobs(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.BESTJOBS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        seen: dict[str, JobPost] = {}
        for term in search_terms(scraper_input.search_term) or ["developer"]:
            page = fetch_page(SEARCH.format(term=quote(term.lower())))
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page or "", re.S)
            if not match:
                continue
            try:
                items = json.loads(match.group(1))["props"]["pageProps"]["jobListCardsFromServer"]["items"]
            except (ValueError, KeyError, TypeError):
                continue
            for item in items:
                title = item.get("title") or ""
                if not matches_search(scraper_input.search_term, title):
                    continue
                places = [p.get("name") for p in item.get("locations") or [] if p.get("name")]
                label = "; ".join(places) or "Romania"
                post = JobPost(
                    id=f"bestjobs-{item.get('id')}",
                    title=title,
                    company_name=item.get("companyName"),
                    job_url=JOB.format(slug=item.get("slug")),
                    job_url_direct=item.get("ownApplyUrl") or None,
                    location=Location(city=label),
                    description=title,
                    num_applicants=item.get("applications"),
                    is_remote="remote" in label.lower(),
                    location_restrictions=["Romania"],
                )
                seen.setdefault(post.id, post)
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])
