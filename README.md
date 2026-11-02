# bisect-job-scanner

A job scanner for [Bisect](https://bisect.eu) users. It reads company career
sites, job boards and LinkedIn every 30 minutes, keeps the roles that match
your stack and the places you can work from, and emails you the new ones,
usually within half an hour of their being posted. With your own Anthropic API
key, Claude checks every skill each advert asks for against your CV, like an
ATS, so the jobs you cover best come first. The applications you send are tracked in Bisect through its MCP server.

It is a fork of [JobSpy](https://github.com/cullenwatson/JobSpy) (MIT): the
scraping library in `jobspy/` comes from there, with new sources added; its own
documentation is upstream.

## What it does

- **Finds jobs early.** It reads companies' own career sites (Greenhouse,
  Ashby, Lever, Workday and more) directly, so a role shows up as soon as it is
  published, before it is syndicated to LinkedIn or the aggregators. Every
  company board seen in a LinkedIn or Himalayas result is added to the
  rotation, so the list of companies read grows by itself.
- **Screens them for you.** A job must mention your stack, be workable from
  where you are (your country and cities, a region that includes you, or
  another country as a contractor), stay under an applicant limit, and avoid
  the titles, industries and companies you exclude. TypeScript/Python-only
  roles can be held to a second bar: they must match your strengths.
- **Emails the new ones** at the hours you choose (08:00 and 14:00 by
  default), through any SMTP server; between those hours they wait in a queue,
  so nothing is lost.
- **AI skill coverage (optional):** with your own Anthropic API key, Claude
  Haiku 5.5 reads every job before it is emailed, lists every skill the advert
  asks for and checks each against your CV, the way an ATS does: "Skills 12 of
  18 (67%) · missing: Liquid, Remix". It also reads the pay, remote policy and
  level as the advert states them. The best-covered jobs come first; a
  systems-administration role that slipped past the rules sinks to the bottom.
  About $3-4 a month ([details](#skill-coverage-with-claude-optional)).
- **Keeps your verdicts:** shortlist, maybe, later, applied or out, with a
  reason, and whether the jobs you kept are still open (`scanner.triage`).
- **Tracks applications in Bisect:** from Claude Code, "I applied to Acme"
  records the application against the CV version you sent and links it to the
  job; the scanner's daily numbers fill the top of Bisect's funnel.
- **Checks your CV against the job before you apply:** `scanner.ats` reads
  the PDF the way an ATS parser does (text layer, contact details as text,
  section headings, your name at the top, Bisect's tracking link) and scores
  it against the advert: which of the skills it asks for your CV names, and
  which it never does. `scanner.gap` does the same across every advert you
  were sent: the skills the market keeps asking for that your CV is missing
  or mentions only once. With Bisect, the PDF checked is the very one you
  send, fetched through its MCP server.
- **Checks adverts before you apply:** `scanner.vet` reports the signs of an
  advert that exists only to collect CVs: a recently registered company
  domain, one advert cloned across many countries, a company site that does
  not link to the board. It reports; you decide.
- **Counts the market:** every job read is kept, with its stack, pay and work
  mode, for a local dashboard of open jobs, pay and demand by language and
  region (`scanner.market`, `/market` on the review server).
- **Backs itself up** every night, and keeps all your data outside the
  repository.

## Where it searches

| Kind | Sources |
|---|---|
| Company career sites | Greenhouse, Ashby, Lever, Workday, Workable, SmartRecruiters, Teamtailor, Recruitee, Personio, Gem, Rippling |
| Searches across companies | LinkedIn (remote, per country or region, with applicant counts), Himalayas (remote, by the country you work from), Workable's job search, Welcome to the Jungle, Hacker News "Who is hiring?", Remote Rocketship |
| Stack-specific boards | LaraJobs (Laravel), symfony.com/jobs (Symfony) |
| Regional boards | No Fluff Jobs (Poland and Central Europe), Djinni (Ukraine and Eastern Europe); in Romania: eJobs, BestJobs, Hipo, peviitor.ro, joburiit.ro, devjob.ro, phpjobs.ro |

All of them are read through public APIs, feeds or pages: no browser, no
login. Each source is switched on and off in your config, and company boards
are added by name (`scanner.run --add-board greenhouse <company>`).

## Quick start

macOS with Python 3.11 or later. About ten minutes, most of it the first scan.
For the CV checks, also poppler (`brew install poppler`).

**1. Install.**

```bash
git clone https://github.com/robertiulianstoica/bisect-job-scanner.git
cd bisect-job-scanner
./setup.sh
```

This makes the venv, and your own profile folder `~/.job-scanner/` with a
config to edit and an empty `env` for the email password. Nothing personal
ever goes in the repository.

**2. Say what you are looking for.** Open `~/.job-scanner/config.toml`; each
field is explained in place. Change at least:

| Field | What to put |
|---|---|
| `[search]` `terms`, `include` | your stack, e.g. `'"Laravel" OR "Vue"'` and `["Laravel", "PHP", "Vue"]` |
| `[eligibility]` `home`, `home_cities` | the country you live in, and the cities where on-site or hybrid is fine |
| `[eligibility]` `contract_ok` | other countries you would work for as a contractor |
| `[email]` `to` | where the jobs are sent |
| `[[linkedin.searches]]` `location`, `[himalayas]` `country` | your country |

The scanner will not start while any of the example's placeholders
(`Your Country`, `Your City`, `you@example.com`) are left, and names the ones it found.

**3. Try it.**

```bash
.venv/bin/python -m scanner.run --dry-run
```

This reads every source once (a few minutes), prints the email it would send,
and remembers nothing. Not what you want? Adjust `include`, `exclude_titles`
and `[eligibility]`, and run it again.

**4. Set up the email.** Put the SMTP details in `~/.job-scanner/env` (never
in the config or the repository). With Gmail, turn on 2-step verification,
create an app password at <https://myaccount.google.com/apppasswords>, and
write the two lines with your address and that password (16 letters, no
spaces); the `@` in the user name is written `%40`:

```bash
export JOB_SCANNER_MAILER_DSN='smtp://<you>%40gmail.com:<app password>@smtp.gmail.com:587'
export JOB_SCANNER_MAIL_FROM='Job scanner <<you>@gmail.com>'
```

Any other SMTP server works the same way: `smtp://<user>:<password>@<host>:587`,
or `smtps://` for port 465. Until the email works, the jobs found wait in a
queue and none are lost.

**5. Run it every 30 minutes.**

```bash
scanner/launchd/install.sh
```

It scans every half hour and emails what is new at 08:00 and 14:00 (`[run]
send_hours`), and backs up your data every night at 03:00. Logs:
`~/.job-scanner/scan.log`. To stop it: `scanner/launchd/uninstall.sh`.

**6. Track your applications in Bisect.** Make a [Bisect](https://bisect.eu)
account and add your CV there (at least one version: every application is
recorded against the version it was sent with). Then open this folder in
Claude Code: it offers the Bisect server from `.mcp.json`; accept it, run
`/mcp` and sign in. From then on, telling Claude "I applied to the Acme
backend role" records the application in Bisect and links it to the job here;
see [Tracking applications with Bisect](#tracking-applications-with-bisect).

On Linux everything but step 5 works; schedule the scan with cron instead:
`*/30 * * * * cd ~/bisect-job-scanner && zsh scanner/launchd/run.sh >> ~/.job-scanner/scan.log 2>&1`
(and `scanner/launchd/backup.sh` once a day).

<img src="https://github.com/cullenwatson/JobSpy/assets/78247585/ae185b7e-e444-4712-8bb9-fa97f53e896b" width="400">

**JobSpy** is a job scraping library with the goal of aggregating all the jobs from popular job boards with one tool.

## Everyday commands

```bash
.venv/bin/python -m scanner.jobs --days 3                  # what was emailed lately
.venv/bin/python -m scanner.jobs --rejected --grep laravel # what the rules turned down, and why
.venv/bin/python -m scanner.triage list                    # your shortlist, maybe and later
.venv/bin/python -m scanner.triage set <url> shortlist "remote, good stack"
.venv/bin/python -m scanner.triage check                   # are the jobs you kept still open?
.venv/bin/python -m scanner.triage funnel --days 7         # per day: found, and worth a look
.venv/bin/python -m scanner.vet <job url>                  # is this advert from a real employer?
.venv/bin/python -m scanner.ats cv.pdf --job <job url>     # ATS check of your CV, and its skill coverage for that job
.venv/bin/python -m scanner.gap --cv cv.pdf --grep laravel # skills the adverts ask for that your CV lacks
.venv/bin/python -m scanner.market                         # pay by language, from the adverts read
.venv/bin/python -m scanner.run --add-board greenhouse <company>
```

## Skill coverage with Claude (optional)

Each job that passes your rules can be read by Claude Haiku 5.5 next to your
CV, the way an applicant tracking system reads it: every skill the advert asks
for, required or nice to have, checked against what your CV shows (by name or a
clear equivalent). The email leads each job with the share of required skills
covered, and lists the best-covered jobs first:

```text
Skills 12 of 18 (67%) · missing: Liquid, Polaris UI, Remix · nice to have, missing: ADA guidelines
Shopify Developer at Hivex
  remote, worldwide · mid · posted 3 h ago · himalayas · Worldwide
  https://...
```

1. Create your own API key at <https://console.anthropic.com/settings/keys>
   and put it in `~/.job-scanner/env`, next to the SMTP password:
   `export ANTHROPIC_API_KEY='<your key>'`. Each person uses their own key; it
   never goes in the config (which is backed up) or the repository (the
   pre-commit check refuses it).
2. Save your CV as plain text in the profile directory, from the PDF you send:
   `pdftotext cv.pdf ~/.job-scanner/cv.txt` (with Bisect, the PDF of your
   current version). Replace the file when your CV changes.
3. In `~/.job-scanner/config.toml`, set `[ai] enabled = true`.
4. Try it with `scanner.run --dry-run`: the email it prints carries the coverage.

- **Cost:** each job is read once (a job already queued keeps its reading), and
  the CV is cached between jobs: about $0.002 a job with Claude Haiku 5.5,
  roughly $3-4 a month at 70 jobs a day (`[ai] effort = "low"` costs less,
  with a less careful reading). Each scan's `scan.log` line gives the tokens
  and the cost; `max_jobs_per_run` caps one run.
- **What is sent to Anthropic:** your CV text, and per job its title, company,
  location and advert text. Not your verdicts or your email address.
- **What it never does:** drop a job, or change your CV. Coverage only orders
  and annotates the email; without a key or a CV, or when the API cannot be
  reached, the email goes out as before. For one job in depth, with the PDF's
  text layer checked too, use `scanner.ats`.

## Tracking applications with Bisect

Finding jobs works on its own. Tracking what you do with them is built on
[Bisect](https://bisect.eu), and needs:

1. **A Bisect account** at [bisect.eu](https://bisect.eu), with your CV and at
   least one version of it: Bisect keeps the version sent to each company, and
   every application with its stage and outcome.
2. **The Bisect MCP server in Claude Code.** This repository's `.mcp.json`
   declares it (`https://bisect.eu/api/mcp`, no token in the file): open the
   folder in Claude Code, approve the `bisect` server, run `/mcp` and sign in
   to your account. To have it in every folder instead:

   ```bash
   claude mcp add --scope user --transport http bisect https://bisect.eu/api/mcp
   ```

Nothing in the scanner calls Bisect by itself: Claude Code does, following
`CLAUDE.md`. In practice:

- **"I want to apply to <company>"**: Claude records the application in
  Bisect against the CV version you choose, fetches that application's PDF
  through the MCP server (`bisect_get_application_pdf`: the file to attach,
  with the application's own tracking link; fetching it records nothing,
  unlike opening the tracking link itself), saves it in your profile
  directory and checks it against the advert:

  ```bash
  .venv/bin/python -m scanner.ats <the PDF> --job <job url> --id <Bisect application id>
  ```

  You see whether an ATS parses it cleanly, which skills the advert asks for
  that it names, and which are missing, before you send it. A missing skill
  is a question, not an instruction: if you have the experience, add it to
  your CV in Bisect with its evidence; if not, say so in the letter.
- **"I applied to <company>"**: Claude finds the job (`scanner.triage`), asks
  which CV version it went with if that is not clear, records the application
  in Bisect (company, role, advert link, date, channel) and stores the id it
  gets back with your verdict:

  ```bash
  .venv/bin/python -m scanner.triage set <job url> applied --bisect <Bisect application id>
  ```

- **"They replied" / "screening on Monday" / "rejected"**: the same
  application moves forward in Bisect (stage, last contact, outcome).
- **The funnel**: `scanner.triage funnel --days 7` prints, per day, the jobs
  the scanner found and how many you marked shortlist, maybe or applied; ask
  Claude to send them to Bisect and they fill the top of its funnel.
- A job found outside the scanner: `scanner.triage add --title T --company C --url U`,
  then the same as above.

The review screen below shows each application's Bisect id next to the
letter and CV that were sent.

## Where your data lives

Everything personal is in one profile directory outside the repository,
`$JOB_SCANNER_HOME` (default `~/.job-scanner`):

| File | What |
|---|---|
| `config.toml` | your searches, places, email address |
| `env` | secrets: the SMTP DSN and sender, your Anthropic API key (mode 600) |
| `state.sqlite3` | jobs seen, boards found, postings, your triage verdicts, market history |
| `pending.json` | jobs waiting for the next send hour |
| `scan.log`, `backup.log` | what the launchd agents did |
| `backups/` | see below |

The config is read from `$JOB_SCANNER_HOME/config.toml`; an older setup with
only `scanner/config.toml` keeps working, and the first line of each scan in
`scan.log` names the file read.

A job is only marked seen once it has been emailed. Between `send_hours` scans
only queue what they find in `pending.json`; the first scan after a send hour
emails the whole queue in one message, and a failed send leaves it queued.

## Backups and restore

```bash
.venv/bin/python -m scanner.backup            # what the daily agent runs
.venv/bin/python -m scanner.backup --list
.venv/bin/python -m scanner.backup --restore ~/.job-scanner/backups/full/state-2026-10-31.sqlite3.gz --to /tmp/state.sqlite3
.venv/bin/python -m scanner.backup --restore ~/.job-scanner/backups/precious/2026-10-31 --to /tmp/precious.sqlite3
```

- `backups/full/state-<day>.sqlite3.gz`: the whole database, copied with
  SQLite's online backup API (safe while a scan writes) and checked with
  `PRAGMA integrity_check`; the last 7 days and the last 4 Sundays are kept.
- `backups/precious/<day>/`: what cannot be read again from the web (your
  triage verdicts, the daily market history, companies, boards, seen jobs) as
  JSONL, with their schema, a copy of the config and a manifest of row counts;
  30 days are kept. Set `[backup] offsite_dir` to copy them off this disk as
  well (an iCloud Drive folder, or a private git repository you commit).
- The env file is never backed up: keep the SMTP password in your password manager.
- `--restore` writes to `--to`; it replaces the live database only with
  `--force`, when no scan holds the lock, and keeps the old file beside it.

## Never commit

`config.toml`, `env` or any `.env*`, `*.sqlite3*`, `pending.json`, logs and
`backups/` are in `.gitignore`. The pre-commit check (`.githooks/pre-commit`,
enabled by `setup.sh`) also refuses staged database files and added lines with
an `smtp://` URL, a `JOB_SCANNER_MAILER_DSN=` value, an Anthropic API key or a
`~/.job-scanner` path.

## Reviewing the applications sent (optional)

Off unless `[review] jobs_dir` points at a jobs folder in the layout
`scanner/review.py` describes.

```bash
.venv/bin/python -m scanner.review          # http://127.0.0.1:8790, --jobs <folder> --port <n>
                                            # market dashboard at http://127.0.0.1:8790/market
```

A local page over the jobs folder's `direct/letters/`: each application with
its form answers and letter, the CV and cover letters uploaded
(`letters/sent/<name>/`), and the advert as saved. The rating and notes typed
there are written to `direct/feedback/<name>.md`, which the next application
reads first. PDFs are drawn to canvas, so their tracking links cannot be
clicked.

`/market` on the same server is the Stack & Pay dashboard (dashboard/market.html),
rebuilt from the scanner's database on every load: open jobs, pay and demand
by language, by region. It replaced a published artifact on 2026-10-04 and is
local only; `python -m scanner.metrics --dashboard <file>` still writes a
standalone copy.
