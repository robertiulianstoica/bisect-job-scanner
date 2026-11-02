"""Your verdict on each job worth a look, kept with the scanner's state.

The scanner's rules decide what is emailed; this records what was decided
after reading the advert, so the list survives the conversation it was made in.

    python -m scanner.triage list                         # shortlist, maybe, later
    python -m scanner.triage list --all                   # every verdict, out and applied included
    python -m scanner.triage set "Jimdo AI" shortlist "TypeScript AI role, remote-first"
    python -m scanner.triage set <url> applied --bisect <application id>
    python -m scanner.triage add --title T --company C --url U [--location L]   # a job found by hand
    python -m scanner.triage check                        # are shortlisted, maybe and applied jobs still open?
    python -m scanner.triage funnel --days 7              # per day: jobs found, and how many were worth a look

A job is named by its URL, its key in the database, or words that appear in
its company and title; the words must match exactly one job.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys

from scanner.settings import load_config
from scanner.state import VERDICTS, State


TRACKING = re.compile(r"(utm\w*|ref|refId|trk\w*|source|src|gh_src|lever-source\w*|trackingId)=", re.I)


def find_job(state: State, ref: str) -> sqlite3.Row:
    """The one job a reference names, or SystemExit listing the candidates."""
    rows = list(state.db.execute("select * from seen where job_key = ? or url = ?", (ref, ref)))
    if not rows and "?" in ref:  # the same URL with tracking parameters added or dropped
        base, _, query = ref.partition("?")
        kept = [p for p in query.split("&") if p and not TRACKING.match(p)]
        # A query that names the job (?gh_jid=123) must still match exactly.
        if not kept:
            rows = list(state.db.execute("select * from seen where url = ? or url like ?", (base, base + "?%")))
    if not rows:
        words = ref.lower().split()
        rows = [r for r in state.db.execute("select * from seen order by first_seen desc")
                if all(w in f"{r['company']} {r['title']}".lower() for w in words)]
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise SystemExit(f"no job matches {ref!r}; add it first with: triage add --title --company --url")
    listing = "\n".join(f"  {r['company']} | {r['title']} | {r['first_seen'][:10]} | {r['url']}" for r in rows[:15])
    raise SystemExit(f"{len(rows)} jobs match {ref!r}; be more specific or use the URL:\n{listing}")


def show(rows) -> None:
    for row in rows:
        when = (row["decided_at"] or "")[:10]
        extra = f" · Bisect {row['bisect_id']}" if row["bisect_id"] else ""
        print(f"[{row['verdict']}] {row['company']} | {row['title']}  ({when}{extra})")
        if row["verdict_reason"]:
            print(f"    {row['verdict_reason']}")
        print(f"    {row['location'] or 'location not stated'} · {row['url']}")


CLOSED_TEXT = ("no longer accepting applications", "this job is no longer available", "position has been filled",
               "job you are looking for is no longer", "this position is closed", "job not found", "no longer open")


def still_open(state: State, key: str, url: str) -> str:
    """'open', 'closed' or 'unknown': the board's own record when the job is on a
    board the scanner reads, else the advert's page."""
    row = state.db.execute("select closed_at, source_board from postings where job_key = ?", (key,)).fetchone()
    if row and row[1]:
        return f"closed {row[0][:10]}" if row[0] else "open"
    import re
    import requests

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
    target = url
    match = re.search(r"linkedin\.com/jobs/view/(\d+)", url or "")
    if match:
        target = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{match[1]}"
    try:
        response = requests.get(target, headers=headers, timeout=20, allow_redirects=True)
    except requests.RequestException:
        return "unknown"
    if response.status_code in (404, 410):
        return "closed"
    if response.status_code != 200:
        return "unknown"
    page = response.text.lower()
    return "closed" if any(t in page for t in CLOSED_TEXT) else "open"


RELEVANT = ("shortlist", "maybe", "applied")


