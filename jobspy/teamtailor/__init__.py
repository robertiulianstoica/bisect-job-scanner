"""Teamtailor career sites, through each site's RSS feed (/jobs.rss), which
carries the description, a remote status and the locations. A board is the
site's host: acme.teamtailor.com or a custom domain such as careers.acme.com.
"""

from __future__ import annotations

from jobspy.ats import format_description, matches_search, read_boards, within_hours
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.rss import fetch_items, pub_date, text

NS = {"tt": "https://teamtailor.com/locations"}


class Teamtailor(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.TEAMTAILOR, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        def read(host):
            host = host if "." in host else f"{host}.teamtailor.com"
            posts = []
            for item in fetch_items(f"https://{host}/jobs.rss"):
                posted = pub_date(item)
                if not within_hours(posted, scraper_input.hours_old):
                    continue
                title = text(item, "title") or ""
                description = format_description(text(item, "description"), scraper_input)
                if not matches_search(scraper_input.search_term, title, description):
                    continue
                places = [n.text.strip() for n in item.findall("./tt:locations/tt:location/tt:name", NS) if n.text]
                countries = [n.text.strip() for n in item.findall("./tt:locations/tt:location/tt:country", NS) if n.text]
                status = text(item, "remoteStatus") or ""
                label = "; ".join(places) + (f" ({status})" if status and status != "none" else "")
                link = text(item, "link")
                posts.append(JobPost(
                    id=f"teamtailor-{text(item, 'guid') or link}",
                    source_board=f"teamtailor:{host}",
                    title=title,
                    company_name=host.split(".")[0] if host.endswith("teamtailor.com") else host.split(".")[-2],
                    job_url=link,
                    location=Location(city=label) if label else None,
                    description=description,
                    date_posted=posted.date() if posted else None,
                    posted_at=posted,
                    is_remote=status in ("fully", "remote"),
                    location_restrictions=countries or None,
                ))
            return posts

        return JobResponse(jobs=read_boards((scraper_input.company_boards or {}).get("teamtailor", []), read))
