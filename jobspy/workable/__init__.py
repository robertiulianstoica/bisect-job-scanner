"""Workable, two ways:
- the cross-company job search (jobs.workable.com), through the JSON API behind
  it. `day_range` (1, 7, 30) is the only reliable way to get recent jobs:
  results are not sorted by date;
- a company's own board (apply.workable.com/<slug>), through its public widget
  API, when company_boards names Workable accounts. Accounts post one copy of a
  job per country; the copies are merged into one job listing every country.
"""

from __future__ import annotations

from jobspy.ats import read_boards, format_description, get_json, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

API = "https://jobs.workable.com/api/v1/jobs"
ACCOUNT_API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"
MAX_PAGES = 5


class Workable(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.WORKABLE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        accounts = (scraper_input.company_boards or {}).get("workable", [])
        if accounts:
            return JobResponse(jobs=read_boards(accounts, lambda slug: self._read_account(slug, scraper_input)))
        hours = scraper_input.hours_old
        day_range = 1 if hours and hours <= 24 else 7 if hours and hours <= 168 else 30
        seen: dict[str, JobPost] = {}
        for term in search_terms(scraper_input.search_term) or [""]:
            params = {"query": term, "day_range": day_range}
            if scraper_input.is_remote:
                params["workplace"] = "remote"
            if scraper_input.location:
                params["location"] = scraper_input.location
            for _ in range(MAX_PAGES):
                data = get_json(API, params=params)
                if not data or not data.get("jobs"):
                    break
                for item in data["jobs"]:
                    post = self._to_post(item, scraper_input)
                    if post and post.id not in seen:
                        seen[post.id] = post
                token = data.get("nextPageToken")
                if not token or len(seen) >= scraper_input.results_wanted:
                    break
                params["pageToken"] = token
        return JobResponse(jobs=list(seen.values())[: scraper_input.results_wanted])

    def _to_post(self, item: dict, scraper_input: ScraperInput) -> JobPost | None:
        posted = parse_timestamp(item.get("created"))
        if not within_hours(posted, scraper_input.hours_old):
            return None
        body = "".join(item.get(k) or "" for k in ("description", "requirementsSection", "benefitsSection"))
        description = format_description(body, scraper_input)
        title = item.get("title") or ""
        if not matches_search(scraper_input.search_term, title, description):
            return None
        places = [p for p in item.get("locations") or [] if p and p != "TELECOMMUTE"]
        workplace = item.get("workplace")
        label = ", ".join(places) + (f" ({workplace})" if workplace else "")
        return JobPost(
            id=f"workable-{item.get('id')}",
            title=title,
            company_name=(item.get("company") or {}).get("title"),
            job_url=item.get("url"),
            location=Location(city=label) if label else None,
            description=description,
            date_posted=posted.date() if posted else None,
            posted_at=posted,
            is_remote=workplace == "remote",
            listing_type=item.get("employmentType") or None,
            location_restrictions=places or None,
        )

    def _read_account(self, slug: str, scraper_input: ScraperInput) -> list[JobPost]:
        data = get_json(ACCOUNT_API.format(slug=slug), params={"details": "true"})
        if not data:
            return []
        # One copy per country: group by title, keep the newest, list every country.
        groups: dict[str, list[dict]] = {}
        for item in data.get("jobs") or []:
            groups.setdefault((item.get("title") or "").strip(), []).append(item)
        posts = []
        for title, items in groups.items():
            items.sort(key=lambda i: i.get("published_on") or i.get("created_at") or "", reverse=True)
            item = items[0]
            posted = parse_timestamp(item.get("published_on") or item.get("created_at"))
            if not within_hours(posted, scraper_input.hours_old):
                continue
            description = format_description(item.get("description") or "", scraper_input)
            if not matches_search(scraper_input.search_term, title, description):
                continue
            places = []
            for i in items:
                for loc in i.get("locations") or [{"country": i.get("country"), "city": i.get("city")}]:
                    place = (loc or {}).get("country") or (loc or {}).get("city")
                    if place and place not in places:
                        places.append(place)
            remote = any(str(i.get("telecommuting")).lower() == "true" for i in items)
            label = ", ".join(places) + (" (remote)" if remote else "")
            posts.append(JobPost(
                id=f"workable-{item.get('shortcode')}",
                source_board=f"workable:{slug}",
                title=title,
                company_name=data.get("name") or slug,
                job_url=item.get("url") or item.get("shortlink"),
                job_url_direct=item.get("application_url"),
                location=Location(city=label) if label else None,
                description=description,
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=remote,
                listing_type=item.get("employment_type") or None,
                location_restrictions=places or None,
            ))
        return posts
