"""Hipo (hipo.ro), a Romanian job board where larger employers post directly.

The search (/cautajob/Toate-Domeniile/Toate-Orasele/<term>/) is full-text and
lists links only; each job page carries a JobPosting in JSON-LD. Hipo's
JSON-LD is quirky: the text is UTF-8 encoded twice, `description` holds the
employer's blurb and the job itself is in `educationRequirements`, and the
work mode is only in the page's "Remote work:" row. `datePosted` is the day
the listing was last refreshed, not when it was first posted. Many listings apply on
the employer's own system (PPC's "Aplica" opens ppc.jobful.io).
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from jobspy.ats import format_description, matches_search, parse_timestamp, search_terms, within_hours
from jobspy.jsonld import fetch_page, json_ld
from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site

BASE = "https://www.hipo.ro"
SEARCH = BASE + "/locuri-de-munca/cautajob/Toate-Domeniile/Toate-Orasele/{term}/"
JOB_LINK = re.compile(r'/locuri-de-munca/locuri_de_munca/(\d+)/([^"\'\s<>/]+)/([^"\'\s<>]+)')
# Hipo's own events and promotions, listed among the jobs.
NOT_JOBS = {"Angajatori-de-TOP", "I-LOVE-Tech", "Top-Talents-Romania", "Hipo.ro"}
WORK_MODE = re.compile(r"Remote work:\s*(?:<[^>]+>\s*)*([A-Za-z-]+)", re.I)


def fix_text(text: str | None) -> str:
    """Undo hipo's double UTF-8 encoding ("pieÈei" back to "pieței")."""
    if not text:
        return ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def job_links(page: str | None) -> dict[str, str]:
    """Job id to job URL, in page order, without hipo's own promotions."""
    found: dict[str, str] = {}
    for match in JOB_LINK.finditer(page or ""):
        job_id, company, _ = match.groups()
        if company not in NOT_JOBS:
            found.setdefault(job_id, BASE + match.group(0))
    return found


def parse_job(url: str, page: str | None) -> dict | None:
    if not page:
        return None
    posting = next((i for i in json_ld(page) if i.get("@type") == "JobPosting"), None)
    if not posting:
        return None
    org = posting.get("hiringOrganization") or {}
    address = ((posting.get("jobLocation") or {}).get("address") or {}) if isinstance(posting.get("jobLocation"), dict) else {}
    city = re.sub(r"\s*,\s*$", "", fix_text(address.get("addressLocality")) or "").strip().title()
    mode = WORK_MODE.search(page)
    job_text = fix_text(posting.get("educationRequirements")).lstrip(": ")
    employer = fix_text(posting.get("description"))
    return {
        "title": html.unescape(fix_text(posting.get("title"))),
        "company": html.unescape(fix_text(org.get("name") if isinstance(org, dict) else str(org))),
        "posted": posting.get("datePosted"),
        "city": city or "Romania",
        "work_mode": mode.group(1).lower() if mode else None,
        "description": "\n\n".join(t for t in (job_text, employer) if t),
    }


class Hipo(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.HIPO, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        urls: dict[str, str] = {}
        for term in search_terms(scraper_input.search_term) or ["developer"]:
            for job_id, url in job_links(fetch_page(SEARCH.format(term=quote(term)))).items():
                urls.setdefault(job_id, url)
        jobs = []
        for job_id, url in list(urls.items())[: scraper_input.results_wanted]:
            data = parse_job(url, fetch_page(url))
            if not data or not matches_search(scraper_input.search_term, data["title"], data["description"]):
                continue
            posted = parse_timestamp(data["posted"])
            if not within_hours(posted, scraper_input.hours_old):
                continue
            remote = data["work_mode"] == "remote"
            label = data["city"] + (f" ({data['work_mode']})" if data["work_mode"] else "")
            jobs.append(JobPost(
                id=f"hipo-{job_id}",
                title=data["title"],
                company_name=data["company"],
                job_url=url,
                location=Location(city=label),
                description=format_description(data["description"], scraper_input),
                date_posted=posted.date() if posted else None,
                posted_at=posted,
                is_remote=remote,
                location_restrictions=["Romania"],
            ))
        return JobResponse(jobs=jobs)
