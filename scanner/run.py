"""One scan: read every source, keep what passes the rules, email what is new.

    python -m scanner.run                  # scan and email
    python -m scanner.run --dry-run        # scan and print, send nothing, remember nothing
    python -m scanner.run --add-board greenhouse cloudbeds
"""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from jobspy import scrape_jobs
from jobspy.ats import matches_search
from scanner import fit, metrics, notify
from scanner.rules import check_applicants, check_content, check_location
from scanner.settings import load_config, lock_path, placeholders
from scanner.state import State, boards_in, job_key, now

HERE = Path(__file__).resolve().parent

# Company boards, read one company at a time.
BOARD_SITES = ("greenhouse", "ashby", "lever", "personio", "recruitee", "smartrecruiters", "teamtailor", "gem", "workday", "workable", "rippling")
# Sources whose listings carry no posting date: their first read is a baseline.
UNDATED_SITES = {"bestjobs", "hipo"}  # hipo dates are its daily refresh
# Boards and searches spanning many companies, with the options each needs.
FEED_SITES = {
    "workable": {"is_remote": True},
    "welcome_to_the_jungle": {"is_remote": True},
    "larajobs": {},
    "symfony_jobs": {},
    "joburiit": {},
    "peviitor": {},
    "bestjobs": {},
    "ejobs": {},
    "nofluffjobs": {"is_remote": True},
    "djinni": {},
    "remote_rocketship": {},  # [remote_rocketship] location: its country page, e.g. "germany"
    "hacker_news": {},
    "devjob_ro": {},
    "phpjobs_ro": {},
    "hipo": {},
}


def records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    rows = df.to_dict(orient="records")
    for row in rows:
        for key, value in list(row.items()):
            if isinstance(value, float) and math.isnan(value):
                row[key] = None
    return rows


def board_query(search: dict) -> str:
    """The stack terms and the boards' extra terms, plus the role titles that
    count only in a job's title."""
    extra = [f'"{t}"' for t in search.get("board_terms", [])]
    titles = [f'title:"{t}"' for t in [*search.get("title_terms", []), *search.get("board_title_terms", [])]]
    return " OR ".join([search["terms"], *extra, *titles])


def collect(config: dict, boards: dict[str, list[str]], log, keep=None) -> list[dict]:
    """Jobs to screen. keep(jobs), when given, receives everything read, before
    any search filter: company boards are read whole, so every job on them is
    stored (postings), and only the matching ones go on to the rules."""
    search = config["search"]
    query = board_query(search)
    jobs: list[dict] = []
    keep = keep or (lambda found: None)

    board_sites = [ats for ats in BOARD_SITES if boards.get(ats)]
    if board_sites:
        everything = records(scrape_jobs(
            site_name=board_sites, search_term=None, company_boards=boards,
            results_wanted=1_000_000, description_format="plain", verbose=0,
        ))
        keep(everything)
        jobs += [j for j in everything if matches_search(query, j.get("title"), j.get("description"))]
        log(f"boards: {sum(len(v) for v in boards.values())} boards read, {len(everything)} jobs listed")

    # Boards that list many companies: one query each, filtered by age.
    for site, options in FEED_SITES.items():
        section = config.get(site, {})
        if not section.get("enabled"):
            continue
        if section.get("location"):  # per-source options from the config
            options = {**options, "location": section["location"]}
        try:
            found = records(scrape_jobs(
                site_name=[site], search_term=query, hours_old=section.get("hours_old", 24),
                results_wanted=200, description_format="plain", verbose=0, **options,
            ))
        except Exception as error:  # one broken source must not stop the others
            log(f"{site}: failed ({type(error).__name__}: {error})")
            continue
        log(f"{site}: {len(found)}")
        keep(found)
        jobs += found

    hima = config.get("himalayas", {})
    if hima.get("enabled"):
        found = records(scrape_jobs(
            site_name=["himalayas"], search_term=query, location=hima.get("country"),
            hours_old=hima.get("hours_old", 24), results_wanted=200, description_format="plain", verbose=0,
        ))
        log(f"himalayas: {len(found)}")
        keep(found)
        jobs += found

    linkedin = config.get("linkedin", {})
    if linkedin.get("enabled"):
        # Each search: a place, and optionally its own terms and result count.
        searches = linkedin.get("searches") or [{"location": place} for place in linkedin.get("locations", [])]
        for entry in searches:
            place = entry["location"]
            found = records(scrape_jobs(
                site_name=["linkedin"], search_term=entry.get("terms", search["terms"]), location=place, is_remote=True,
                hours_old=entry.get("hours_old", linkedin.get("hours_old", 24)),
                results_wanted=entry.get("results_wanted", linkedin.get("results_wanted", 25)),
                linkedin_fetch_description=True, description_format="plain", verbose=0,
            ))
            for job in found:
                # LinkedIn sometimes returns a card without a location; the
                # search itself was limited to this place and to remote.
                if not job.get("location"):
                    job["location"] = f"{place} (remote search)"
            log(f"linkedin {place} [{entry.get('terms', 'default terms')}]: {len(found)}")
            keep(found)
            jobs += found
    return jobs


