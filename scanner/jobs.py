"""What the scanner has found, from its state database.

    python -m scanner.jobs                  # jobs emailed in the last 3 days
    python -m scanner.jobs --days 7 --grep laravel
    python -m scanner.jobs --rejected       # what the rules turned down, and why
    python -m scanner.jobs --untriaged      # emailed, not yet given a verdict (scanner.triage)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from scanner.settings import load_config
from scanner.state import State


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="default: $JOB_SCANNER_HOME/config.toml")
    parser.add_argument("--days", type=float, default=3)
    parser.add_argument("--grep", help="only titles or companies containing this")
    parser.add_argument("--rejected", action="store_true", help="show turned-down jobs with the reason")
    parser.add_argument("--untriaged", action="store_true", help="only emailed jobs without a verdict yet")
    args = parser.parse_args(argv)

    state = State(load_config(args.config)["run"]["state_path"])
    state.db.row_factory = sqlite3.Row
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat(timespec="seconds")
    query = ("select s.*, t.verdict, t.reason as verdict_reason from seen s left join triage t using (job_key)"
             " where first_seen >= ? and emailed = ?")
    params: list = [since, 0 if args.rejected else 1]
    if args.grep:
        query += " and (title like ? or company like ?)"
        params += [f"%{args.grep}%", f"%{args.grep}%"]
    if args.untriaged:
        query += " and t.verdict is null"
    rows = list(state.db.execute(query + " order by first_seen desc", params))
    for row in rows:
        facts = [row["site"], row["location"] or "location not stated"]
        if row["posted"]:
            facts.append(f"posted {row['posted'][:10]}")
        if row["applicants"] is not None:
            facts.append(f"{row['applicants']} applicants")
        if row["flags"]:
            facts.append(row["flags"])
        print(f"{row['first_seen'][:16].replace('T', ' ')}  {row['title']} at {row['company']}")
        print(f"    {' · '.join(str(f) for f in facts)}")
        if args.rejected:
            print(f"    rejected: {row['reason'] or '?'}")
        if row["verdict"]:
            print(f"    [{row['verdict']}] {row['verdict_reason'] or ''}".rstrip())
        print(f"    {row['url']}")
    print(f"{len(rows)} job(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
