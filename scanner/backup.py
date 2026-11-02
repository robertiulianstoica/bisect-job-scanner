"""Backups of the state database and the config, and restoring them.

    python -m scanner.backup                    # full copy + precious tables, then prune old ones
    python -m scanner.backup --list             # what is there, with sizes and dates
    python -m scanner.backup --restore FILE --to /tmp/state.sqlite3
    python -m scanner.backup --restore DIR  --to /tmp/state.sqlite3   # precious JSONL into an empty schema
    python -m scanner.backup --restore FILE --force                   # over the live database

Two kinds, under backups/ in the profile directory ([backup] dir to move it):

    full/state-<day>.sqlite3.gz     the whole database, an online copy taken while
                                    scans may be writing; the last 7 days and the
                                    last 4 Sundays are kept
    precious/<day>/                 the tables that cannot be read again from the
                                    web (triage, market_daily, companies, boards,
                                    seen) as JSONL, their schema, the config and a
                                    manifest; 30 days are kept, and copied to
                                    [backup] offsite_dir when it is set

The env file (SMTP password) is never copied. Only files this tool names
itself are ever deleted. Any failure exits non-zero, so the scheduler's log
shows it.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from scanner.settings import load_config, lock_path, profile_home

PRECIOUS = ("triage", "market_daily", "companies", "boards", "seen")
FULL_NAME = re.compile(r"^state-(\d{4}-\d{2}-\d{2})\.sqlite3\.gz$")
DAY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def backup_dir(config: dict) -> Path:
    return Path(config.get("backup", {}).get("dir") or profile_home() / "backups").expanduser()


def tables(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute("select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name")]


def counts(path: Path) -> dict[str, int]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {t: db.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables(db)}
    finally:
        db.close()


def integrity(path: Path) -> str:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return "; ".join(r[0] for r in db.execute("pragma integrity_check"))
    finally:
        db.close()


def snapshot(source: Path, dest: Path) -> None:
    """A consistent copy of a database other processes may be writing to,
    with SQLite's online backup API. The source is opened read-only."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def export_precious(db_path: Path, out: Path) -> dict[str, int]:
    """One JSONL file per precious table, and schema.sql to recreate them."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    written = {}
    try:
        present = set(tables(db))
        schema = [r[0] for r in db.execute(
            "select sql from sqlite_master where tbl_name in ({}) and sql is not null order by type desc, name"
            .format(",".join("?" * len(PRECIOUS))), PRECIOUS)]
        (out / "schema.sql").write_text(";\n".join(schema) + ";\n")
        for table in PRECIOUS:
            if table not in present:
                continue
            with open(out / f"{table}.jsonl", "w") as handle:
                written[table] = 0
                for row in db.execute(f'select * from "{table}"'):
                    handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
                    written[table] += 1
    finally:
        db.close()
    return written


def keep_full(days: list[str], daily: int = 7, weekly: int = 4) -> set[str]:
    """Which days of full backups to keep: the last `daily`, and the last `weekly` Sundays."""
    ordered = sorted(set(days), reverse=True)
    sundays = [d for d in ordered if date.fromisoformat(d).weekday() == 6]
    return set(ordered[:daily]) | set(sundays[:weekly])


def prune_full(folder: Path, daily: int, weekly: int) -> list[Path]:
    found = {m.group(1): p for p in folder.iterdir() if (m := FULL_NAME.match(p.name))}
    keep = keep_full(list(found), daily, weekly)
    gone = []
    for day, path in sorted(found.items()):
        if day not in keep:
            path.unlink()
            path.with_name(f"state-{day}.json").unlink(missing_ok=True)
            gone.append(path)
    return gone


def prune_precious(folder: Path, days: int, today: date) -> list[Path]:
    """Day folders older than `days`; only those this tool wrote (named by day, with a manifest)."""
    cutoff = today - timedelta(days=days)
    gone = []
    for path in sorted(folder.iterdir()):
        if path.is_dir() and DAY_NAME.match(path.name) and (path / "manifest.json").is_file() \
                and date.fromisoformat(path.name) < cutoff:
            shutil.rmtree(path)
            gone.append(path)
    return gone


def run_backup(config: dict, config_file: Path | None, today: date | None = None, log=print) -> dict:
    old_umask = os.umask(0o077)  # backups hold the same personal data as the database
    try:
        return _run_backup(config, config_file, today or date.today(), log)
    finally:
        os.umask(old_umask)


def _run_backup(config: dict, config_file: Path | None, today: date, log) -> dict:
    day = today.isoformat()
    source = Path(config["run"]["state_path"]).expanduser()
    if not source.is_file():
        raise RuntimeError(f"no database at {source}")
    root = backup_dir(config)
    settings = config.get("backup", {})
    full, precious = root / "full", root / "precious"
    for folder in (full, precious):
        folder.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"day": day, "started": datetime.now().isoformat(timespec="seconds"), "source": str(source)}
    work = full / f".state-{day}.sqlite3.tmp"
    work.unlink(missing_ok=True)
    try:
        snapshot(source, work)
        manifest["integrity"] = integrity(work)
        if manifest["integrity"] != "ok":
            raise RuntimeError(f"integrity check of the copy: {manifest['integrity']}")
        manifest["counts"] = counts(work)
        manifest["db_bytes"] = work.stat().st_size

        # Precious tables, from the same snapshot so they agree with the full copy.
        target = precious / day
        staging = precious / f".{day}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        manifest["exported"] = export_precious(work, staging)
        if config_file and config_file.is_file():
            shutil.copy2(config_file, staging / "config.toml")
            (staging / "config.toml").chmod(0o600)  # copy2 keeps the source's mode
            manifest["config"] = str(config_file)

        gz = full / f"state-{day}.sqlite3.gz"
        partial = gz.with_name(gz.name + ".tmp")
        with open(work, "rb") as raw, gzip.open(partial, "wb", compresslevel=6) as packed:
            shutil.copyfileobj(raw, packed, 1 << 20)
        os.replace(partial, gz)
        manifest["full"] = str(gz)
        manifest["full_bytes"] = gz.stat().st_size
    finally:
        work.unlink(missing_ok=True)

    manifest["finished"] = datetime.now().isoformat(timespec="seconds")
    text = json.dumps(manifest, indent=2) + "\n"
    (full / f"state-{day}.json").write_text(text)
    (staging / "manifest.json").write_text(text)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staging, target)
    log(f"full: {gz} ({manifest['full_bytes'] / 1e6:.0f} MB, {manifest['db_bytes'] / 1e6:.0f} MB unpacked), integrity ok")
    log(f"precious: {target} ({', '.join(f'{t} {n}' for t, n in manifest['exported'].items())})")

    for path in prune_full(full, settings.get("keep_daily", 7), settings.get("keep_weekly", 4)):
        log(f"pruned {path.name}")
    keep_days = settings.get("keep_precious_days", 30)
    for path in prune_precious(precious, keep_days, today):
        log(f"pruned precious/{path.name}")

    offsite = settings.get("offsite_dir")
    if offsite:
        away = Path(offsite).expanduser()
        if not away.is_dir():
            raise RuntimeError(f"offsite_dir {away} does not exist; local backups were written")
        copy = away / day
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(target, copy)
        prune_precious(away, keep_days, today)
        log(f"offsite: {copy}")
    return manifest


def restore(source: Path, dest: Path, live: Path, force: bool, log=print) -> dict[str, int]:
    """A full backup (.sqlite3.gz or .sqlite3) or a precious folder into `dest`.
    The live database, or any existing file, is only replaced with `force`; the
    live one then needs the scanner's lock free, and is kept aside, not deleted."""
    dest = dest.expanduser().resolve()
    is_live = dest == live.expanduser().resolve()
    if dest.exists() and not force:
        raise RuntimeError(f"{dest} exists" + (" and is the live database" if is_live else "") + "; add --force to replace it")
    lock = None
    if is_live:
        lock = open(lock_path(live), "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("a scan is running (its lock is held); try again when it ends")
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.with_name(f".{dest.name}.restore.tmp")
    work.unlink(missing_ok=True)
    try:
        if source.is_dir():
            restore_precious(source, work)
        elif source.name.endswith(".gz"):
            with gzip.open(source, "rb") as packed, open(work, "wb") as raw:
                shutil.copyfileobj(packed, raw, 1 << 20)
        else:
            snapshot(source, work)
        result = integrity(work)
        if result != "ok":
            raise RuntimeError(f"integrity check of the restored copy: {result}")
        if dest.exists():
            aside = dest.with_name(f"{dest.name}.before-restore-{datetime.now():%Y%m%d-%H%M%S}")
            os.replace(dest, aside)
            log(f"kept the old file as {aside}")
        os.replace(work, dest)
    finally:
        work.unlink(missing_ok=True)
        if lock:
            lock.close()
    found = counts(dest)
    log(f"restored {source} to {dest}: " + ", ".join(f"{t} {n}" for t, n in found.items()))
    return found


def restore_precious(folder: Path, dest: Path) -> None:
    db = sqlite3.connect(dest)
    try:
        db.executescript((folder / "schema.sql").read_text())
        for table in PRECIOUS:
            file = folder / f"{table}.jsonl"
            if not file.is_file():
                continue
            with open(file) as handle:
                for line in handle:
                    row = json.loads(line)
                    columns = ",".join(f'"{c}"' for c in row)
                    db.execute(f'insert into "{table}" ({columns}) values ({",".join("?" * len(row))})',
                               list(row.values()))
        db.commit()
    finally:
        db.close()


def listing(config: dict) -> list[tuple[str, int, str]]:
    root = backup_dir(config)
    rows = []
    for path in sorted(root.rglob("*")) if root.is_dir() else []:
        if path.name.startswith(".") or path.is_dir() and not (path / "manifest.json").exists():
            continue
        if path.parent.parent == root / "precious":  # a file inside a precious day: shown as its folder
            continue
        size = sum(p.stat().st_size for p in path.rglob("*")) if path.is_dir() else path.stat().st_size
        rows.append((str(path.relative_to(root)) + ("/" if path.is_dir() else ""), size,
                     datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="default: $JOB_SCANNER_HOME/config.toml")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="FILE_OR_DIR")
    parser.add_argument("--to", type=Path, help="where to restore (default: the live database, which needs --force)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)  # backups hold the same personal data as the database
    config, config_file = load_config(args.config, with_path=True)
    live = Path(config["run"]["state_path"]).expanduser()
    try:
        if args.list:
            for name, size, when in listing(config):
                print(f"{when}  {size / 1e6:>9.1f} MB  {name}")
            print(f"in {backup_dir(config)}", file=sys.stderr)
        elif args.restore:
            restore(args.restore.expanduser(), args.to or live, live, args.force)
        else:
            print(f"--- backup {datetime.now():%Y-%m-%d %H:%M}")
            run_backup(config, config_file)
    except Exception as error:
        print(f"scanner.backup failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
