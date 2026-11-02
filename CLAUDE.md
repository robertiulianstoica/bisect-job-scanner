# bisect-job-scanner

A JobSpy fork (`jobspy/`) with a job scanner on top (`scanner/`). The scanner
finds jobs; the applications sent are tracked in Bisect through its MCP server
(`.mcp.json`; the user signs in with `/mcp`). README.md has the setup.

## Personal data

Everything personal lives in the profile directory, `$JOB_SCANNER_HOME` (by default `.job-scanner` in your home folder):
`config.toml`, `env`, `state.sqlite3`, `pending.json`, logs, `backups/`.

- Never print, copy or commit `env`: it holds the SMTP password and the user's
  Anthropic API key. To check a key is set, test that the variable is non-empty;
  never show it.
- Never write to `state.sqlite3` except through the commands below, and never
  replace it; `python -m scanner.backup --restore` exists for that.
- Nothing from the profile directory goes into the repository; the pre-commit
  check (`.githooks/pre-commit`) refuses it.

## When the user wants to apply to a job

1. Find the job, and pick the CV version as in steps 1 and 2 below.
2. Record the application with `bisect_create_application` (step 3 below). It
   is what the PDF is made for: each application has its own tracking link.
3. Fetch the PDF to send with `bisect_get_application_pdf` and that id, and
   save it under the profile directory (`$JOB_SCANNER_HOME/applications/`),
   never in the repository. Never fetch `trackingPdfUrl`: that is the
   company's link, and opening it counts as the company reading the CV.
4. Check it before it goes out, and show the user the result:
   `.venv/bin/python -m scanner.ats <pdf> --job <job url> --id <application id>`
   (or `--advert <file>` for a job the scanner has not read). Problems in the
   text layer are worth fixing first. Missing skills are questions for the
   user, never edits: the CV is not changed to match an advert. If they have
   the experience, it goes into the CV in Bisect with its evidence; if not,
   the letter says so.
5. If the user decides not to send it after all, set the application's
   `outcome` to `withdrawn` (applications cannot be deleted).
6. Once sent: `scanner.triage set <url> applied --bisect <id>`.

For the market rather than one job, `scanner.gap --cv <pdf> [--grep laravel]`
lists the skills the adverts emailed lately ask for, and how often the CV names
each.

## When the user says they applied to a job

1. Find the job: `.venv/bin/python -m scanner.triage list --all`, or
   `scanner.jobs --days 7 --grep <company>`. A job found outside the scanner:
   `scanner.triage add --title T --company C --url U` first.
2. Pick the CV version it was sent with: `bisect_list_variants`. If it is not
   obvious which one, ask; never guess.
3. Record it with `bisect_create_application`: `company`, `variant`,
   `positions` (the job title), `url` (the advert), `sentAt` (today unless told
   otherwise), `channel` (`direct` unless told it went through an agency or a
   referral), and where the advert says so `locationPolicy`, `roleLevel` and
   `coreStack`. Leave `shared` alone unless asked.
4. Link the two with the id Bisect returned:
   `.venv/bin/python -m scanner.triage set <url> applied --bisect <id>`.

Later news (a reply, a screening, an interview, a rejection) goes to
`bisect_update_application` with that id (`scanner.triage list --all` shows
it, as does `bisect_list_applications`): `stage` only moves forward, and how
it ended is `outcome`. A reply also sets `lastContactAt`.

## Verdicts and the funnel

Verdicts on jobs worth a look: `scanner.triage set <url|key|words>
shortlist|maybe|later|out "<reason>"`.

The top of Bisect's funnel is the scanner's own numbers:
`.venv/bin/python -m scanner.triage funnel --days 7` prints, per day, the jobs
found and how many got shortlist, maybe or applied. Send each line with
`bisect_record_job_scan` (`day`, `found`, `relevant`); recording a day again
replaces it, so resending a week after a triage session is safe.

## Working on the code

- The skill coverage (`scanner/fit.py`) calls Claude Haiku 5.5 with the key
  from `[ai] api_key_env` only, and the CV text at `[ai] cv`. It must never drop
  a job, change the CV or fail a scan; its tests use a fake client, so they
  need no key and no network. A job's reading is in the email and in
  `pending.json` until it is sent.

- Tests: `.venv/bin/python -m pytest -q tests` (no network).
- The rules are tested against `tests/fixtures/config.toml`, not anyone's config.
- `scanner/launchd/run.sh` is what the scheduled scan runs: do not break it.
