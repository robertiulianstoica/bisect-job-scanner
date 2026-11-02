"""Which skills the adverts keep asking for, and how often your CV names them.

Reads every advert the scanner emailed you since a date, and the text layer of
a CV PDF. For each skill in scanner/cvterms.py: the share of adverts that ask
for it, the share among the adverts you applied to, and how many times the CV
names it.

    python -m scanner.gap --cv cv.pdf                       # the last 30 days
    python -m scanner.gap --cv cv.pdf --since 2026-10-01 --grep "laravel|symfony"

--grep keeps only the adverts matching a regular expression: the part of the
market you apply in.

Read the result in two halves. A skill asked for often and named 0 times is
either experience missing from the CV (add it to your CV in Bisect, with
evidence) or a real gap (learn it, or keep stating it). A skill the CV names
only once or twice, deep in the PDF, is one an ATS ranks low.

For one job rather than the market: python -m scanner.ats <cv.pdf> --job <url>.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from scanner.ats import pdf_text
from scanner.cvterms import COMPILED, count


def adverts(db_path: str, since: str, grep: str | None = None) -> list[tuple[str, bool]]:
    """(advert text, applied) for every distinct advert emailed since a day."""
    db = sqlite3.connect(f"file:{Path(db_path).expanduser()}?mode=ro", uri=True)
    try:
        rows = db.execute(
            """select d.description, coalesce(t.verdict, '')
                 from seen s join details d on d.job_key = s.job_key
                 left join triage t on t.job_key = s.job_key
                where s.emailed = 1 and d.description is not null and s.first_seen >= ?""",
            (since,)).fetchall()
    finally:
        db.close()
    keep = re.compile(grep, re.I) if grep else None
    seen: set[str] = set()
    out = []
    for text, verdict in rows:
        if text[:500] in seen:  # the same advert is often posted once per country
            continue
        seen.add(text[:500])
        if keep and not keep.search(text):
            continue
        out.append((text, verdict == "applied"))
    return out


def gaps(ads: list[tuple[str, bool]], cv: str) -> list[tuple[float, float, str, int]]:
    """(share of adverts asking, share of applied ones asking, skill, times in CV), most asked first."""
    applied = [t for t, a in ads if a]
    stats = []
    for name, rx in COMPILED:
        n_all = sum(1 for t, _ in ads if rx.search(t))
        if not n_all:
            continue
        n_app = sum(1 for t in applied if rx.search(t))
        stats.append((n_all / len(ads), n_app / len(applied) if applied else 0.0, name, count(cv, name)))
    return sorted(stats, key=lambda s: (-s[0], -s[1], s[2]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cv", type=Path, required=True, help="the CV PDF (with Bisect: bisect_get_application_pdf)")
    parser.add_argument("--since", default=(date.today() - timedelta(days=30)).isoformat())
    parser.add_argument("--grep", help="only adverts matching this regular expression")
    parser.add_argument("--top", type=int, default=60)
    parser.add_argument("--config", help="default: $JOB_SCANNER_HOME/config.toml")
    args = parser.parse_args(argv)

    from scanner.settings import load_config
    cv = pdf_text(args.cv)
    ads = adverts(load_config(args.config)["run"]["state_path"], args.since, args.grep)
    if not ads:
        raise SystemExit(f"no adverts emailed since {args.since}" + (f" matching {args.grep}" if args.grep else ""))
    applied = sum(1 for _, a in ads if a)
    print(f"{len(ads)} distinct adverts since {args.since}{f' matching {args.grep}' if args.grep else ''}, "
          f"{applied} of them applied to. CV: {args.cv.name}\n")
    print(f"{'skill':32} {'adverts':>8} {'applied':>8} {'in CV':>6}")
    for share_all, share_app, name, in_cv in gaps(ads, cv)[: args.top]:
        flag = "  <- not in CV" if in_cv == 0 else ("  <- thin" if in_cv <= 2 else "")
        print(f"{name:32} {share_all:8.0%} {share_app:8.0%} {in_cv:6}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
