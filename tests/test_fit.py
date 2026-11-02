from types import SimpleNamespace

import anthropic
import httpx2

from scanner import fit
from scanner.notify import render

CONFIG = {"ai": {"enabled": True, "profile": "Backend developer, Laravel and Vue, wants product companies."},
          "search": {"include": ["Laravel", "Vue"]}, "eligibility": {"home": ["Portugal"]}}


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
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=80))


def fake_client(*results):
    return SimpleNamespace(messages=FakeMessages(results))


def job(n, **extra):
    return {"title": f"Developer {n}", "company": "Acme", "job_url": f"https://example.com/{n}",
            "description": "Laravel and Vue, remote in the EU.", **extra}


def good(score=5):
    return fit.Fit(score=score, reason="Laravel and Vue match; Kubernetes is missing.", salary="€60-75k a year",
                   work_policy="remote, EU only", seniority="senior")


def test_scores_each_job_once_and_logs_the_cost():
    jobs = [job(1), job(2, fit={"score": 3, "reason": "already scored"})]
    client, said = fake_client(good()), []
    assert fit.score_jobs(jobs, CONFIG, said.append, client=client) == 1
    assert jobs[0]["fit"]["score"] == 5 and jobs[1]["fit"]["reason"] == "already scored"
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["output_format"] is fit.Fit
    assert "Laravel and Vue, wants product companies" in call["system"] and "Developer 1" in call["messages"][0]["content"]
    assert "1 of 1 jobs scored" in said[-1] and "$" in said[-1]


def test_nothing_is_sent_when_off_without_a_profile_or_without_a_key(monkeypatch):
    client = fake_client(good())
    assert fit.score_jobs([job(1)], {**CONFIG, "ai": {**CONFIG["ai"], "enabled": False}}, print, client=client) == 0
    said = []
    assert fit.score_jobs([job(1)], {**CONFIG, "ai": {"enabled": True, "profile": " "}}, said.append, client=client) == 0
    assert "profile is empty" in said[-1]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    said = []
    assert fit.score_jobs([job(1)], CONFIG, said.append) == 0
    assert "ANTHROPIC_API_KEY is not set" in said[-1] and client.messages.calls == []


def test_only_the_configured_key_is_used(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-test-not-real")
    made = fit.client_for({"api_key_env": "MY_KEY"}, print)
    assert made.api_key == "sk-test-not-real"


def test_api_failures_leave_jobs_unscored_and_the_scan_going():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    refused = anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None)
    jobs, said = [job(1), job(2)], []
    assert fit.score_jobs(jobs, CONFIG, said.append, client=fake_client(refused, good())) == 0
    assert not any("fit" in j for j in jobs) and any("refused" in s for s in said)

    down = anthropic.APIConnectionError(request=request)
    jobs, said = [job(n) for n in range(5)], []
    assert fit.score_jobs(jobs, CONFIG, said.append, client=fake_client(down, good(4), down, down, good())) == 1
    assert any("keeps failing" in s for s in said)


def test_the_run_limit_leaves_the_rest_for_later():
    jobs, said = [job(n) for n in range(4)], []
    config = {**CONFIG, "ai": {**CONFIG["ai"], "max_jobs_per_run": 2}}
    assert fit.score_jobs(jobs, config, said.append, client=fake_client(good(), good())) == 2
    assert [("fit" in j) for j in jobs] == [True, True, False, False]


def test_the_email_lists_best_fits_first_with_the_reason():
    jobs = [job(1, fit={**good(3).model_dump()}), job(2, fit=good(5).model_dump()), job(3),
            job(4, fit=good(5).model_dump(), flags=["TypeScript/Python role: React"])]
    ordered = fit.order(jobs)
    assert [j["title"] for j in ordered] == ["Developer 2", "Developer 1", "Developer 3", "Developer 4"]
    _, text, body = render(ordered)
    assert text.startswith("[5/5] Developer 2 at Acme\n  remote, EU only · €60-75k a year · senior")
    assert "Laravel and Vue match; Kubernetes is missing." in text and "<i>Laravel and Vue match" in body
    assert "\nDeveloper 3 at Acme" in text  # unscored: as before
