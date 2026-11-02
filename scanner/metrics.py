"""Daily market metrics from the stored postings, and the snapshot the
dashboard is built from.

    .venv/bin/python -m scanner.metrics --record           # today's row (each scan does this)
    .venv/bin/python -m scanner.metrics --export out.json  # data for the dashboard
    .venv/bin/python -m scanner.metrics --dashboard out.html  # the dashboard page, data embedded

Counted: engineering postings only, by main language and region (global, EU,
US). "Open" is a posting still listed in the last day. Pay is stored as each
advert states it; here it is turned into yearly EUR (scanner/salary.py) to
compare, which is the only place that conversion happens.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scanner.salary import yearly_eur
from scanner.settings import load_config
from scanner.state import State

REGIONS = ("global", "EU", "US")
BANDS = [(0, 40_000), (40_000, 60_000), (60_000, 80_000), (80_000, 100_000), (100_000, 130_000),
         (130_000, 160_000), (160_000, 200_000), (200_000, 10**9)]

SCHEMA = """
create table if not exists market_daily (
    day text, region text, language text,
    open_jobs integer, new_jobs integer, with_pay integer,
    min_p50 real, max_p50 real, mid_p25 real, mid_p50 real, mid_p75 real,
    primary key (day, region, language)
)
"""


def _open_rows(state: State):
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    return list(state.db.execute(
        "select language, region, pay_min, pay_max, pay_currency, pay_period, posted from postings"
        " where engineering = 1 and language is not null and closed_at is null and last_seen >= ?", (since,)))


def _yearly(row) -> tuple[float, float] | None:
    low, high, currency, period = row[2], row[3], row[4], row[5]
    if not currency or (low is None and high is None):
        return None
    return yearly_eur(low if low is not None else high, high if high is not None else low, currency, period)


def _stats(rows) -> dict:
    pays = [p for p in (_yearly(r) for r in rows) if p]
    out = {"open_jobs": len(rows), "with_pay": len(pays)}
    if pays:
        mids = sorted((lo + hi) / 2 for lo, hi in pays)
        q = statistics.quantiles(mids, n=4) if len(mids) >= 4 else [mids[0], statistics.median(mids), mids[-1]]
        out.update(min_p50=statistics.median(lo for lo, _ in pays), max_p50=statistics.median(hi for _, hi in pays),
                   mid_p25=q[0], mid_p50=statistics.median(mids), mid_p75=q[-1],
                   bands=[sum(1 for m in mids if a <= m < b) for a, b in BANDS])
    return out


def _groups(rows):
    groups = defaultdict(list)
    for row in rows:
        for reg in ("global", row[1]):
            if reg in REGIONS:
                groups[(reg, row[0])].append(row)
                groups[(reg, "all")].append(row)
    return groups


def record(state: State) -> None:
    """Today's row per region and language (rewritten by each scan that day)."""
    state.db.execute(SCHEMA)
    today = date.today().isoformat()
    rows = _open_rows(state)
    new_today = defaultdict(int)
    for row in rows:
        if row[6] == today:
            for reg in ("global", row[1]):
                new_today[(reg, row[0])] += 1
                new_today[(reg, "all")] += 1
    for (reg, language), group in _groups(rows).items():
        s = _stats(group)
        state.db.execute(
            "insert or replace into market_daily values (?,?,?,?,?,?,?,?,?,?,?)",
            (today, reg, language, s["open_jobs"], new_today[(reg, language)], s["with_pay"], s.get("min_p50"),
             s.get("max_p50"), s.get("mid_p25"), s.get("mid_p50"), s.get("mid_p75")))
    state.db.commit()


COHORTS = [("under 3 years", 0, 3), ("3–5 years", 3, 6), ("6–10 years", 6, 11), ("11–20 years", 11, 21),
           ("over 20 years", 21, 1000)]


