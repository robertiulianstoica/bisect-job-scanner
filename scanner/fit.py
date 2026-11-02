"""How much of each emailed job your CV covers, read by Claude (optional).

With [ai] enabled in the config, your CV as text ([ai] cv) and your own
Anthropic API key in the env file, every job that passed the rules is read by
Claude Haiku 5.5 next to your CV, once, before it waits for the next email.
It lists every skill the advert asks for and whether your CV shows it (by name
or a clear equivalent), the way an ATS keyword filter would, and the email
leads with the share of required skills covered:

    Skills 7 of 9 (78%) · missing: Rust, Kubernetes · nice to have, missing: GraphQL
    Senior Backend Developer at Acme
      remote, EU only · €60-75k a year · senior · ...

The email lists the best-covered jobs first. Coverage only orders and
annotates: it never drops a job the rules kept, and when the API cannot be
reached the email goes out as before.

Sent to the API: your CV text, once per run (then cached), and for each job its
title, company, location and advert text. Nothing else. Only the key named by
[ai] api_key_env is used; without it, nothing is read.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DEFAULT_MODEL = "claude-haiku-5-5"
# Dollars per million tokens: input, cache write, cache read, output. Haiku 5.5's
# prices are for prompts up to 100,000 tokens; a CV and an advert stay well below.
PRICES = {"claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50), "claude-haiku-4-5": (1.0, 1.25, 0.10, 5.0)}

INSTRUCTIONS = """You read a job advert the way an applicant tracking system (ATS) does, against the candidate's CV below.

List every skill the advert asks for: languages, frameworks, tools, platforms, practices,
domains, spoken languages, certifications. One entry per skill, named briefly as the
advert names it. Leave out personality traits ("team player") and generic phrases.

For each one:
- required: true when the advert requires it, false when it is a plus or nice to have.
- in_cv: true only when the CV shows it, by name or by a clear equivalent (Stripe for
  "payment providers", PostgreSQL for "SQL databases"). Never assume a skill the CV does
  not show.

