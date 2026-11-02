"""Who the hiring companies are, and how long they have been around.

    .venv/bin/python -m scanner.companies --enrich        # look up companies not yet looked up
    .venv/bin/python -m scanner.companies --enrich --all  # look them all up again
    .venv/bin/python -m scanner.companies --guess-sites   # find the site of companies still without one

One row per company board. The founding year comes from Wikidata when the
company is there (matched by its website where we know it), else from the
registration date of its own domain, which is a floor, not the truth (an
old domain can be bought by a young company, and rebrands move domains).
The website comes from Ashby's organisation data, the Greenhouse board's
own page, or the domain in the company's job links.
"""

from __future__ import annotations

import argparse
import html
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from scanner.settings import load_config
from scanner.state import State
from scanner.vet import domain_created, registrable

# Wikidata classes that mean "a company" (business, company, enterprise, public company,
# software company, technology company, corporation, startup, subsidiary, bank, privately held company).
COMPANY_CLASSES = {"Q4830453", "Q783794", "Q6881511", "Q891723", "Q1058914", "Q18388277", "Q167037",
                   "Q21980538", "Q658255", "Q22687", "Q1589009", "Q17377208", "Q2005696", "Q1631111"}
# A contact address is added from [profile] contact, so a site can say if it minds.
HEADERS = {"User-Agent": "job-scanner/1.0 (personal research)"}
NOT_SITES = re.compile(r"greenhouse|ashbyhq|lever\.co|linkedin|twitter|x\.com|facebook|instagram|youtube|glassdoor|"
                       r"tiktok|medium\.com|github\.com|wikipedia|apple\.com/app|google\.com|bit\.ly|vimeo|"
                       r"myworkdayjobs|smartrecruiters|workable|teamtailor|recruitee|personio|rippling|eeoc\.gov|dol\.gov", re.I)
ATS_HOSTS = re.compile(r"greenhouse\.io|rippling\.com|ashbyhq\.com|lever\.co|myworkdayjobs|smartrecruiters|workable|teamtailor|"
                       r"recruitee|personio|linkedin|himalayas|dover\.com|gem\.com|bamboohr", re.I)

SCHEMA = """
create table if not exists companies (
    board text primary key,      -- ats:slug, as in postings.source_board
    name text,
    website text,
    domain text,
    domain_created text,         -- RDAP registration date
    wikidata text,               -- Q-id when matched
    founded integer,             -- year
    founded_source text,         -- wikidata or domain
    checked_at text
)
"""


def _get(url: str, timeout: int = 20, **kwargs):
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
        return response if response.status_code == 200 else None
    except requests.RequestException:
        return None


def _tokens(*names: str) -> set[str]:
    return {t for n in names for t in re.split(r"[^a-z0-9]+", (n or "").lower()) if len(t) >= 3}


def _plausible(url: str, name: str, slug: str) -> bool:
    """A site whose domain carries the company's name or board slug."""
    domain = registrable(urlparse(url).hostname or "")
    label = domain.split(".")[0]
    return any(t in label for t in _tokens(name, slug)) or label in re.sub(r"[^a-z0-9]", "", (name or "").lower())


def website_for(board: str, job_hosts: set[str], name: str = "") -> str | None:
    ats, slug = board.split(":", 1)
    if ats == "ashby":
        try:
            r = requests.post(
                "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiOrganizationFromHostedJobsPageName",
                json={"operationName": "ApiOrganizationFromHostedJobsPageName",
                      "variables": {"organizationHostedJobsPageName": slug, "searchContext": "JobBoard"},
                      "query": "query ApiOrganizationFromHostedJobsPageName($organizationHostedJobsPageName: String!,"
                               " $searchContext: OrganizationSearchContext) { organization:"
                               " organizationFromHostedJobsPageName(organizationHostedJobsPageName:"
                               " $organizationHostedJobsPageName, searchContext: $searchContext) { publicWebsite } }"},
                headers=HEADERS, timeout=20)
            site = ((r.json().get("data") or {}).get("organization") or {}).get("publicWebsite")
            if site:
                return site
        except (requests.RequestException, ValueError):
            pass
    if ats == "greenhouse":
        r = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        if r is not None:
            content = html.unescape((r.json() or {}).get("content") or "")
            for href in re.findall(r'href="(https?://[^"]+)"', content):
                if not NOT_SITES.search(href) and _plausible(href, name, slug):
                    return href
    own = sorted(h for h in job_hosts if not ATS_HOSTS.search(h) and _plausible(f"https://{h}", name, slug))
    return f"https://{own[0]}" if own else None


