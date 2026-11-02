"""What the scanner remembers between runs: jobs already seen, and the
company boards it has found."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path

from scanner.classify import ai_kind, is_engineering, main_language, region, scam_signals, warns_of_fraud, work_mode
from scanner.stack import tags

SCHEMA = """
create table if not exists seen (
    job_key text primary key,
    site text,
    title text,
    company text,
    url text,
    first_seen text,
    emailed integer default 0
);
create table if not exists boards (
    ats text,
    slug text,
    source text,
    added text,
    primary key (ats, slug)
);
-- The advert itself, kept for what the scanner may become: the text as
-- read, its pay, and the stack it asks for (scanner/stack.py).
create table if not exists details (
    job_key text primary key,
    description text,
    text_hash text,        -- spots the same advert reposted under another id
    stack text,            -- JSON list of tags
    salary_min real,
    salary_max real,
    salary_currency text,
    salary_interval text,
    is_remote integer,
    job_type text,
    job_level text,
    company_url text,
    job_url_direct text,
    source_board text,     -- ats:slug for company boards
    captured_at text
);
-- Every job read, whatever the screening thought of it: the market, not
-- your shortlist. The advert text is kept apart (posting_texts), so old
-- texts can be dropped while titles, companies, pay and stack stay as history.
create table if not exists postings (
    job_key text primary key,
    site text,
    source_board text,
    company text,
    title text,
    location text,
    url text,
    posted text,
    first_seen text,
    last_seen text,
    text_hash text,
    stack text,            -- JSON list of tags (scanner/stack.py)
    -- Pay as the advert states it, in its own currency; converting is for views.
    pay_min real,
    pay_max real,
    pay_currency text,
    pay_period text,       -- year, month, hour; null when the advert does not say
    pay_source text,       -- site (structured fields) or text (scanner/salary.py)
    engineering integer,   -- an engineering title (scanner/classify.py)
    language text,         -- main programming language, engineering roles only
    region text,           -- EU, US or other
    ai text,               -- builds or uses AI (scanner/classify.py), engineering roles only
    scam_signals text,     -- JSON list of scam signals in the text (scanner/classify.py)
    fraud_warning integer, -- the advert warns candidates about recruitment fraud
    work_mode text,        -- remote, hybrid, on-site; null when not stated (scanner/classify.py)
    closed_at text,        -- first successful read of its board without it (scanner/state.close_missing)
    is_remote integer,
    job_type text,
    job_level text
);
create table if not exists posting_texts (
    job_key text primary key,
    text_z blob            -- zlib-compressed advert text (scanner.state.posting_text)
);
-- What you decided about a job after reading it: the scanner's rules
-- only say a job might fit; this says whether it is worth applying to.
create table if not exists triage (
    job_key text primary key,
    verdict text not null,
    reason text,
    decided_at text,
    bisect_id text         -- the application's id in your own tracker (triage set --bisect)
);
"""

# Verdicts, in the order a shortlist is read.
VERDICTS = ("shortlist", "maybe", "later", "applied", "out")

# Added after the first version; applied to existing databases on open.
MIGRATIONS = (
    "alter table boards add column tier text default 'hot'",  # hot: every run; cold: in rotation
    "alter table boards add column last_read text",
    "alter table seen add column location text",
    "alter table seen add column posted text",
    "alter table seen add column applicants integer",
    "alter table seen add column flags text",   # what the email said about it
    "alter table seen add column reason text",  # why the rules turned it down
    "alter table seen add column last_seen text",  # last run that still listed it: how long an advert stays up
    "create index if not exists seen_url on seen(url)",  # one advert found by two sources (peviitor and hipo)
)

# Board URLs as they appear in job links: the slug is the company's board.
BOARD_PATTERNS = {
    "greenhouse": re.compile(r"(?:job-boards(?:\.eu)?|boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([A-Za-z0-9_-]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9._-]+)"),
    "lever": re.compile(r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9._-]+)"),
    "personio": re.compile(r"([A-Za-z0-9-]+)\.jobs\.personio\.(?:com|de)"),
    "recruitee": re.compile(r"([A-Za-z0-9-]+)\.recruitee\.com"),
    "smartrecruiters": re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    "teamtailor": re.compile(r"([A-Za-z0-9-]+\.teamtailor\.com)"),
    "gem": re.compile(r"jobs\.gem\.com/([A-Za-z0-9._-]+)"),
    "workable": re.compile(r"apply\.workable\.com/([A-Za-z0-9-]+)"),
    "rippling": re.compile(r"ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    # Two parts, joined into one slug: <tenant>.wd<N>/<site>; a locale may sit between.
    "workday": re.compile(r"([a-z0-9-]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
}
NOT_SLUGS = {"embed", "jobs", "v1", "api", "j", "wday", "www.teamtailor.com", "app.teamtailor.com", "career.teamtailor.com"}


def _num(value):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


PERIODS = {"yearly": "year", "monthly": "month", "weekly": "week", "daily": "day", "hourly": "hour"}


def _pay(job: dict, text: str) -> tuple | None:
    """(min, max, currency, period, source) as stated: the site's own salary
    fields when it has them, else the first range in the advert's text."""
    from scanner.salary import parse_salary

    low, high, currency = _num(job.get("min_amount")), _num(job.get("max_amount")), job.get("currency")
    if (low or high) and currency:
        interval = str(job.get("interval") or "").lower().split(".")[-1]
        return low, high, currency, PERIODS.get(interval), "site"
    parsed = parse_salary(text)
    return (*parsed, "text") if parsed else None