def companies_by_age(state: State) -> dict:
    """Per region: hiring by company age (founding year from scanner/companies.py)."""
    if not state.db.execute("select 1 from sqlite_master where name = 'companies'").fetchone():
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    year = date.today().year
    rows = list(state.db.execute(
        "select p.source_board, coalesce(c.name, p.company), c.founded, c.founded_source, p.language, p.region,"
        " p.pay_min, p.pay_max, p.pay_currency, p.pay_period"
        " from postings p left join companies c on c.board = p.source_board"
        " where p.engineering = 1 and p.language is not null and p.last_seen >= ? and p.source_board is not null",
        (since,)))
    out = {}
    for reg in REGIONS:
        mine = [r for r in rows if reg == "global" or r[5] == reg]
        cohorts = []
        for label, low, high in COHORTS + [("unknown", None, None)]:
            group = [r for r in mine if (r[2] is None if low is None else r[2] is not None and low <= year - r[2] < high)]
            pays = [p for p in (_yearly((None, None, r[6], r[7], r[8], r[9])) for r in group) if p]
            companies = {r[0] for r in group}
            langs = defaultdict(int)
            for r in group:
                langs[r[4]] += 1
            cohorts.append({
                "label": label, "companies": len(companies), "open_jobs": len(group),
                "jobs_per_company": round(len(group) / len(companies), 1) if companies else None,
                "with_pay": len(pays), "mid_p50": statistics.median((lo + hi) / 2 for lo, hi in pays) if pays else None,
                "languages": {l: round(100 * n / len(group), 1) for l, n in langs.items()} if group else {},
            })
        per_company = defaultdict(list)
        for r in mine:
            per_company[(r[0], r[1], r[2], r[3])].append(r)
        top = sorted(per_company.items(), key=lambda kv: -len(kv[1]))[:20]
        out[reg] = {"cohorts": cohorts, "top": [
            {"name": name, "founded": founded, "source": source, "open_jobs": len(group),
             "mid_p50": (lambda p: statistics.median((lo + hi) / 2 for lo, hi in p) if p else None)(
                 [p for p in (_yearly((None, None, r[6], r[7], r[8], r[9])) for r in group) if p]),
             "main_language": max(set(r[4] for r in group), key=[r[4] for r in group].count)}
            for (_, name, founded, source), group in top]}
    known = state.db.execute("select count(*), sum(founded is not null), sum(founded_source = 'wikidata')"
                             " from companies").fetchone()
    out["coverage"] = {"companies": known[0], "with_founding_year": known[1], "from_wikidata": known[2]}
    return out


AI_KINDS = ("builds", "uses", "none")


def ai_work(state: State, days: int = 120) -> dict:
    """Per region: open engineering jobs that build AI, that work with AI tools,
    and neither; their pay, their languages, and new postings per day."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    rows = list(state.db.execute(
        "select coalesce(ai, 'none'), region, language, pay_min, pay_max, pay_currency, pay_period from postings"
        " where engineering = 1 and last_seen >= ?", (since,)))
    start = (date.today() - timedelta(days=days)).isoformat()
    daily = list(state.db.execute(
        "select coalesce(ai, 'none'), region, posted, count(*) from postings where engineering = 1"
        " and posted >= ? and posted <= ? group by 1, 2, 3", (start, date.today().isoformat())))
    out = {}
    for reg in REGIONS:
        mine = [r for r in rows if reg == "global" or r[1] == reg]
        current = {}
        for kind in AI_KINDS:
            group = [r for r in mine if r[0] == kind]
            pays = [p for p in (_yearly((None, None, r[3], r[4], r[5], r[6])) for r in group) if p]
            langs = defaultdict(int)
            for r in group:
                if r[2]:
                    langs[r[2]] += 1
            current[kind] = {"open_jobs": len(group), "with_pay": len(pays),
                             "mid_p50": statistics.median((lo + hi) / 2 for lo, hi in pays) if pays else None,
                             "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1]))}
        per_day = defaultdict(lambda: defaultdict(int))
        for kind, region_, day, count in daily:
            if reg == "global" or region_ == reg:
                per_day[kind][day] += count
        out[reg] = {"current": current, "new_by_day": {k: sorted(v.items()) for k, v in per_day.items()}}
    return out


CLONE_FARM_MIN = 50       # open postings at one company
CLONE_SHARE = 0.8         # of them sharing their text with at least two others


def scams(state: State) -> dict:
    """Suspicious postings: scam signals in the text, or a clone farm (a company
    under two years old by its domain, most of whose many adverts are copies);
    plus the share warning about recruitment fraud. Market data only: nothing
    from your own verdicts or applications goes into the dashboard."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    young = {b for (b,) in state.db.execute(
        "select board from companies where domain_created >= date('now', '-2 years')")} \
        if state.db.execute("select 1 from sqlite_master where name = 'companies'").fetchone() else set()
    rows = list(state.db.execute(
        "select source_board, company, site, region, scam_signals, fraud_warning, text_hash from postings"
        " where last_seen >= ?", (since,)))
    by_company = defaultdict(list)
    for r in rows:
        by_company[r[0] or r[1]].append(r)
    farms = set()
    for company, group in by_company.items():
        if company in young and len(group) >= CLONE_FARM_MIN:
            counts = defaultdict(int)
            for r in group:
                counts[r[6]] += 1
            if sum(1 for r in group if r[6] and counts[r[6]] >= 3) / len(group) >= CLONE_SHARE:
                farms.add(company)
    out = {}
    for reg in REGIONS:
        mine = [r for r in rows if reg == "global" or r[3] == reg]
        signals, sites, examples = defaultdict(int), defaultdict(lambda: [0, 0]), defaultdict(int)
        suspicious = 0
        for r in mine:
            found = json.loads(r[4]) if r[4] else []
            if (r[0] or r[1]) in farms:
                found.append("clone farm")
            sites[r[2]][1] += 1
            if found:
                suspicious += 1
                sites[r[2]][0] += 1
                examples[(r[1], ", ".join(found))] += 1
                for s in found:
                    signals[s] += 1
        out[reg] = {
            "postings": len(mine), "suspicious": suspicious,
            "warnings": sum(1 for r in mine if r[5]),
            "signals": dict(signals),
            "sites": {s: {"suspicious": a, "postings": b} for s, (a, b) in sorted(sites.items(), key=lambda kv: -kv[1][1])},
            "examples": [{"company": c, "signals": s, "postings": n}
                         for (c, s), n in sorted(examples.items(), key=lambda kv: -kv[1])[:12]],
        }
    return out


