"""Hacker News "Ask HN: Who is hiring?", the monthly thread where companies
post directly, read through the HN Algolia API.

Only top-level comments count (replies are discussion, and the separate
"Who wants to be hired?" thread is job seekers). A post's first line is
usually "Company | Role | Location | Remote/Onsite | ...".
"""

from __future__ import annotations

import html
import re

from jobspy.ats import format_description, get_json, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

API = "https://hn.algolia.com/api/v1"


class HackerNews(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.HACKER_NEWS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        stories = (get_json(f"{API}/search_by_date", params={"tags": "story,author_whoishiring", "hitsPerPage": 6}) or {}).get("hits", [])
        story = next((s for s in stories if "who is hiring" in (s.get("title") or "").lower()), None)
        if not story:
            return JobResponse(jobs=[])
        story_id = story["objectID"]
        seen: dict[str, JobPost] = {}
        for term in search_terms(scraper_input.search_term) or [""]:
            hits = (get_json(f"{API}/search", params={"tags": f"comment,story_{story_id}", "query": term, "hitsPerPage": 200}) or {}).get("hits", [])
            for hit in hits:
                if str(hit.get("parent_id")) != str(story_id):
                    continue
                posted = parse_timestamp(hit.get("created_at"))
                if not within_hours(posted, scraper_input.hours_old):
                    continue
                raw = hit.get("comment_text") or ""
                # Job seekers sometimes post in the hiring thread too.
                if re.match(r"\s*(location|looking for)\s*:", raw, re.I) or "willing to relocate" in raw.lower():
                    continue
                first = html.unescape(re.sub(r"<[^>]+>", " ", re.split(r"<p>|\n", raw, 1)[0])).strip()
                description = format_description(raw, scraper_input)
                if not matches_search(scraper_input.search_term, first, description):
                    continue
                parts = [p.strip() for p in first.split("|")]
                where = ", ".join(p for p in parts[1:] if re.search(r"remote|onsite|on-site|hybrid|europe|emea|eu\b|usa|us\b|uk|[A-Z][a-z]+,", p, re.I)) or first
                seen.setdefault(hit["objectID"], JobPost(
                    id=f"hn-{hit['objectID']}",
                    title=first[:160],
                    company_name=parts[0][:80] if parts else None,
                    job_url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    location=Location(city=where[:160]),
                    description=description,
                    date_posted=posted.date() if posted else None,
                    posted_at=posted,
                    is_remote="remote" in first.lower(),
                ))
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])
