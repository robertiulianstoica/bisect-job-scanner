from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from scanner import fit
from scanner.notify import render


@pytest.fixture
def config(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("Jane Doe\nSKILLS\nPHP, Laravel, Vue, PostgreSQL, Stripe\n")
    return {"ai": {"enabled": True, "cv": str(cv)}}


class FakeMessages:
    """Answers like messages.parse would, one queued result per call."""

    def __init__(self, results):
        self.results, self.calls = list(results), []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(parsed_output=result, stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=400, output_tokens=150,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=2000))


def fake_client(*results):
    return SimpleNamespace(messages=FakeMessages(results))


def job(n, **extra):
    return {"title": f"Developer {n}", "company": "Acme", "job_url": f"https://example.com/{n}",
            "description": "Laravel, Vue and Kubernetes; GraphQL is a plus. Remote in the EU.", **extra}


def reading(*skills):
    """A Reading from (name, required, in_cv) triples."""
    return fit.Reading(skills=[fit.Skill(name=n, required=r, in_cv=c) for n, r, c in skills],
                       salary="€60-75k a year", work_policy="remote, EU only", seniority="senior")


LARAVEL = reading(("Laravel", True, True), ("Vue", True, True), ("Kubernetes", True, False), ("GraphQL", False, False))


def test_coverage_counts_required_skills_like_an_ats():
    found = fit.coverage(LARAVEL.model_dump())
    assert (found["covered"], found["asked"], found["percent"]) == (2, 3, 67)
    assert found["missing"] == ["Kubernetes"] and found["missing_extra"] == ["GraphQL"]
    # An advert with only nice-to-haves: all of them count.
    found = fit.coverage(reading(("Docker", False, True), ("AWS", False, False)).model_dump())
    assert (found["covered"], found["asked"], found["missing"], found["missing_extra"]) == (1, 2, ["AWS"], [])


def test_reads_each_job_once_with_the_cv_cached(config):
    jobs = [job(1), job(2, coverage={"percent": 50, "already": True})]
    client, said = fake_client(LARAVEL), []
    assert fit.score_jobs(jobs, config, said.append, client=client) == 1
    assert jobs[0]["coverage"]["percent"] == 67 and jobs[1]["coverage"]["already"]
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["output_format"] is fit.Reading
    system = call["system"][0]
    assert "PHP, Laravel, Vue, PostgreSQL, Stripe" in system["text"] and system["cache_control"] == {"type": "ephemeral"}
    assert "Developer 1" in call["messages"][0]["content"]
    assert "1 of 1 jobs read" in said[-1] and "2000 from cache" in said[-1] and "$" in said[-1]


def test_nothing_is_sent_when_off_without_a_cv_or_without_a_key(config, monkeypatch):
    client = fake_client(LARAVEL)
    assert fit.score_jobs([job(1)], {"ai": {**config["ai"], "enabled": False}}, print, client=client) == 0
    said = []
    assert fit.score_jobs([job(1)], {"ai": {"enabled": True, "cv": "/no/such/cv.txt"}}, said.append, client=client) == 0
    assert "no CV text" in said[-1]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    said = []
    assert fit.score_jobs([job(1)], config, said.append) == 0
    assert "ANTHROPIC_API_KEY is not set" in said[-1] and client.messages.calls == []


def test_only_the_configured_key_is_used(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-test-not-real")
    assert fit.client_for({"api_key_env": "MY_KEY"}, print).api_key == "sk-test-not-real"


def test_api_failures_leave_jobs_unread_and_the_scan_going(config):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    refused = anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None)
    jobs, said = [job(1), job(2)], []
    assert fit.score_jobs(jobs, config, said.append, client=fake_client(refused, LARAVEL)) == 0
    assert not any("coverage" in j for j in jobs) and any("refused" in s for s in said)

    down = anthropic.APIConnectionError(request=request)
    jobs, said = [job(n) for n in range(5)], []
    assert fit.score_jobs(jobs, config, said.append, client=fake_client(down, LARAVEL, down, down, LARAVEL)) == 1
    assert any("keeps failing" in s for s in said)


def test_the_run_limit_leaves_the_rest_for_later(config):
    jobs = [job(n) for n in range(4)]
    config["ai"]["max_jobs_per_run"] = 2
    assert fit.score_jobs(jobs, config, print, client=fake_client(LARAVEL, LARAVEL)) == 2
    assert [("coverage" in j) for j in jobs] == [True, True, False, False]


def test_the_email_leads_with_coverage_best_first():
    full = reading(("Laravel", True, True), ("Vue", True, True))
    as_read = lambda r: {**r.model_dump(), **fit.coverage(r.model_dump())}  # noqa: E731
    jobs = [job(1, coverage=as_read(LARAVEL)), job(2, coverage=as_read(full)), job(3),
            job(4, coverage=as_read(full), flags=["TypeScript/Python role: React"])]
    ordered = fit.order(jobs)
    assert [j["title"] for j in ordered] == ["Developer 2", "Developer 1", "Developer 3", "Developer 4"]
    _, text, body = render(ordered)
    assert text.startswith("Skills 2 of 2 (100%)\nDeveloper 2 at Acme\n  remote, EU only · €60-75k a year · senior")
    assert "Skills 2 of 3 (67%) · missing: Kubernetes · nice to have, missing: GraphQL\nDeveloper 1" in text
    assert "<b>Skills 2 of 3 (67%) · missing: Kubernetes" in body
    assert "\nDeveloper 3 at Acme" in text  # unread: as before
