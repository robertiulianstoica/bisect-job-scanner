"""How well each job in the email fits you, scored by Claude (optional).

With [ai] enabled in the config and your own Anthropic API key in the env file,
every job that passed the rules is read by Claude Haiku 5.5 together with your
profile, once, before it waits for the next email:

    [5/5] Senior Laravel Developer at Acme  (remote, EU only · €60-75k a year · senior)
          Laravel and Vue with Stripe payments match you closely; asks for Kubernetes, which you do not list.

The email lists the best fits first. The score only orders and annotates: it
never drops a job the rules kept, and when the API cannot be reached the email
goes out as before, unscored.

Sent to the API for each job: its title, company, location and advert text,
with your [ai] profile and the stack and places in your config. Nothing else
(no CV, no verdicts, no email address). Only the key named by
[ai] api_key_env is used; without it, nothing is scored.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel

DEFAULT_MODEL = "claude-haiku-5-5"
# Dollars per million tokens (input, output), for the cost line in scan.log. Haiku 5.5's
# price is for prompts up to 100,000 tokens; one advert and a profile stay far below.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5": (2.0, 10.0)}

INSTRUCTIONS = """You compare one job advert with a developer's profile and say how well it fits them.

score, from the advert as written:
5 = a strong fit, worth applying to today
4 = a good fit with a minor doubt
3 = possible, with a clear gap or doubt
2 = a weak fit
1 = not a fit

reason: one sentence of at most 30 words, in English, addressed to the developer as "you": the strongest overlap, then the biggest gap or doubt.
salary: the pay as the advert states it, with currency and period (e.g. "€60-75k a year"); null when it states none. Never estimate.
work_policy: what the advert says about remote, hybrid or on-site, and where candidates may live, in a few words (e.g. "remote, EU only"); null when it says nothing.
seniority: the level the advert asks for, or "unclear".

The scanner's rules have already checked the stack and the location; judge the rest: the work itself, the level, the domain, and the profile's preferences."""


class Fit(BaseModel):
    score: Literal[1, 2, 3, 4, 5]
    reason: str
    salary: str | None
    work_policy: str | None
    seniority: Literal["junior", "mid", "senior", "lead", "staff", "unclear"]


def profile_text(config: dict) -> str:
    """The developer, as the model sees them: their own words, then the config's facts."""
    search, places = config.get("search", {}), config.get("eligibility", {})
    facts = [
        ("Stack they want", ", ".join(search.get("include", []))),
        ("Titles they look for", ", ".join(search.get("title_terms", []))),
        ("Lives in", ", ".join(places.get("home", []) + places.get("home_cities", []))),
        ("Works as a contractor for", ", ".join(places.get("contract_ok", []))),
        ("Avoids", ", ".join(search.get("exclude", []))),
    ]
    return config.get("ai", {}).get("profile", "").strip() + "\n\n" + "\n".join(f"{k}: {v}" for k, v in facts if v)


def advert(job: dict) -> str:
    return (f"Title: {job.get('title')}\nCompany: {job.get('company')}\n"
            f"Location: {job.get('location') or 'not stated'}\n\n{job.get('description') or '(no advert text)'}")


def client_for(settings: dict, log):
    """An Anthropic client with the key from the env file, or None (logged) when it cannot be made."""
    key = os.environ.get(settings.get("api_key_env", "ANTHROPIC_API_KEY"))
    if not key:
        log(f"fit: {settings.get('api_key_env', 'ANTHROPIC_API_KEY')} is not set in the env file; jobs not scored")
        return None
    try:
        import anthropic
    except ImportError:
        log("fit: the anthropic package is missing (run ./setup.sh again); jobs not scored")
        return None
    # The key is passed explicitly: no other credential on this machine is ever used.
    return anthropic.Anthropic(api_key=key, timeout=60.0)


def score_jobs(jobs: list[dict], config: dict, log, client=None) -> int:
    """Adds job["fit"] to each job that has none. Returns how many were scored."""
    settings = config.get("ai", {})
    todo = [job for job in jobs if "fit" not in job]
    if not settings.get("enabled") or not todo:
        return 0
    if not settings.get("profile", "").strip():
        log("fit: [ai] profile is empty in the config; jobs not scored")
        return 0
    client = client or client_for(settings, log)
    if client is None:
        return 0
    import anthropic

    model = settings.get("model", DEFAULT_MODEL)
    limit = settings.get("max_jobs_per_run", 60)
    if len(todo) > limit:
        log(f"fit: {len(todo)} jobs to score, {limit} this run ([ai] max_jobs_per_run); the rest next run")
        todo = todo[:limit]
    system = INSTRUCTIONS + "\n\nThe developer:\n" + profile_text(config)
    # The model thinks before scoring by default; [ai] effort = "low" trades some judgement for less cost.
    extra = {"output_config": {"effort": settings["effort"]}} if settings.get("effort") else {}
    scored, tokens_in, tokens_out, failures = 0, 0, 0, 0
    for job in todo:
        try:
            response = client.messages.parse(
                model=model, max_tokens=4096, system=system,
                messages=[{"role": "user", "content": advert(job)}], output_format=Fit, **extra,
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            log(f"fit: the API key was refused ({error.status_code}); jobs not scored")
            break
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as error:
            failures += 1
            if failures >= 3:
                log(f"fit: the API keeps failing ({type(error).__name__}); the rest wait for the next run")
                break
            continue
        tokens_in += response.usage.input_tokens
        tokens_out += response.usage.output_tokens
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            continue  # a refusal or a cut-off answer: left unscored, tried again next run
        job["fit"] = response.parsed_output.model_dump()
        scored += 1
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    cost = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    log(f"fit: {scored} of {len(todo)} jobs scored by {model}, {tokens_in} tokens in, {tokens_out} out (~${cost:.3f})")
    return scored


def order(jobs: list[dict]) -> list[dict]:
    """The email's order: main-stack roles before TypeScript/Python-only ones, best fits first in each."""
    def secondary(job):
        return any(str(f).startswith("TypeScript/Python role") for f in job.get("flags") or [])
    return sorted(jobs, key=lambda j: (secondary(j), -((j.get("fit") or {}).get("score") or 0)))