def posting_text(blob: bytes | None) -> str:
    return zlib.decompress(blob).decode() if blob else ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_key(job: dict) -> str:
    """Stable identity: the site's own id, else the URL."""
    return str(job.get("id") or job.get("job_url"))


def boards_in(*urls: str | None) -> list[tuple[str, str]]:
    found = []
    for url in urls:
        if not url or not isinstance(url, str):
            continue
        for ats, pattern in BOARD_PATTERNS.items():
            match = pattern.search(url)
            if match and match.groups()[-1].lower() not in NOT_SLUGS:
                found.append((ats, "/".join(match.groups())))
    return found


class State:
    def __init__(self, path: str):
        file = Path(path).expanduser()
        file.parent.mkdir(parents=True, exist_ok=True)
        # Wait for another writer (a backfill alongside a scheduled run) instead of failing.
        self.db = sqlite3.connect(file, timeout=60)
        self.db.executescript(SCHEMA)
        for statement in MIGRATIONS:
            try:
                self.db.execute(statement)
            except sqlite3.OperationalError:
                pass  # already applied
        self._split_posting_texts()
        self._pay_as_written()
        self._classify_postings()
        self._classify_ai()
        self._classify_scams()
        self._classify_work_mode()
        self._closed_from_past_reads()

    def _split_posting_texts(self) -> None:
        """Move advert texts out of postings (kept there by the first version)."""
        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "text_z" not in columns:
            return
        self.db.execute("insert or ignore into posting_texts (job_key, text_z)"
                        " select job_key, text_z from postings where text_z is not null")
        self.db.execute("alter table postings drop column text_z")
        self.db.commit()

    def _pay_as_written(self) -> None:
        """Replace the first version's yearly-EUR pay with pay as the advert states it."""
        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "pay_eur_min" not in columns:
            return
        for column in ("pay_min real", "pay_max real", "pay_currency text", "pay_period text", "pay_source text"):
            if column.split()[0] not in columns:
                self.db.execute(f"alter table postings add column {column}")
        rows = list(self.db.execute(
            "select p.job_key, p.salary_min, p.salary_max, p.salary_currency, p.salary_interval, x.text_z"
            " from postings p left join posting_texts x using (job_key)"))
        updates = []
        for key, low, high, currency, interval, blob in rows:
            pay = _pay({"min_amount": low, "max_amount": high, "currency": currency, "interval": interval},
                       posting_text(blob))
            if pay:
                updates.append((*pay, key))
        self.db.executemany("update postings set pay_min=?, pay_max=?, pay_currency=?, pay_period=?, pay_source=?"
                            " where job_key=?", updates)
        for column in ("pay_eur_min", "pay_eur_max", "salary_min", "salary_max", "salary_currency", "salary_interval"):
            self.db.execute(f"alter table postings drop column {column}")
        self.db.commit()

    def _classify_postings(self) -> None:
        """Give postings stored before classification their engineering flag,
        main language and region."""
        from scanner.classify import is_engineering, main_language, region

        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "engineering" in columns:
            return
        for column in ("engineering integer", "language text", "region text"):
            if column.split()[0] not in columns:
                self.db.execute(f"alter table postings add column {column}")
        updates = []
        location_column = "p.location" if "location" in columns else "null"
        for key, title, location, blob in self.db.execute(
                f"select p.job_key, p.title, {location_column}, x.text_z"
                " from postings p left join posting_texts x using (job_key)"):
            engineering = is_engineering(title)
            text = posting_text(blob) if blob else ""
            updates.append((int(engineering), main_language(title, text) if engineering else None,
                            region(location, text), key))
        self.db.executemany("update postings set engineering=?, language=?, region=? where job_key=?", updates)
        self.db.commit()

    def _classify_ai(self) -> None:
        """Mark engineering postings stored before the AI classification."""
        from scanner.classify import ai_kind

        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "ai" in columns or "engineering" not in columns:
            return
        self.db.execute("alter table postings add column ai text")
        updates = [(ai_kind(title, posting_text(blob)), key) for key, title, blob in self.db.execute(
            "select p.job_key, p.title, x.text_z from postings p left join posting_texts x using (job_key)"
            " where p.engineering = 1")]
        self.db.executemany("update postings set ai = ? where job_key = ?", updates)
        self.db.commit()

    def _classify_scams(self) -> None:
        """Scam signals and fraud warnings for postings stored before they were looked for."""
        from scanner.classify import scam_signals, warns_of_fraud

        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "scam_signals" in columns or "title" not in columns:
            return
        self.db.execute("alter table postings add column scam_signals text")
        self.db.execute("alter table postings add column fraud_warning integer")
        updates = []
        for key, blob in self.db.execute(
                "select p.job_key, x.text_z from postings p left join posting_texts x using (job_key)"):
            text = posting_text(blob)
            signals = scam_signals(text)
            updates.append((json.dumps(signals) if signals else None, int(warns_of_fraud(text)), key))
        self.db.executemany("update postings set scam_signals = ?, fraud_warning = ? where job_key = ?", updates)
        self.db.commit()

    def _classify_work_mode(self) -> None:
        """Remote, hybrid or on-site for postings stored before it was recorded."""
        from scanner.classify import work_mode

        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "work_mode" in columns or "location" not in columns:
            return
        self.db.execute("alter table postings add column work_mode text")
        updates = [(work_mode(location, remote, posting_text(blob)), key) for key, location, remote, blob in self.db.execute(
            "select p.job_key, p.location, p.is_remote, x.text_z from postings p left join posting_texts x using (job_key)")]
        self.db.executemany("update postings set work_mode = ? where job_key = ?", updates)
        self.db.commit()

    def _closed_from_past_reads(self) -> None:
        """Add closed_at, and close what reads before it already showed gone: a
        posting last seen before its board's last read, on a board whose last
        read did list jobs (a failed or empty read proves nothing)."""
        columns = {row[1] for row in self.db.execute("pragma table_info(postings)")}
        if "closed_at" in columns or "source_board" not in columns:
            return
        self.db.execute("alter table postings add column closed_at text")
        self.db.execute("""
            update postings set closed_at = (
                select b.last_read from boards b where b.ats || ':' || b.slug = lower(postings.source_board))
            where source_board is not null and closed_at is null and exists (
                select 1 from boards b where b.ats || ':' || b.slug = lower(postings.source_board)
                and datetime(b.last_read) > datetime(postings.last_seen, '+10 minutes')
                and exists (select 1 from postings q where q.source_board = postings.source_board
                            and datetime(q.last_seen) >= datetime(b.last_read, '-10 minutes')))""")
        self.db.commit()

    def close_missing(self, read_started: str, listed_boards: set[str]) -> int:
        """Postings on boards read in this run (and listing jobs) that the read
        did not list are closed now."""
        if not listed_boards:
            return 0
        self.db.execute("create temp table if not exists listed (board text primary key)")
        self.db.execute("delete from listed")
        self.db.executemany("insert or ignore into listed values (?)", [(b,) for b in listed_boards])
        cursor = self.db.execute(
            "update postings set closed_at = ? where closed_at is null and last_seen < ?"
            " and source_board in (select board from listed)", (now(), read_started))
        self.db.commit()
        return cursor.rowcount

    def drop_old_texts(self, days: int) -> int:
        """Delete the advert texts of postings not listed for `days` days;
        the postings themselves (title, company, pay, stack) stay."""
        cursor = self.db.execute(
            "delete from posting_texts where job_key in (select job_key from postings"
            " where last_seen < datetime('now', ?))", (f"-{int(days)} days",))
        self.db.commit()
        return cursor.rowcount

    def is_seen(self, key: str, url: str | None = None) -> bool:
        """By the job's key, or by its URL when another source already brought the same advert."""
        if self.db.execute("select 1 from seen where job_key = ?", (key,)).fetchone():
            return True
        return bool(url) and self.db.execute("select 1 from seen where url = ?", (url,)).fetchone() is not None

    def mark_seen(self, job: dict, emailed: bool, reason: str | None = None) -> None:
        applicants = job.get("num_applicants")
        self.db.execute(
            "insert or ignore into seen (job_key, site, title, company, url, first_seen, emailed,"
            " location, posted, applicants, flags, reason) values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_key(job), job.get("site"), job.get("title"), job.get("company"), job.get("job_url"), now(),
                int(emailed), job.get("location"), str(job.get("date_posted") or "") or None,
                int(applicants) if isinstance(applicants, (int, float)) and applicants == applicants else None,
                " · ".join(job.get("flags") or []) or None, reason,
            ),
        )
        self.save_details(job)

    def save_details(self, job: dict) -> None:
        def value(key):
            v = job.get(key)
            return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

        description = value("description")
        normalized = re.sub(r"\s+", " ", description or "").strip().lower()
        self.db.execute(
            "insert or ignore into details (job_key, description, text_hash, stack, salary_min, salary_max,"
            " salary_currency, salary_interval, is_remote, job_type, job_level, company_url, job_url_direct,"
            " source_board, captured_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_key(job), description,
                hashlib.sha1(normalized.encode()).hexdigest()[:16] if normalized else None,
                json.dumps(tags(job.get("title"), description)),
                value("min_amount"), value("max_amount"), value("currency"),
                str(value("interval")) if value("interval") is not None else None,
                None if value("is_remote") is None else int(bool(value("is_remote"))),
                str(value("job_type")) if value("job_type") is not None else None,
                value("job_level"), value("company_url"), value("job_url_direct"), value("source_board"), now(),
            ),
        )

    def save_postings(self, jobs: list[dict]) -> None:
        """Store every job read; a job already stored only gets its last_seen."""
        if not jobs:
            return
        if not hasattr(self, "_posting_keys"):
            self._posting_keys = {k for (k,) in self.db.execute("select job_key from postings")}
        stamp = now()
        fresh, again, texts = [], [], []
        for job in jobs:
            key = job_key(job)
            if key in self._posting_keys:
                again.append((stamp, key))
                continue
            self._posting_keys.add(key)
            text = job.get("description") or ""
            pay = _pay(job, text)
            engineering = is_engineering(job.get("title"))
            fresh.append((
                key, job.get("site"), job.get("source_board"), job.get("company"), job.get("title"),
                job.get("location"), job.get("job_url"), str(job.get("date_posted") or "") or None, stamp, stamp,
                hashlib.sha1(re.sub(r"\s+", " ", text).strip().lower().encode()).hexdigest()[:16] if text else None,
                json.dumps(tags(job.get("title"), text)),
                *(pay or (None, None, None, None, None)),
                int(engineering), main_language(job.get("title"), text) if engineering else None,
                region(job.get("location"), text),
                ai_kind(job.get("title"), text) if engineering else None,
                json.dumps(scam_signals(text)) if scam_signals(text) else None, int(warns_of_fraud(text)),
                work_mode(job.get("location"), job.get("is_remote"), text),
                None if job.get("is_remote") is None else int(bool(job.get("is_remote"))),
                str(job["job_type"]) if job.get("job_type") is not None else None, job.get("job_level"),
            ))
            if text:
                texts.append((key, zlib.compress(text.encode())))
        self.db.executemany(
            "insert or ignore into postings (job_key, site, source_board, company, title, location, url, posted,"
            " first_seen, last_seen, text_hash, stack, pay_min, pay_max, pay_currency, pay_period, pay_source,"
            " engineering, language, region, ai, scam_signals, fraud_warning, work_mode, is_remote, job_type, job_level)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fresh)
        self.db.executemany("insert or ignore into posting_texts (job_key, text_z) values (?,?)", texts)
        self.db.executemany("update postings set last_seen = ?, closed_at = null where job_key = ?", again)
        self.db.commit()

    def touch(self, keys: list[str]) -> None:
        """Note that these jobs were still listed in this run."""
        stamp = now()
        self.db.executemany("update seen set last_seen = ? where job_key = ?", [(stamp, k) for k in keys])

    def known_sites(self) -> set[str]:
        return {row[0] for row in self.db.execute("select distinct site from seen where site is not null")}

    def boards(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for ats, slug in self.db.execute("select ats, slug from boards order by ats, slug"):
            result.setdefault(ats, []).append(slug)
        return result

    def add_board(self, ats: str, slug: str, source: str, tier: str = "hot",
                  promote_existing: bool = True) -> bool:
        """Add a board; a known one named again (config, --add-board) becomes hot.

        Links seen in jobs pass promote_existing=False: every job read from a
        board in rotation links back to that board, which would otherwise
        make the whole rotation hot within a day.
        """
        cursor = self.db.execute(
            "insert or ignore into boards (ats, slug, source, added, tier) values (?,?,?,?,?)",
            (ats, slug.lower(), source, now(), tier),
        )
        if cursor.rowcount == 0 and tier == "hot" and promote_existing:
            # A board already known in rotation becomes hot when named again.
            self.promote(ats, slug)
        return cursor.rowcount > 0

    def promote(self, ats: str, slug: str) -> None:
        self.db.execute("update boards set tier = 'hot' where ats = ? and slug = ?", (ats, slug.lower()))

    def boards_to_read(self, cold_limit: int) -> dict[str, list[str]]:
        """Every hot board, plus the cold boards read longest ago."""
        rows = list(self.db.execute("select ats, slug from boards where tier = 'hot'"))
        rows += list(self.db.execute(
            "select ats, slug from boards where tier = 'cold' order by last_read is not null, last_read limit ?",
            (cold_limit,),
        ))
        result: dict[str, list[str]] = {}
        for ats, slug in rows:
            result.setdefault(ats, []).append(slug)
        return result

    def mark_read(self, boards: dict[str, list[str]]) -> None:
        stamp = now()
        self.db.executemany(
            "update boards set last_read = ? where ats = ? and slug = ?",
            [(stamp, ats, slug) for ats, slugs in boards.items() for slug in slugs],
        )

    def board_counts(self) -> dict[str, int]:
        return dict(self.db.execute("select tier, count(*) from boards group by tier"))

    def set_triage(self, key: str, verdict: str, reason: str | None = None,
                   bisect_id: str | None = None) -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
        self.db.execute(
            "insert into triage (job_key, verdict, reason, decided_at, bisect_id) values (?,?,?,?,?)"
            " on conflict(job_key) do update set verdict = excluded.verdict,"
            " reason = coalesce(excluded.reason, triage.reason), decided_at = excluded.decided_at,"
            " bisect_id = coalesce(excluded.bisect_id, triage.bisect_id)",
            (key, verdict, reason, now(), bisect_id),
        )

    def add_manual_job(self, title: str, company: str, url: str, location: str | None = None) -> str:
        """A job found outside the scanner (a company board read by hand), so it can be triaged."""
        key = url
        self.db.execute(
            "insert or ignore into seen (job_key, site, title, company, url, first_seen, emailed, location)"
            " values (?,?,?,?,?,?,?,?)",
            (key, "manual", title, company, url, now(), 0, location),
        )
        return key

    def commit(self) -> None:
        self.db.commit()
