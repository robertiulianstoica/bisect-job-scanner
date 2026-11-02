"""SmartRecruiters company boards, through the public postings API:
api.smartrecruiters.com/v1/companies/<company>/postings. The company is the
identifier in jobs.smartrecruiters.com/<company>/...

The list has title, date and a remote/hybrid flag; the description is
fetched only for postings released in the last few days.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

from jobspy.ats import format_description, get_json, matches_search, parse_timestamp, read_boards, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
DETAIL_DAYS = 3


class SmartRecruiters(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.SMARTRECRUITERS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DETAIL_DAYS)

        def read(company):
            posts, offset = [], 0
            while offset < 1000:
                data = get_json(API.format(company=company), params={"limit": 100, "offset": offset})
                if not data or not data.get("content"):
                    break
                for item in data["content"]:
                    released = parse_timestamp(item.get("releasedDate"))
                    if not within_hours(released, scraper_input.hours_old) or (released and released < cutoff):
                        continue
                    post = self._to_post(company, item, released, scraper_input)
                    if post:
                        posts.append(post)
                offset += 100
                if offset >= data.get("totalFound", 0):
                    break
            return posts

        return JobResponse(jobs=read_boards((scraper_input.company_boards or {}).get("smartrecruiters", []), read))

    def _to_post(self, company, item, released, scraper_input) -> JobPost | None:
        detail = get_json(f"{API.format(company=company)}/{item.get('id')}") or {}
        sections = (detail.get("jobAd") or {}).get("sections") or {}
        body = "".join(f"<h3>{s.get('title', '')}</h3>{s.get('text', '')}" for s in sections.values() if isinstance(s, dict))
        description = format_description(body, scraper_input)
        title = item.get("name") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        where = item.get("location") or {}
        mode = "remote" if where.get("remote") else "hybrid" if where.get("hybrid") else "on-site"
        label = f"{where.get('fullLocation') or where.get('city') or ''} ({mode})"
        return JobPost(
            id=f"smartrecruiters-{item.get('id')}",
            source_board=f"smartrecruiters:{company}",
            title=title,
            company_name=(item.get("company") or {}).get("name") or company,
            job_url=f"https://jobs.smartrecruiters.com/{company}/{item.get('id')}",
            location=Location(city=label),
            description=description,
            date_posted=released.date() if released else None,
            posted_at=released,
            is_remote=bool(where.get("remote")),
            listing_type=(item.get("typeOfEmployment") or {}).get("label"),
        )