def wikidata_for(name: str, domain: str | None) -> tuple[str, int] | None:
    """(Q-id, founding year) of the company called `name`; when its domain is
    known, only an entity whose official website has that domain counts."""
    r = _get("https://www.wikidata.org/w/api.php",
             params={"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 5})
    ids = [hit["id"] for hit in (r.json().get("search", []) if r is not None else [])]
    if not ids:
        return None
    r = _get("https://www.wikidata.org/w/api.php",
             params={"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|descriptions",
                     "languages": "en", "format": "json"})
    entities = (r.json().get("entities", {}) if r is not None else {})
    for qid in ids:
        entity = entities.get(qid) or {}
        claims = entity.get("claims", {})
        founded = next((c["mainsnak"]["datavalue"]["value"]["time"] for c in claims.get("P571", [])
                        if c["mainsnak"].get("datavalue")), None)
        if not founded:
            continue
        sites = [c["mainsnak"]["datavalue"]["value"] for c in claims.get("P856", []) if c["mainsnak"].get("datavalue")]
        site_domains = {registrable(urlparse(s).hostname or "") for s in sites}
        label = ((entity.get("labels") or {}).get("en") or {}).get("value", "")
        classes = {c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get("P31", []) if c["mainsnak"].get("datavalue")}
        if domain and domain in site_domains:
            return qid, int(founded[1:5])  # its own website: certain
        if label.lower() == name.lower() and classes & COMPANY_CLASSES and not (domain and site_domains):
            return qid, int(founded[1:5])  # same name, a company, and no website that contradicts it
    return None


TLDS = ("com", "io", "ai", "co", "app")
BOARD_SUFFIXES = re.compile(r"(careers?|jobs|hiring|inc|hq|team|global|group|labs?|technologies|tech)$")


def _markers(board: str) -> tuple[str, ...]:
    ats, slug = board.split(":", 1)
    slug = slug.lower()
    return {"greenhouse": (f"greenhouse.io/{slug}", f"for={slug}"), "ashby": (f"ashbyhq.com/{slug}",),
            "lever": (f"lever.co/{slug}",)}.get(ats, (slug,))


def _candidates(board: str, name: str) -> list[str]:
    slug = board.split(":", 1)[1].lower()
    bases = {re.sub(r"[^a-z0-9-]", "", slug), re.sub(r"[^a-z0-9]", "", slug),
             re.sub(r"[^a-z0-9]", "", (name or "").lower()), BOARD_SUFFIXES.sub("", re.sub(r"[^a-z0-9]", "", slug))}
    bases = sorted((b for b in bases if len(b) >= 3), key=lambda b: (b != re.sub(r"[^a-z0-9]", "", slug), b))
    return [f"{b}.{tld}" for b in bases for tld in TLDS]


def _resolves(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, 443)
        return True
    except OSError:
        return False


def links_to_board(domain: str, board: str, name: str = "", by_title: bool = False) -> bool:
    """The site points at this board (home page, a careers page it links to, or
    /careers, /jobs); failing that, for names of five letters or more, the home
    page's title carries the company's name (boards loaded by script leave no link)."""
    markers = _markers(board)
    for base in (f"https://{domain}", f"https://www.{domain}"):
        home = _get(base, timeout=8)
        if home is None:
            continue
        page = home.text
        if any(m in page for m in markers):
            return True
        for path in ("/careers", "/jobs"):
            extra = _get(base + path, timeout=8)
            if extra is not None and any(m in extra.text for m in markers):
                return True
        links = re.findall(r'href="((?:https?://[^"]*?)?/[^"]*(?:career|jobs|join|work-with-us)[^"]*)"', page, re.I)
        for link in list(dict.fromkeys(links))[:2]:
            url = link if link.startswith("http") else base + link
            if registrable(urlparse(url).hostname or "") != domain and not ATS_HOSTS.search(url):
                continue
            if ATS_HOSTS.search(url):
                if any(m in url for m in markers):
                    return True
                continue
            careers = _get(url, timeout=8)
            if careers is not None and any(m in careers.text for m in markers):
                return True
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        compact = re.sub(r"[^a-z0-9]", "", (name or "").lower())
        if by_title and title and len(compact) >= 6 and compact in re.sub(r"[^a-z0-9]", "", html.unescape(title[1]).lower()):
            return True
        return False
    return False


def guess_site(board: str, name: str) -> str | None:
    """A candidate domain that links to the board; failing that, the .com whose
    home page title carries the company's name."""
    live = [d for d in _candidates(board, name) if _resolves(d)]
    for domain in live:
        if links_to_board(domain, board, name):
            return f"https://{domain}"
    for domain in live:
        if domain.endswith(".com") and links_to_board(domain, board, name, by_title=True):
            return f"https://{domain}"
    return None


def guess_sites(state: State, workers: int = 8) -> int:
    """For companies still without a website: retry Ashby's own field, else try
    name-based domains and keep one only if it links to the company's board.
    Then date the domain and look the company up in Wikidata by it."""
    state.db.execute(SCHEMA)
    todo = list(state.db.execute("select board, name from companies where website is null"))

    def one(row):
        board, name = row
        site = website_for(board, set(), name) if board.startswith("ashby:") else None
        site = site or guess_site(board, name)
        if not site:
            return board, None
        domain = registrable(urlparse(site).hostname or "")
        wiki = wikidata_for(name, domain) if name else None
        created = domain_created(domain)
        return board, (site, domain, created.isoformat() if created else None, wiki[0] if wiki else None,
                       wiki[1] if wiki else (created.year if created else None),
                       "wikidata" if wiki else ("domain" if created else None))

    found = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (board, result) in enumerate(pool.map(one, todo), 1):
            if result:
                found += 1
                site, domain, created, qid, founded, source = result
                state.db.execute(
                    "update companies set website=?, domain=?, domain_created=?, wikidata=coalesce(?, wikidata),"
                    " founded=case when founded_source = 'wikidata' then founded else ? end,"
                    " founded_source=case when founded_source = 'wikidata' then founded_source else ? end,"
                    " checked_at=? where board=?",
                    (site, domain, created, qid, founded, source, datetime.now(timezone.utc).isoformat(timespec="seconds"), board))
                state.db.commit()
            if i % 100 == 0:
                print(f"{i}/{len(todo)} checked, {found} sites found", flush=True)
    return found


def enrich_one(board: str, name: str, hosts: set[str]) -> tuple:
    website = website_for(board, hosts, name)
    host = (urlparse(website).hostname or "").lower() if website else ""
    domain = registrable(host) if host else None
    wiki = wikidata_for(name, domain) if name else None
    created = domain_created(domain) if domain else None
    if wiki:
        founded, source = wiki[1], "wikidata"
    elif created:
        founded, source = created.year, "domain"
    else:
        founded, source = None, None
    return (board, name, website, domain, created.isoformat() if created else None, wiki[0] if wiki else None,
            founded, source, datetime.now(timezone.utc).isoformat(timespec="seconds"))


def enrich(state: State, again: bool = False, workers: int = 12) -> int:
    state.db.execute(SCHEMA)
    hosts: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for board, company, url in state.db.execute(
            "select source_board, company, url from postings where source_board is not null"):
        names.setdefault(board, company)
        host = (urlparse(url or "").hostname or "").lower()
        if host:
            hosts.setdefault(board, set()).add(host)
    done = set() if again else {b for (b,) in state.db.execute("select board from companies")}
    todo = [b for b in names if b not in done]
    count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(lambda b: enrich_one(b, names[b], hosts.get(b, set())), todo):
            state.db.execute("insert or replace into companies values (?,?,?,?,?,?,?,?,?)", row)
            state.db.commit()  # short writes: a scheduled scan may be waiting on the database
            count += 1
            if count % 100 == 0:
                print(f"{count}/{len(todo)} companies looked up", flush=True)
    state.db.commit()
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--enrich", action="store_true")
    parser.add_argument("--all", action="store_true", help="look up companies already looked up, again")
    parser.add_argument("--guess-sites", action="store_true", help="find sites for companies without one")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args(argv)
    config = load_config()
    if contact := config.get("profile", {}).get("contact"):
        HEADERS["User-Agent"] = f"job-scanner/1.0 (personal research; {contact})"
    state = State(config["run"]["state_path"])
    if args.guess_sites:
        print(f"{guess_sites(state, args.workers)} sites found")
        for row in state.db.execute("select founded_source, count(*) from companies group by 1"):
            print(row)
    if args.enrich:
        print(f"{enrich(state, args.all, args.workers)} companies looked up")
        for row in state.db.execute("select founded_source, count(*) from companies group by 1"):
            print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
