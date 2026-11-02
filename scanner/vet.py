"""Check that an advert comes from a real employer before applying to it.

Some adverts exist only to collect CVs and personal data. This looks at the
posting's job board and the company's domain and reports what looks off:

    python -m scanner.vet <job url> [--domain company.com]

It reports:
- when the company's domain was registered (a young domain is a warning);
- how many jobs the board holds, and how many are this same title again
  (one advert cloned across many countries is a warning);
- whether the company's own site links to that board.

Nothing here decides alone: it prints the facts and the warnings, and the
application waits until someone has looked at them.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlparse

import requests

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
}
YOUNG_DOMAIN_DAYS = 2 * 365
CLONES_WARN = 3
CAREER_PATHS = ("", "/careers", "/careers/", "/careers/open-positions/", "/jobs", "/en/careers", "/about/careers", "/join-us")


@dataclass
class Board:
    ats: str
    slug: str
    titles: list[str] = field(default_factory=list)
    title: str | None = None  # the posting's own title, when found
    website: str | None = None  # the company site the board names, when it does
    markers: tuple[str, ...] = ()  # strings that show up in a link to this board
    # (title, description) of every job, where the board gives descriptions:
    # a clone repeats both, while a big employer reuses only the title.
    bodies: list[tuple[str, str]] = field(default_factory=list)
    body: str | None = None  # the posting's own description


def _get(url: str, **kwargs):
    try:
        return requests.get(url, headers=UA, timeout=20, **kwargs)
    except requests.RequestException:
        return None


def _json(url: str):
    response = _get(url)
    if response is None or not response.ok:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def read_board(url: str) -> Board | None:
    """The board a posting URL belongs to, with every open job title on it."""
    parsed = urlparse(url)
    host, parts = parsed.netloc.lower(), [p for p in parsed.path.split("/") if p]

    if "greenhouse.io" in host and parts:
        slug = parts[0]
        eu = ".eu." in host
        api = f"https://boards-api{'.eu' if eu else ''}.greenhouse.io/v1/boards/{slug}"
        jobs = (_json(f"{api}/jobs?content=true") or {}).get("jobs", [])
        # A careers page often embeds the board by script: ...job_board/js?for=<slug>
        board = Board("greenhouse", slug, [j["title"] for j in jobs], markers=(f"greenhouse.io/{slug}", f"for={slug}"),
                      bodies=[(j["title"], j.get("content") or "") for j in jobs])
        if "jobs" in parts:
            job_id = parts[parts.index("jobs") + 1]
            own = next((j for j in jobs if str(j["id"]) == job_id), None)
            if own:
                board.title, board.body = own["title"], own.get("content") or ""
        return board

    if "lever.co" in host and parts:
        slug = parts[0]
        api = "https://api.eu.lever.co" if ".eu." in host else "https://api.lever.co"
        jobs = _json(f"{api}/v0/postings/{slug}?mode=json") or []
        board = Board("lever", slug, [j["text"] for j in jobs], markers=(f"lever.co/{slug}",),
                      bodies=[(j["text"], j.get("descriptionPlain") or "") for j in jobs])
        own = next((j for j in jobs if len(parts) > 1 and j["id"] == parts[1]), None)
        if own:
            board.title, board.body = own["text"], own.get("descriptionPlain") or ""
        return board

    if host == "ats.rippling.com" and parts:
        slug = parts[0]
        jobs = _json(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs") or []
        board = Board("rippling", slug, list(dict.fromkeys(j["name"] for j in jobs)), markers=(f"ats.rippling.com/{slug}",))
        own = next((j for j in jobs if len(parts) > 2 and j.get("uuid") == parts[2]), None)
        if own:
            board.title = own["name"]
        return board

    if "ashbyhq.com" in host and parts:
        slug = parts[0]
        jobs = (_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}") or {}).get("jobs", [])
        board = Board("ashby", slug, [j["title"] for j in jobs], markers=(f"ashbyhq.com/{slug}",),
                      bodies=[(j["title"], j.get("descriptionPlain") or "") for j in jobs])
        own = next((j for j in jobs if len(parts) > 1 and j.get("id") == parts[1]), None)
        if own:
            board.title, board.body = own["title"], own.get("descriptionPlain") or ""
        return board

    if host == "jobs.gem.com" and parts:
        slug = parts[0]
        jobs = _json(f"https://api.gem.com/job_board/v0/{slug}/job_posts/") or []
        board = Board("gem", slug, [j["title"] for j in jobs], markers=(f"jobs.gem.com/{slug}",),
                      bodies=[(j["title"], j.get("content") or "") for j in jobs])
        own = next((j for j in jobs if len(parts) > 1 and str(j["id"]) == parts[1]), None)
        if own:
            board.title, board.body = own["title"], own.get("content") or ""
        return board

    if host == "jobs.workable.com" and len(parts) > 1 and parts[0] == "view":
        job = _json(f"https://jobs.workable.com/api/v1/jobs/{parts[1]}") or {}
        company = job.get("company") or {}
        titles, token = [], None
        company_id = (company.get("url") or "").rstrip("/").split("/")[-2:-1]
        company_id = company_id[0] if company_id else None
        for _ in range(40):  # 40 pages is far past any real employer
            page = _json(f"https://jobs.workable.com/api/v1/companies/{company_id}"
                         + (f"?pageToken={token}" if token else "")) if company_id else None
            if not page:
                break
            titles += [j.get("title") for j in page.get("jobs", [])]
            token = page.get("nextPageToken")
            if not token:
                break
        return Board("workable", company.get("title") or "?", titles, job.get("title"),
                     company.get("website"), markers=("workable.com",))

    if host == "apply.workable.com" and parts:
        slug = parts[0]
        data = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}") or {}
        return Board("workable", slug, [j["title"] for j in data.get("jobs", [])],
                     markers=(f"workable.com/{slug}",))

    if host.endswith(".bamboohr.com"):
        slug = host.split(".")[0]
        jobs = (_json(f"https://{host}/careers/list") or {}).get("result", [])
        board = Board("bamboohr", slug, [j["jobOpeningName"] for j in jobs], markers=(f"{slug}.bamboohr.com",))
        if "careers" in parts and parts[-1].isdigit():
            board.title = next((j["jobOpeningName"] for j in jobs if j["id"] == parts[-1]), None)
        return board

    if host.endswith(".recruitee.com"):
        slug = host.split(".")[0]
        offers = (_json(f"https://{host}/api/offers") or {}).get("offers", [])
        return Board("recruitee", slug, [o["title"] for o in offers], markers=(host,))

    if host.endswith(".teamtailor.com") or "/jobs/" in parsed.path:
        rss = _get(f"https://{host}/jobs.rss")
        if rss is not None and rss.ok and "<rss" in rss.text:
            titles = re.findall(r"<item>.*?<title>(.*?)</title>", rss.text, re.S)
            return Board("teamtailor", host, titles, markers=(host,))
    return None


def domain_created(domain: str) -> date | None:
    """Registration date from RDAP, falling back to whois (some ccTLDs have no RDAP)."""
    data = _json(f"https://rdap.org/domain/{domain}")
    # A throttled or failed lookup can come back as the TLD's own record (.com: 1985); only
    # the domain's own record counts.
    if (data or {}).get("objectClassName") != "domain" or (data.get("ldhName") or "").lower() != domain.lower():
        data = None
    for event in (data or {}).get("events", []):
        if event.get("eventAction") == "registration":
            return date.fromisoformat(event["eventDate"][:10])
    try:
        text = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    # whois prints IANA's record for the TLD first (.com "created: 1985-01-01"); read only
    # what follows the domain's own record.
    own = re.search(rf"(?im)^\s*domain(?: name)?:\s*{re.escape(domain)}\s*$", text)
    if not own:
        return None
    text = text[own.start():]
    match = re.search(r"(?:Creation Date|Registration Date|Registered on|created|Registration Time)\s*:\s*"
                      r"(\d{4}-\d{2}-\d{2}|\d{2}[-./]\w{2,3}[-./]\d{4})", text, re.I)
    if not match:
        return None
    raw = match[1]
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def site_links_board(domain: str, board: Board) -> str | None:
    """The page of the company's site that links to the board, if one does."""
    for base in (f"https://www.{domain}", f"https://{domain}"):
        for path in CAREER_PATHS:
            response = _get(base + path)
            if response is not None and response.ok and any(m in response.text for m in board.markers):
                return base + path
    return None


