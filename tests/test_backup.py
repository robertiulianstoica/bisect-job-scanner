import fcntl
import gzip
import sqlite3
from datetime import date

import pytest

from scanner import backup, metrics
from scanner.state import State


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_SCANNER_HOME", str(tmp_path))
    state = State(str(tmp_path / "state.sqlite3"))
    state.mark_seen({"site": "greenhouse", "title": "PHP Developer", "company": "Acme",
                     "job_url": "https://example.com/1"}, emailed=True)
    key = state.db.execute("select job_key from seen").fetchone()[0]
    state.set_triage(key, "applied", "good fit", bisect_id="01abc")
    state.add_board("greenhouse", "acme", "config")
    state.db.execute(metrics.SCHEMA)
    state.db.execute("insert into market_daily (day, region, language, open_jobs) values ('2026-10-30', 'EU', 'PHP', 5)")
    state.commit()
    state.db.close()
    (tmp_path / "config.toml").write_text('[run]\n')
    (tmp_path / "env").write_text("JOB_SCANNER_MAILER_DSN=secret\n")
    config, file = backup.load_config(with_path=True)
    return tmp_path, config, file


def test_full_and_precious_backup_and_restore(profile):
    home, config, file = profile
    manifest = backup.run_backup(config, file, today=date(2026, 10, 31), log=lambda _m: None)
    assert manifest["integrity"] == "ok"
    gz = home / "backups" / "full" / "state-2026-10-31.sqlite3.gz"
    day = home / "backups" / "precious" / "2026-10-31"
    assert gz.is_file() and (home / "backups" / "full" / "state-2026-10-31.json").is_file()
    assert {p.name for p in day.iterdir()} == {"schema.sql", "manifest.json", "config.toml", "triage.jsonl",
                                               "market_daily.jsonl", "boards.jsonl", "seen.jsonl"}
    assert not any("secret" in p.read_text() for p in day.iterdir())  # env is never copied
    assert all(p.stat().st_mode & 0o077 == 0 for p in day.iterdir())  # private, like the database

    live = backup.counts(home / "state.sqlite3")
    assert backup.restore(gz, home / "r" / "full.sqlite3", home / "state.sqlite3", False, log=lambda _m: None) == live
    restored = backup.restore(day, home / "r" / "precious.sqlite3", home / "state.sqlite3", False, log=lambda _m: None)
    assert restored == {t: live[t] for t in ("triage", "market_daily", "boards", "seen")}
    db = sqlite3.connect(home / "r" / "precious.sqlite3")
    assert db.execute("select verdict, reason, bisect_id from triage").fetchone() == ("applied", "good fit", "01abc")
    db.close()
    State(str(home / "r" / "precious.sqlite3")).db.close()  # the scanner can open what was restored


def test_restore_refuses_live_and_existing_files(profile):
    home, config, file = profile
    backup.run_backup(config, file, today=date(2026, 10, 31), log=lambda _m: None)
    gz = home / "backups" / "full" / "state-2026-10-31.sqlite3.gz"
    live = home / "state.sqlite3"
    with pytest.raises(RuntimeError, match="live database"):
        backup.restore(gz, live, live, False)
    other = home / "other.sqlite3"
    other.write_bytes(b"")
    with pytest.raises(RuntimeError, match="exists"):
        backup.restore(gz, other, live, False)
    # --force over the live database waits for no scan: it refuses while the lock is held.
    with open(home / "state.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="scan is running"):
            backup.restore(gz, live, live, True)
    backup.restore(gz, live, live, True, log=lambda _m: None)
    assert list(home.glob("state.sqlite3.before-restore-*"))  # the replaced file is kept


def test_failed_restore_leaves_the_target_alone(profile, tmp_path):
    home, _config, _file = profile
    bad = tmp_path / "bad.sqlite3.gz"
    with gzip.open(bad, "wb") as handle:
        handle.write(b"not a database" * 100)
    target = home / "keep.sqlite3"
    target.write_bytes(b"precious")
    with pytest.raises(Exception):
        backup.restore(bad, target, home / "state.sqlite3", True, log=lambda _m: None)
    assert target.read_bytes() == b"precious"


def test_keep_full_keeps_seven_days_and_four_sundays():
    days = [date.fromordinal(date(2026, 8, 1).toordinal() + n).isoformat() for n in range(92)]
    keep = backup.keep_full(days)
    assert sorted(keep)[-7:] == days[-7:]
    sundays = [d for d in days if date.fromisoformat(d).weekday() == 6]
    assert set(sundays[-4:]) <= keep and len(keep) <= 11


def test_pruning_touches_only_its_own_files(tmp_path):
    full = tmp_path / "full"
    full.mkdir()
    for n in range(1, 21):
        (full / f"state-2026-10-{n:02}.sqlite3.gz").write_bytes(b"x")
    (full / "state.sqlite3").write_bytes(b"live")
    (full / "state-2026-10-01.sqlite3.gz.keep").write_bytes(b"other")
    backup.prune_full(full, 7, 4)
    left = sorted(p.name for p in full.iterdir())
    assert "state.sqlite3" in left and "state-2026-10-01.sqlite3.gz.keep" in left
    assert [n for n in left if n.endswith(".gz")][-7:] == [f"state-2026-10-{n}.sqlite3.gz" for n in range(14, 21)]

    precious = tmp_path / "precious"
    for name, manifest in (("2026-08-01", True), ("2026-08-02", False), ("2026-10-30", True), ("manual", True)):
        (precious / name).mkdir(parents=True)
        if manifest:
            (precious / name / "manifest.json").write_text("{}")
    backup.prune_precious(precious, 30, date(2026, 10, 31))
    assert sorted(p.name for p in precious.iterdir()) == ["2026-08-02", "2026-10-30", "manual"]