MODES = ("remote", "hybrid", "on-site", "not stated")


def work_modes(state: State) -> dict:
    """Per region: open engineering jobs by work mode, overall and per language, with median pay."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    rows = list(state.db.execute(
        "select coalesce(work_mode, 'not stated'), region, language, pay_min, pay_max, pay_currency, pay_period"
        " from postings where engineering = 1 and last_seen >= ?", (since,)))
    out = {}
    for reg in REGIONS:
        mine = [r for r in rows if reg == "global" or r[1] == reg]
        overall = {}
        for mode in MODES:
            group = [r for r in mine if r[0] == mode]
            pays = [p for p in (_yearly((None, None, r[3], r[4], r[5], r[6])) for r in group) if p]
            overall[mode] = {"open_jobs": len(group), "with_pay": len(pays),
                             "mid_p50": statistics.median((lo + hi) / 2 for lo, hi in pays) if pays else None}
        per_language = defaultdict(lambda: {m: 0 for m in MODES})
        for r in mine:
            if r[2]:
                per_language[r[2]][r[0]] += 1
        out[reg] = {"overall": overall, "languages": per_language}
    return out


def lifetimes(state: State) -> dict:
    """Per region and language: how many engineering adverts have closed, and the
    median days they stayed up (from their posting date, else from first seen)."""
    rows = list(state.db.execute(
        "select region, language, julianday(closed_at) - julianday(coalesce(posted, first_seen)) from postings"
        " where engineering = 1 and language is not null and closed_at is not null"))
    out = {}
    for reg in REGIONS:
        groups = defaultdict(list)
        for region_, language, days in rows:
            if (reg == "global" or region_ == reg) and days is not None and days >= 0:
                groups[language].append(days)
                groups["all"].append(days)
        out[reg] = {l: {"closed": len(v), "median_days": round(statistics.median(v), 1)} for l, v in groups.items()}
    return out


def export(state: State, days: int = 120) -> dict:
    state.db.execute(SCHEMA)
    rows = _open_rows(state)
    current = defaultdict(dict)
    for (reg, language), group in _groups(rows).items():
        current[reg][language] = _stats(group)
    # New postings per day by the date each advert was posted: history from day one.
    start = (date.today() - timedelta(days=days)).isoformat()
    new_by_day = defaultdict(lambda: defaultdict(dict))
    for language, reg, day, count in state.db.execute(
            "select language, region, posted, count(*) from postings where engineering = 1 and language is not null"
            " and posted >= ? and posted <= ? group by 1, 2, 3", (start, date.today().isoformat())):
        for r in ("global", reg):
            if r in REGIONS:
                for lang in (language, "all"):
                    new_by_day[r][lang][day] = new_by_day[r][lang].get(day, 0) + count
    daily = [dict(zip(("day", "region", "language", "open_jobs", "new_jobs", "with_pay", "min_p50", "max_p50",
                       "mid_p25", "mid_p50", "mid_p75"), r))
             for r in state.db.execute("select * from market_daily order by day")]
    totals = state.db.execute(
        "select count(*), count(distinct company), sum(engineering), min(first_seen) from postings").fetchone()
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "totals": {"postings": totals[0], "companies": totals[1], "engineering": totals[2], "since": totals[3]},
        "bands": [f"{a // 1000}k" if b < 10**9 else f"{a // 1000}k+" for a, b in BANDS],
        "current": current,
        "new_by_day": {r: {l: sorted(v.items()) for l, v in langs.items()} for r, langs in new_by_day.items()},
        "daily": daily,
        "companies": companies_by_age(state),
        "ai": ai_work(state, days),
        "scams": scams(state),
        "work_modes": work_modes(state),
        "lifetimes": lifetimes(state),
    }


def dashboard_html(state: State) -> str:
    """dashboard/market.html with the current data embedded: written to a file
    by --dashboard, served live at /market by scanner.review."""
    template = (Path(__file__).parent.parent / "dashboard" / "market.html").read_text()
    data = json.dumps(export(state), separators=(",", ":")).replace("</", "<\\/")
    return template.replace("__DATA__", data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--export", metavar="JSON")
    parser.add_argument("--dashboard", metavar="HTML", help="dashboard/market.html with today's data embedded")
    args = parser.parse_args(argv)
    config = load_config()
    state = State(config["run"]["state_path"])
    if args.record:
        record(state)
    if args.export:
        Path(args.export).write_text(json.dumps(export(state), separators=(",", ":")))
        print(f"wrote {args.export}")
    if args.dashboard:
        Path(args.dashboard).write_text(dashboard_html(state))
        print(f"wrote {args.dashboard}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