Also give, as the advert states them:
- salary: the pay with currency and period (e.g. "€60-75k a year"); null when it states none. Never estimate.
- work_policy: remote, hybrid or on-site, and where candidates may live, in a few words (e.g. "remote, EU only"); null when it says nothing.
- seniority: the level asked for, or "unclear"."""


class Skill(BaseModel):
    name: str
    required: bool
    in_cv: bool


class Reading(BaseModel):
    skills: list[Skill]
    salary: str | None
    work_policy: str | None
    seniority: Literal["junior", "mid", "senior", "lead", "staff", "unclear"]


def coverage(reading: dict) -> dict:
    """The ATS-style numbers from a reading: required skills covered, and what is missing."""
    skills = reading.get("skills") or []
    required = [s for s in skills if s["required"]] or skills  # an advert with no must-haves: count them all
    covered = sum(1 for s in required if s["in_cv"])
    return {
        "covered": covered,
        "asked": len(required),
        "percent": round(100 * covered / len(required)) if required else None,
        "missing": [s["name"] for s in required if not s["in_cv"]],
        "missing_extra": [s["name"] for s in skills if not s["required"] and not s["in_cv"] and s not in required],
    }


def cv_text(settings: dict) -> str:
    path = Path(settings.get("cv", "")).expanduser()
    return path.read_text(errors="replace").strip() if settings.get("cv") and path.is_file() else ""


def advert(job: dict) -> str:
    return (f"Title: {job.get('title')}\nCompany: {job.get('company')}\n"
            f"Location: {job.get('location') or 'not stated'}\n\n{job.get('description') or '(no advert text)'}")


def client_for(settings: dict, log):
    """An Anthropic client with the key from the env file, or None (logged) when it cannot be made."""
    key = os.environ.get(settings.get("api_key_env", "ANTHROPIC_API_KEY"))
    if not key:
        log(f"coverage: {settings.get('api_key_env', 'ANTHROPIC_API_KEY')} is not set in the env file; jobs not read")
        return None
    try:
        import anthropic
    except ImportError:
        log("coverage: the anthropic package is missing (run ./setup.sh again); jobs not read")
        return None
    # The key is passed explicitly: no other credential on this machine is ever used.
    return anthropic.Anthropic(api_key=key, timeout=60.0)


def score_jobs(jobs: list[dict], config: dict, log, client=None) -> int:
    """Adds job["coverage"] to each job that has none. Returns how many were read."""
    settings = config.get("ai", {})
    todo = [job for job in jobs if "coverage" not in job]
    if not settings.get("enabled") or not todo:
        return 0
    cv = cv_text(settings)
    if not cv:
        log(f"coverage: no CV text at [ai] cv ({settings.get('cv') or 'not set'}); jobs not read")
        return 0
    client = client or client_for(settings, log)
    if client is None:
        return 0
    import anthropic

    model = settings.get("model", DEFAULT_MODEL)
    limit = settings.get("max_jobs_per_run", 60)
    if len(todo) > limit:
        log(f"coverage: {len(todo)} jobs to read, {limit} this run ([ai] max_jobs_per_run); the rest next run")
        todo = todo[:limit]
    # The CV is the same for every job: cached after the first request of the run.
    system = [{"type": "text", "text": INSTRUCTIONS + "\n\nThe candidate's CV:\n\n" + cv,
               "cache_control": {"type": "ephemeral"}}]
    extra = {"output_config": {"effort": settings["effort"]}} if settings.get("effort") else {}
    read, failures = 0, 0
    tokens = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    for job in todo:
        try:
            response = client.messages.parse(
                model=model, max_tokens=8192, system=system,
                messages=[{"role": "user", "content": advert(job)}], output_format=Reading, **extra,
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            log(f"coverage: the API key was refused ({error.status_code}); jobs not read")
            break
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as error:
            failures += 1
            if failures >= 3:
                log(f"coverage: the API keeps failing ({type(error).__name__}); the rest wait for the next run")
                break
            continue
        usage = response.usage
        tokens["input"] += usage.input_tokens
        tokens["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        tokens["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        tokens["output"] += usage.output_tokens
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            continue  # a refusal or a cut-off answer: left unread, tried again next run
        reading = response.parsed_output.model_dump()
        job["coverage"] = {**reading, **coverage(reading)}
        read += 1
    prices = PRICES.get(model, (0.0, 0.0, 0.0, 0.0))
    cost = sum(tokens[k] / 1e6 * p for k, p in zip(("input", "cache_write", "cache_read", "output"), prices))
    log(f"coverage: {read} of {len(todo)} jobs read by {model}; tokens {tokens['input']} in, "
        f"{tokens['cache_read']} from cache, {tokens['cache_write']} cached, {tokens['output']} out (~${cost:.3f})")
    return read


def headline(job: dict) -> str | None:
    """The email's first line for a job: "Skills 7 of 9 (78%) · missing: ...", or None when unread."""
    found = job.get("coverage")
    if not found or found.get("percent") is None:
        return None
    line = f"Skills {found['covered']} of {found['asked']} ({found['percent']}%)"
    if found["missing"]:
        line += " · missing: " + ", ".join(found["missing"])
    if found["missing_extra"]:
        line += " · nice to have, missing: " + ", ".join(found["missing_extra"])
    return line


def order(jobs: list[dict]) -> list[dict]:
    """The email's order: main-stack roles before TypeScript/Python-only ones, best covered first in each."""
    def secondary(job):
        return any(str(f).startswith("TypeScript/Python role") for f in job.get("flags") or [])

    def percent(job):
        value = (job.get("coverage") or {}).get("percent")
        return -1 if value is None else value
    return sorted(jobs, key=lambda j: (secondary(j), -percent(j)))
