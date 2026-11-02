from scanner.state import State
from scanner.triage import funnel


def test_funnel_counts_jobs_found_and_worth_a_look_per_day(tmp_path):
    state = State(str(tmp_path / "state.sqlite3"))
    rows = [("a", "2026-10-30T10:00:00+00:00"), ("b", "2026-10-30T11:00:00+00:00"),
            ("c", "2026-10-30T12:00:00+00:00"), ("d", "2026-10-31T10:00:00+00:00")]
    for key, seen in rows:
        state.db.execute("insert into postings (job_key, first_seen) values (?, ?)", (key, seen))
        state.db.execute("insert into seen (job_key, first_seen) values (?, ?)", (key, seen))
    state.set_triage("a", "shortlist")
    state.set_triage("b", "applied", bisect_id="01abc")
    state.set_triage("c", "out")  # not worth a look: not counted
    state.set_triage("d", "maybe")
    assert funnel(state, "2026-10-30") == [("2026-10-30", 3, 2)]
    # A job added by hand is in seen only, and counts as found.
    key = state.add_manual_job("Backend Developer", "Acme", "https://example.com/1")
    state.db.execute("update seen set first_seen = '2026-10-31T09:00:00+00:00' where job_key = ?", (key,))
    state.set_triage(key, "applied")
    assert funnel(state, "2026-10-31") == [("2026-10-31", 2, 2)]
    assert funnel(state, "2026-10-29") == [("2026-10-29", 0, 0)]
    assert [d for d, _, _ in funnel(state, days=3)] == sorted(d for d, _, _ in funnel(state, days=3))
    assert len(funnel(state, days=3)) == 3
