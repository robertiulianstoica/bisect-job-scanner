"""Fill in the advert text (the details table) for jobs seen before it existed.

    .venv/bin/python -m scanner.backfill                 # everything missing
    .venv/bin/python -m scanner.backfill --workers 32 --linkedin-workers 3
    .venv/bin/python -m scanner.backfill --all-boards     # every job on every known board, into postings

Company boards are re-read through their APIs, many in parallel, and every
listed job already in `seen` gets its details. Other sites are read one page
per job: LinkedIn through its guest API (few workers: it rate-limits), the
rest through the page's JobPosting data. An advert taken down since it was
seen cannot be recovered; those are counted and left empty.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from jobspy import scrape_jobs
from scanner.run import BOARD_SITES, records
from scanner.settings import load_config
from scanner.state import State, boards_in, job_key

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def missing(state: State) -> list[tuple[str, str, str]]:
    return list(state.db.execute(
        "select job_key, site, url from seen where job_key not in (select job_key from details)"))


def clean(text: str | None) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", html.unescape(text))).strip()


def page_text(url: str) -> str | None:
    """One advert's text from its page: LinkedIn's guest API, else JobPosting JSON-LD."""
    if "linkedin.com" in url:
        match = re.search(r"(\d{6,})", url)
        if not match:
            return None
        response = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{match[1]}",
                                headers=HEADERS, timeout=30)
        if response.status_code == 429:
            raise RuntimeError("rate limited")
        body = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', response.text, re.S)
        return clean(body[1]) if body else None
    response = requests.get(url, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        return None
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', response.text, re.S):
        try:
            data = json.loads(html.unescape(block))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting" and item.get("description"):
                return clean(item["description"])
    return None


def from_boards(state: State, rows, workers: int) -> int:
    wanted = {key for key, _, _ in rows}
    boards: dict[str, set[str]] = {}
    for _, _, url in rows:
        for ats, slug in boards_in(url):
            if ats in BOARD_SITES:
                boards.setdefault(ats, set()).add(slug.lower())
    chunks = [(ats, sorted(slugs)[i:i + 8]) for ats, slugs in boards.items() for i in range(0, len(slugs), 8)]

    def read(chunk):
        ats, slugs = chunk
        try:
            return records(scrape_jobs(site_name=[ats], company_boards={ats: slugs}, results_wanted=100_000,
                                       description_format="plain", verbose=0))
        except Exception:
            return []

    saved = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for jobs in pool.map(read, chunks):
            for job in jobs:
                if job_key(job) in wanted:
                    state.save_details(job)
                    saved += 1
            state.commit()
    print(f"boards: {sum(len(s) for s in boards.values())} boards re-read, {saved} adverts recovered")
    return saved


def from_pages(state: State, rows, workers: int, label: str) -> int:
    def read(row):
        key, site, url = row
        for attempt in range(3):
            try:
                return key, page_text(url)
            except RuntimeError:
                time.sleep(20 * (attempt + 1))
            except requests.RequestException:
                return key, None
        return key, None

    saved = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, text in pool.map(read, rows):
            if text:
                state.save_details({"id": key, "description": text})
                saved += 1
                state.commit()  # short write: a scheduled run may be waiting on the database
    state.commit()
    print(f"{label}: {saved} of {len(rows)} adverts recovered")
    return saved


def all_boards(state: State, workers: int) -> None:
    """Read every known board now (instead of waiting for the cold rotation)
    and store every job on it in postings."""
    boards: dict[str, list[str]] = {}
    for ats, slug in state.db.execute("select ats, slug from boards"):
        if ats in BOARD_SITES:
            boards.setdefault(ats, []).append(slug)
    chunks = [(ats, slugs[i:i + 4]) for ats, slugs in boards.items() for i in range(0, len(slugs), 4)]

    def read(chunk):
        ats, slugs = chunk
        try:
            return records(scrape_jobs(site_name=[ats], company_boards={ats: slugs}, results_wanted=1_000_000,
                                       description_format="plain", verbose=0))
        except Exception:
            return []

    done = stored = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for jobs in pool.map(read, chunks):
            state.save_postings(jobs)
            done += 1
            stored += len(jobs)
            if done % 100 == 0:
                print(f"{done}/{len(chunks)} chunks, {stored} jobs read", flush=True)
    total = state.db.execute("select count(*) from postings").fetchone()[0]
    print(f"all boards: {sum(len(v) for v in boards.values())} boards, {stored} jobs read, {total} postings stored")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--linkedin-workers", type=int, default=3)
    parser.add_argument("--all-boards", action="store_true", help="store every job on every known board")
    args = parser.parse_args(argv)
    config = load_config()
    state = State(config["run"]["state_path"])
    if args.all_boards:
        all_boards(state, args.workers)
        return 0
    rows = missing(state)
    print(f"{len(rows)} seen jobs without their advert text")
    board_rows = [r for r in rows if any(ats in BOARD_SITES for ats, _ in boards_in(r[2]))]
    from_boards(state, board_rows, args.workers)
    rows = missing(state)
    linkedin = [r for r in rows if r[1] == "linkedin"]
    others = [r for r in rows if r[1] != "linkedin" and r[2] and r[2].startswith("http")]
    from_pages(state, others, args.workers // 2, "pages")
    from_pages(state, linkedin, args.linkedin_workers, "linkedin")
    left = len(missing(state))
    print(f"still without text: {left} (taken down since, or the page gives no text)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