def registrable(host: str) -> str:
    host = host.lower().removeprefix("www.")
    parts = host.split(".")
    # co.uk, com.au and the like keep three labels
    return ".".join(parts[-3:]) if len(parts) > 2 and parts[-2] in {"co", "com", "org", "net", "ac"} else ".".join(parts[-2:])


def vet(url: str, domain: str | None = None, today: date | None = None) -> tuple[list[str], list[str]]:
    """(facts, warnings) about a posting."""
    today = today or date.today()
    facts, warnings = [], []

    board = read_board(url)
    if board is None:
        warnings.append("job board not recognised: check the posting by hand")
    else:
        facts.append(f"board: {board.ats} '{board.slug}', {len(board.titles)} open jobs")
        if board.title:
            same_title = Counter(t.strip().lower() for t in board.titles)[board.title.strip().lower()]
            facts.append(f"this title on the board: {same_title}x ('{board.title}')")
            clones = same_title
            if board.body is not None:
                clones = sum(1 for t, b in board.bodies if t == board.title and b == board.body)
                if same_title > 1:
                    facts.append(f"of those, {clones} with the same description")
            if clones >= CLONES_WARN:
                warnings.append(f"the same advert is posted {clones} times (one per country?)")
        adverts = board.bodies or [(t.strip().lower(), "") for t in board.titles]
        repeated = sum(1 for n in Counter(adverts).values() if n >= CLONES_WARN)
        if adverts and repeated / max(1, len(set(adverts))) > 0.3:
            warnings.append(f"{repeated} titles are each cloned {CLONES_WARN}+ times across the board")
        if board.website and not domain:
            domain = registrable(urlparse(board.website if "//" in board.website else "//" + board.website).netloc)

    if not domain:
        warnings.append("company domain unknown: pass --domain")
        return facts, warnings

    created = domain_created(domain)
    if created is None:
        warnings.append(f"{domain}: registration date not found")
    else:
        age = (today - created).days
        facts.append(f"{domain} registered {created.isoformat()} ({age // 365}y {age % 365 // 30}m ago)")
        if age < YOUNG_DOMAIN_DAYS:
            warnings.append(f"{domain} is under {YOUNG_DOMAIN_DAYS // 365} years old")

    if board is not None:
        page = site_links_board(domain, board)
        if page:
            facts.append(f"{page} links to the board")
        else:
            warnings.append(f"no link from {domain} (home or careers page) to this board found")
    return facts, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the posting's URL on the company's job board")
    parser.add_argument("--domain", help="the company's own domain, e.g. medserv.ie")
    args = parser.parse_args(argv)

    facts, warnings = vet(args.url, args.domain)
    for fact in facts:
        print(f"  {fact}")
    for warning in warnings:
        print(f"  WARNING: {warning}")
    print("verdict: " + ("check the warnings before applying" if warnings else "nothing looks off"))
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