def funnel(state: State, day: str | None = None, days: int = 1) -> list[tuple[str, int, int]]:
    """Per local day, the top of the job-search funnel (Bisect's bisect_record_job_scan):
    postings first read that day, and how many of those jobs got a verdict worth
    a look. A verdict counts on the day its job was found, so a later verdict
    changes an earlier day."""
    if day:
        since, until = day, day
    else:
        until = state.db.execute("select date('now', 'localtime')").fetchone()[0]
        since = state.db.execute("select date(?, ?)", (until, f"-{days - 1} days")).fetchone()[0]
    # Jobs added by hand (triage add) are in seen only; they count as found too.
    found = dict(state.db.execute(
        "select date(first_seen, 'localtime') d, count(*) from ("
        "  select first_seen from postings"
        "  union all select first_seen from seen where job_key not in (select job_key from postings))"
        " where date(first_seen, 'localtime') between ? and ? group by d", (since, until)))
    relevant = dict(state.db.execute(
        "select date(s.first_seen, 'localtime') d, count(*) from triage t join seen s using (job_key)"
        f" where t.verdict in ({','.join('?' * len(RELEVANT))}) and date(s.first_seen, 'localtime') between ? and ?"
        " group by d", (*RELEVANT, since, until)))
    out, current = [], since
    while current <= until:
        out.append((current, found.get(current, 0), relevant.get(current, 0)))
        current = state.db.execute("select date(?, '+1 day')", (current,)).fetchone()[0]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="default: $JOB_SCANNER_HOME/config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("list", help="the current list")
    ls.add_argument("--all", action="store_true", help="include out and applied")
    ls.add_argument("--verdict", choices=VERDICTS)

    st = sub.add_parser("set", help="record a verdict")
    st.add_argument("job", help="URL, job key, or words from company and title")
    st.add_argument("verdict", choices=VERDICTS)
    st.add_argument("reason", nargs="?")
    st.add_argument("--bisect", help="the application's id in your own tracker, for applied")

    ad = sub.add_parser("add", help="a job found outside the scanner")
    ad.add_argument("--title", required=True)
    ad.add_argument("--company", required=True)
    ad.add_argument("--url", required=True)
    ad.add_argument("--location")

    fn = sub.add_parser("funnel", help="per day: jobs found and how many got shortlist, maybe or applied")
    fn.add_argument("--day", help="one day, as 2026-11-01 (default: the last --days days)")
    fn.add_argument("--days", type=int, default=1)

    ck = sub.add_parser("check", help="whether shortlisted, maybe and applied jobs are still open")
    ck.add_argument("--verdict", choices=VERDICTS, action="append")

    args = parser.parse_args(argv)
    state = State(load_config(args.config)["run"]["state_path"])
    state.db.row_factory = sqlite3.Row

    if args.command == "add":
        known = state.db.execute("select job_key from seen where url = ?", (args.url,)).fetchone()
        if known:  # a board or feed already brought it: verdicts go on that row
            print(f"already known: {known[0]}")
            return 0
        key = state.add_manual_job(args.title, args.company, args.url, args.location)
        state.commit()
        print(f"added: {key}")
        return 0

    if args.command == "set":
        job = find_job(state, args.job)
        state.set_triage(job["job_key"], args.verdict, args.reason, args.bisect)
        state.commit()
        print(f"[{args.verdict}] {job['company']} | {job['title']}")
        return 0

    if args.command == "funnel":
        for day, found, relevant in funnel(state, args.day, args.days):
            print(f"{day} found {found} relevant {relevant}")
        return 0

    if args.command == "check":
        wanted = args.verdict or ["shortlist", "maybe", "applied"]
        rows = list(state.db.execute(
            "select s.job_key, s.company, s.title, s.url, t.verdict from triage t join seen s using (job_key)"
            f" where t.verdict in ({','.join('?' * len(wanted))}) order by t.verdict, t.decided_at desc", wanted))
        for row in rows:
            status = still_open(state, row["job_key"], row["url"])
            print(f"{status:18} [{row['verdict']}] {row['company']} | {row['title']}")
        return 0

    verdicts = [args.verdict] if args.verdict else (list(VERDICTS) if args.all else ["shortlist", "maybe", "later"])
    order = " ".join(f"when '{v}' then {i}" for i, v in enumerate(VERDICTS))
    rows = list(state.db.execute(
        "select s.*, t.verdict, t.reason as verdict_reason, t.decided_at, t.bisect_id from triage t join seen s using (job_key)"
        f" where t.verdict in ({','.join('?' * len(verdicts))})"
        f" order by case t.verdict {order} end, t.decided_at desc", verdicts))
    show(rows)
    print(f"{len(rows)} job(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
