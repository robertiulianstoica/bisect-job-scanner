"""joburiit.ro, a Romanian IT job board (WordPress).

The job list comes from the site's REST API (/wp-json/wp/v2/jobs-vacancies),
which gives title, date, link and location ids but not the text; the page
of each recent job is read for company and description.
"""

from __future__ import annotations

import html
import re

import requests

from jobspy.ats import DEFAULT_HEADERS, format_description, get_json, matches_search, parse_timestamp, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

BASE = "https://joburiit.ro/wp-json/wp/v2"


class JoburiIT(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.JOBURIIT, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        items = get_json(f"{BASE}/jobs-vacancies", params={
            "per_page": 100, "_fields": "id,date_gmt,link,title,vacancy-location",
        }) or []
        places = {t["id"]: t["name"] for t in get_json(f"{BASE}/vacancy-location", params={"per_page": 100, "_fields": "id,name"}) or []}
        jobs = []
        for item in items:
            posted = parse_timestamp((item.get("date_gmt") or "") + "Z" if item.get("date_gmt") else None)
            if not within_hours(posted, scraper_input.hours_old):
                continue
            title = html.unescape((item.get("title") or {}).get("rendered") or "")
            company, raw = self._page(item.get("link"))
            description = format_description(raw, scraper_input)
            if not matches_search(scraper_input.search_term, title, description):
                continue
            cities = [places.get(i) for i in item.get("vacancy-location") or [] if places.get(i)]
            remote = any(c.lower() == "remote" for c in cities)
            label = ", ".join(cities + ["Romania"]) if cities else "Romania"
            jobs.append(JobPost(
                id=f"joburiit-{item.get('id')}",
                title=title,
                company_name=company,
                job_url=item.get("link"),
                location=Location(city=label),
                description=description,
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=remote,
                location_restrictions=["Romania"],
            ))
        return JobResponse(jobs=jobs[: scraper_input.results_wanted])

    @staticmethod
    def _page(url: str | None) -> tuple[str | None, str | None]:
        """Company name and the description section of a job page."""
        if not url:
            return None, None
        try:
            page = requests.get(url, headers={**DEFAULT_HEADERS, "Accept": "text/html"}, timeout=30).text
        except requests.RequestException:
            return None, None
        main = re.search(r"<main.*?</main>", page, re.S)
        body = re.sub(r"<(script|style).*?</\1>", "", main.group(0) if main else page, flags=re.S)
        lines = [l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "\n", body)).split("\n") if l.strip()]
        company = lines[1] if len(lines) > 1 else None
        start = body.find("Descrierea jobului")
        end = body.find("Despre companie", start)
        section = body[start:end if end > start else None] if start >= 0 else body
        return company, section