def posted_recently(job: dict, hours: int) -> bool:
    posted = job.get("date_posted")
    if not posted:
        return True
    if isinstance(posted, str):
        try:
            posted = date.fromisoformat(posted[:10])
        except ValueError:
            return True
    if isinstance(posted, datetime):
        posted = posted.date()
    # Boards give a day, not a time: allow the whole first day.
    return posted >= (datetime.now() - timedelta(hours=hours)).date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="default: $JOB_SCANNER_HOME/config.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--add-board", nargs=2, metavar=("ATS", "SLUG"))
    parser.add_argument("--import-boards", metavar="JSON",
                        help='file of {"greenhouse": [slugs], ...}; added to the rotation, not read every run')
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    log = (lambda _msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))
    config = load_config(args.config, log)
    if unset := placeholders(config):
        print(f"edit these in your config first; they still hold the example's placeholders: {', '.join(unset)}",
              file=sys.stderr)
        return 1

    # A scan can outlast the half hour between runs; never run two at once.
    if not (args.add_board or args.import_boards):
        lock = open(lock_path(config["run"]["state_path"]), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another scan is still running; skipping this one")
            return 0
    state = State(config["run"]["state_path"])

    for ats, slugs in config.get("boards", {}).items():
        for slug in slugs:
            state.add_board(ats, slug, "config")
    if args.add_board:
        ats, slug = args.add_board
        print("added" if state.add_board(ats, slug, "manual") else "already known")
        state.commit()
        return 0
    if args.import_boards:
        import json
        added = sum(
            state.add_board(ats, slug, "import", tier="cold")
            for ats, slugs in json.loads(Path(args.import_boards).read_text()).items()
            for slug in slugs
        )
        state.commit()
        print(f"{added} boards added to the rotation; {state.board_counts()}")
        return 0
    state.commit()

    to_read = state.boards_to_read(config["run"].get("cold_boards_per_run", 250))
    read_started = now()
    listed: set[str] = set()

    def keep(found: list[dict]) -> None:
        state.save_postings(found)
        listed.update(j["source_board"] for j in found if j.get("source_board"))

    jobs = collect(config, to_read, log, keep=None if args.dry_run else keep)
    if not args.dry_run:
        state.mark_read(to_read)
        closed = state.close_missing(read_started, listed)
        log(f"{closed} postings no longer listed")

    # The same job can come back from two searches; keep the fuller copy.
    by_key: dict[str, dict] = {}
    for job in jobs:
        key = job_key(job)
        current = by_key.get(key)
        if current is None or sum(v is not None for v in job.values()) > sum(v is not None for v in current.values()):
            by_key[key] = job
    jobs = list(by_key.values())

    # An undated source read for the first time only sets the baseline: what
    # it lists now is remembered, not emailed.
    new_sources = ({job.get("site") for job in jobs} & UNDATED_SITES) - state.known_sites()

    fresh, discovered = [], 0
    baseline = config["run"].get("baseline_hours", 72)
    for job in jobs:
        for ats, slug in boards_in(job.get("job_url"), job.get("job_url_direct")):
            if not args.dry_run and state.add_board(ats, slug, job.get("site") or "?", promote_existing=False):
                discovered += 1
        key = job_key(job)
        if state.is_seen(key, job.get("job_url")):
            continue
        verdicts = [
            check_content(job, config["search"]),
            check_location(job, config["eligibility"]),
            check_applicants(job, config.get("linkedin", {}).get("max_applicants")),
        ]
        rejected = next((v for v in verdicts if not v.keep), None)
        recent = posted_recently(job, baseline) and job.get("site") not in new_sources
        job["flags"] = [f for v in verdicts for f in v.flags]
        if rejected or not recent:
            if not args.dry_run:
                reason = rejected.reason if rejected else (
                    "first read of this source" if job.get("site") in new_sources else "older than the baseline")
                state.mark_seen(job, emailed=False, reason=reason)
            continue
        fresh.append(job)

    # A board that produced a wanted job is read on every run from now on.
    # Wanted means emailed, and with a stated place you can work from:
    # "Remote" alone is too often US-only to justify reading the board
    # every half hour.
    promoted = {
        job["source_board"] for job in fresh
        if job.get("source_board") and "location unclear" not in job.get("flags", [])
    }
    if not args.dry_run:
        for board in promoted:
            ats, _, slug = board.partition(":")
            state.promote(ats, slug)

    # PHP and e-commerce roles first; TypeScript/Python ones after them.
    fresh.sort(key=lambda j: any(str(f).startswith("TypeScript/Python role") for f in j.get("flags") or []))
    log(f"{len(jobs)} collected, {len(fresh)} new and wanted, {discovered} boards discovered, "
        f"{sum(len(v) for v in to_read.values())} boards read ({state.board_counts()})")

    if args.dry_run:
        if fresh:
            fit.score_jobs(fresh, config, log)
            print(notify.render(fit.order(fresh))[1])
        return 0

    # Jobs wait in a queue until the next send hour, so a job that drops out
    # of a search before then is still emailed.
    queue_path = Path(config["run"]["state_path"]).expanduser().with_name("pending.json")
    queue = load_queue(queue_path)
    queued = {job_key(job): job for job in queue["jobs"] if not state.is_seen(job_key(job), job.get("job_url"))}
    pending = dict(queued)
    for job in fresh:
        key = job_key(job)
        if "coverage" in queued.get(key, {}):  # read when it was first queued: not paid for twice
            job["coverage"] = queued[key]["coverage"]
        pending[key] = job
    fit.score_jobs(list(pending.values()), config, log)
    batch = fit.order(list(pending.values()))

    at = datetime.now()
    send_hours = config["run"].get("send_hours")
    if send_hours:
        due = send_due(send_hours, queue["last_sent"], at)
    else:
        start, end = config["run"].get("active_hours", [0, 24])
        due = start <= at.hour < end

    sent = False
    if batch and due:
        email = config["email"]
        dsn, sender = os.environ.get(email["dsn_env"]), os.environ.get(email["from_env"])
        if not dsn or not sender:
            log(f"{email['dsn_env']} or {email['from_env']} is not set: nothing sent, jobs kept for the next run")
        else:
            subject, text, body = notify.render(batch)
            notify.send(dsn, sender, email["to"], subject, text, body)
            sent = True
            log(f"emailed {len(batch)} to {email['to']}")
    elif batch:
        log(f"{len(batch)} queued for the next send hour")
    # Jobs are only remembered once emailed, so a failed or out-of-hours
    # run leaves them in the queue.
    if sent:
        for job in batch:
            state.mark_seen(job, emailed=True)
    # A send hour with nothing to send still counts, so what turns up after it
    # waits for the next one.
    save_queue(queue_path, at if (sent or (due and not batch)) else queue["last_sent"], [] if sent else batch)
    state.touch([job_key(job) for job in jobs])
    metrics.record(state)
    state.commit()
    return 0


def send_due(send_hours: list[int], last_sent: datetime | None, at: datetime) -> bool:
    """Whether a send hour has passed since the last email."""
    slots = [datetime.combine(at.date() - timedelta(days=back), datetime.min.time()).replace(hour=hour)
             for back in (0, 1) for hour in send_hours]
    latest = max(slot for slot in slots if slot <= at)
    return last_sent is None or last_sent < latest


def load_queue(path: Path) -> dict:
    import json
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {"last_sent": None, "jobs": []}
    last = data.get("last_sent")
    return {"last_sent": datetime.fromisoformat(last) if last else None, "jobs": data.get("jobs") or []}


def save_queue(path: Path, last_sent: datetime | None, jobs: list[dict]) -> None:
    import json
    data = {"last_sent": last_sent.isoformat(timespec="seconds") if last_sent else None, "jobs": jobs}
    path.write_text(json.dumps(data, default=str))


if __name__ == "__main__":
    sys.exit(main())
