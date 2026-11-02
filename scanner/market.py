"""Pay by main programming language, from the stored adverts.

    .venv/bin/python -m scanner.market            # Europe and remote-from-Europe
    .venv/bin/python -m scanner.market --all      # every region
    .venv/bin/python -m scanner.market --postings # every job read (the market), not only screened ones

The main language is the one named in the title, else the one the text
names most often. Pay is the first range found in the text (scanner/salary.py)
or the structured salary when a site gives one, as yearly EUR.
"""

from __future__ import annotations

import argparse
import re
import statistics

from scanner.classify import ENGINEERING, EUROPE, NOT_ENGINEERING, main_language
from scanner.salary import TO_EUR, parse_salary, yearly_eur
from scanner.settings import load_config
from scanner.state import State, posting_text

def pay(row) -> tuple[float, float] | None:
    _, _, description, low, high, currency, interval = row[:7]
    if low and high and currency in TO_EUR:
        period = {"yearly": "year", "monthly": "month", "hourly": "hour"}.get(str(interval).lower(), interval)
        if period not in ("year", "month", "hour"):
            period = None
        found = yearly_eur(low, high, currency, period)
        if found:
            return found
    parsed = parse_salary(description)
    return yearly_eur(*parsed) if parsed else None


def report(state: State, everywhere: bool, postings: bool = False) -> str:
    if postings:
        rows = [(t, loc, posting_text(z), lo, hi, cur, period) for t, loc, z, lo, hi, cur, period in state.db.execute(
            "select p.title, p.location, x.text_z, p.pay_min, p.pay_max, p.pay_currency, p.pay_period"
            " from postings p join posting_texts x using (job_key)")]
    else:
        rows = list(state.db.execute(
            "select s.title, s.location, d.description, d.salary_min, d.salary_max, d.salary_currency, d.salary_interval"
            " from details d join seen s using (job_key) where d.description is not null"))
    groups: dict[str, list[tuple[float, float]]] = {}
    counted = {}
    for row in rows:
        title, location = row[0], row[1] or ""
        if not ENGINEERING.search(title or "") or NOT_ENGINEERING.search(title or ""):
            continue
        # The place comes from the location; the text only when the location says
        # nothing more than "Remote" (a US advert's text often mentions EMEA).
        place = location if re.sub(r"(?i)remote|worldwide|anywhere|[\s(),-]", "", location) else f"{location} {row[2][:400]}"
        if not everywhere and not EUROPE.search(place):
            continue
        language = main_language(title, row[2])
        if not language:
            continue
        counted[language] = counted.get(language, 0) + 1
        found = pay((title, location, row[2], *row[3:]))
        if found:
            groups.setdefault(language, []).append(found)
    lines = [f"{len(rows)} adverts with text; {sum(counted.values())} with a main language"
             + ("" if everywhere else " in Europe / remote from Europe"),
             f"{'language':24}{'adverts':>8}{'with pay':>9}{'median min':>12}{'median max':>12}{'middle half (mid-points)':>28}"]
    for language in sorted(counted, key=lambda k: -counted[k]):
        ranges = groups.get(language, [])
        if not ranges:
            lines.append(f"{language:24}{counted[language]:>8}{0:>9}")
            continue
        mids = sorted((lo + hi) / 2 for lo, hi in ranges)
        q = statistics.quantiles(mids, n=4) if len(mids) >= 4 else [mids[0], 0, mids[-1]]
        lines.append(
            f"{language:24}{counted[language]:>8}{len(ranges):>9}"
            f"{statistics.median(lo for lo, _ in ranges):>12,.0f}{statistics.median(hi for _, hi in ranges):>12,.0f}"
            f"{q[0]:>16,.0f} – {q[-1]:<9,.0f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="every region, not only Europe")
    parser.add_argument("--postings", action="store_true", help="every job read, not only the screened ones")
    args = parser.parse_args(argv)
    config = load_config()
    print(report(State(config["run"]["state_path"]), args.all, args.postings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
