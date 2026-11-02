> **bisect-job-scanner** is the job scanner for [Bisect](https://bisect.eu) users:
> a fork of JobSpy that adds company job boards and remote-jobs boards, and a
> scanner on top that emails you new roles within half an hour of their being
> posted. Start with the [quick start](#quick-start) below; the scanner's full
> documentation is in [Bisect job scanner](#bisect-job-scanner), and the rest
> of this README is upstream JobSpy's.

## Quick start

macOS with Python 3.11 or later. About ten minutes, most of it the first scan.

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

## Features

- Scrapes job postings from **LinkedIn**, **Indeed**, **Glassdoor**, **Google**, **ZipRecruiter**, & other job boards concurrently
- Aggregates the job postings in a dataframe
- Proxies support to bypass blocking

![jobspy](https://github.com/cullenwatson/JobSpy/assets/78247585/ec7ef355-05f6-4fd3-8161-a817e31c5c57)

### Installation

```
pip install -U python-jobspy
```

_Python version >= [3.10](https://www.python.org/downloads/release/python-3100/) required_

### Usage

```python
import csv
from jobspy import scrape_jobs

jobs = scrape_jobs(
    site_name=["indeed", "linkedin", "zip_recruiter", "google"], # "glassdoor", "bayt", "naukri", "bdjobs"
    search_term="software engineer",
    google_search_term="software engineer jobs near San Francisco, CA since yesterday",
    location="San Francisco, CA",
    results_wanted=20,
    hours_old=72,
    country_indeed='USA',
    
    # linkedin_fetch_description=True # gets more info such as description, direct job url (slower)
    # proxies=["208.195.175.46:65095", "208.195.175.45:65095", "localhost"],
)
print(f"Found {len(jobs)} jobs")
print(jobs.head())
jobs.to_csv("jobs.csv", quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False) # to_excel
```

### Output

```
SITE           TITLE                             COMPANY           CITY          STATE  JOB_TYPE  INTERVAL  MIN_AMOUNT  MAX_AMOUNT  JOB_URL                                            DESCRIPTION
indeed         Software Engineer                 AMERICAN SYSTEMS  Arlington     VA     None      yearly    200000      150000      https://www.indeed.com/viewjob?jk=5e409e577046...  THIS POSITION COMES WITH A 10K SIGNING BONUS!...
indeed         Senior Software Engineer          TherapyNotes.com  Philadelphia  PA     fulltime  yearly    135000      110000      https://www.indeed.com/viewjob?jk=da39574a40cb...  About Us TherapyNotes is the national leader i...
linkedin       Software Engineer - Early Career  Lockheed Martin   Sunnyvale     CA     fulltime  yearly    None        None        https://www.linkedin.com/jobs/view/3693012711      Description:By bringing together people that u...
linkedin       Full-Stack Software Engineer      Rain              New York      NY     fulltime  yearly    None        None        https://www.linkedin.com/jobs/view/3696158877      Rain’s mission is to create the fastest and ea...
zip_recruiter Software Engineer - New Grad       ZipRecruiter      Santa Monica  CA     fulltime  yearly    130000      150000      https://www.ziprecruiter.com/jobs/ziprecruiter...  We offer a hybrid work environment. Most US-ba...
zip_recruiter Software Developer                 TEKsystems        Phoenix       AZ     fulltime  hourly    65          75          https://www.ziprecruiter.com/jobs/teksystems-0...  Top Skills' Details• 6 years of Java developme...

```

### Parameters for `scrape_jobs()`

```plaintext
Optional
├── site_name (list|str): 
|    linkedin, zip_recruiter, indeed, glassdoor, google, bayt, bdjobs
|    (default is all)
│
├── search_term (str)
|
├── google_search_term (str)
|     search term for google jobs. This is the only param for filtering google jobs.
│
├── location (str)
│
├── distance (int): 
|    in miles, default 50
│
├── job_type (str): 
|    fulltime, parttime, internship, contract
│
├── proxies (list): 
|    in format ['user:pass@host:port', 'localhost']
|    each job board scraper will round robin through the proxies
|
├── is_remote (bool)
│
├── results_wanted (int): 
|    number of job results to retrieve for each site specified in 'site_name'
│
├── easy_apply (bool): 
|    filters for jobs that are hosted on the job board site (LinkedIn easy apply filter no longer works)
|
├── user_agent (str): 
|    override the default user agent which may be outdated
│
├── description_format (str): 
|    markdown, html (Format type of the job descriptions. Default is markdown.)
│
├── offset (int): 
|    starts the search from an offset (e.g. 25 will start the search from the 25th result)
│
├── hours_old (int): 
|    filters jobs by the number of hours since the job was posted 
|    (ZipRecruiter and Glassdoor round up to next day.)
│
├── verbose (int) {0, 1, 2}: 
|    Controls the verbosity of the runtime printouts 
|    (0 prints only errors, 1 is errors+warnings, 2 is all logs. Default is 2.)

├── linkedin_fetch_description (bool): 
|    fetches full description and direct job url for LinkedIn (Increases requests by O(n))
│
├── linkedin_company_ids (list[int]): 
|    searches for linkedin jobs with specific company ids
|
├── country_indeed (str): 
|    filters the country on Indeed & Glassdoor (see below for correct spelling)
|
├── enforce_annual_salary (bool): 
|    converts wages to annual salary
|
├── ca_cert (str)
|    path to CA Certificate file for proxies
```

```
├── Indeed limitations:
|    Only one from this list can be used in a search:
|    - hours_old
|    - job_type & is_remote
|    - easy_apply
│
└── LinkedIn limitations:
|    Only one from this list can be used in a search:
|    - hours_old
|    - easy_apply
```

## Supported Countries for Job Searching

### **LinkedIn**

LinkedIn searches globally & uses only the `location` parameter. 

### **ZipRecruiter**

ZipRecruiter searches for jobs in **US/Canada** & uses only the `location` parameter.

### **Indeed / Glassdoor**

Indeed & Glassdoor supports most countries, but the `country_indeed` parameter is required. Additionally, use the `location`
parameter to narrow down the location, e.g. city & state if necessary. 

You can specify the following countries when searching on Indeed (use the exact name, * indicates support for Glassdoor):

|                      |              |            |                |
|----------------------|--------------|------------|----------------|
| Argentina            | Australia*   | Austria*   | Bahrain        |
| Belgium*             | Brazil*      | Canada*    | Chile          |
| China                | Colombia     | Costa Rica | Czech Republic |
| Denmark              | Ecuador      | Egypt      | Finland        |
| France*              | Germany*     | Greece     | Hong Kong*     |
| Hungary              | India*       | Indonesia  | Ireland*       |
| Israel               | Italy*       | Japan      | Kuwait         |
| Luxembourg           | Malaysia     | Mexico*    | Morocco        |
| Netherlands*         | New Zealand* | Nigeria    | Norway         |
| Oman                 | Pakistan     | Panama     | Peru           |
| Philippines          | Poland       | Portugal   | Qatar          |
| Romania              | Saudi Arabia | Singapore* | South Africa   |
| South Korea          | Spain*       | Sweden     | Switzerland*   |
| Taiwan               | Thailand     | Turkey     | Ukraine        |
| United Arab Emirates | UK*          | USA*       | Uruguay        |
| Venezuela            | Vietnam*     |            |                |

### **Bayt**

Bayt only uses the search_term parameter currently and searches internationally



## Notes
* Indeed is the best scraper currently with no rate limiting.  
* All the job board endpoints are capped at around 1000 jobs on a given search.  
* LinkedIn is the most restrictive and usually rate limits around the 10th page with one ip. Proxies are a must basically.

## Frequently Asked Questions

---
**Q: Why is Indeed giving unrelated roles?**  
**A:** Indeed searches the description too.

- use - to remove words
- "" for exact match

Example of a good Indeed query

```py
search_term='"engineering intern" software summer (java OR python OR c++) 2025 -tax -marketing'
```

This searches the description/title and must include software, summer, 2025, one of the languages, engineering intern exactly, no tax, no marketing.

---

**Q: No results when using "google"?**  
**A:** You have to use super specific syntax. Search for google jobs on your browser and then whatever pops up in the google jobs search box after applying some filters is what you need to copy & paste into the google_search_term. 

---

**Q: Received a response code 429?**  
**A:** This indicates that you have been blocked by the job board site for sending too many requests. All of the job board sites are aggressive with blocking. We recommend:

- Wait some time between scrapes (site-dependent).
- Try using the proxies param to change your IP address.

---

### JobPost Schema

```plaintext
JobPost
├── title
├── company
├── company_url
├── job_url
├── location
│   ├── country
│   ├── city
│   ├── state
├── is_remote
├── description
├── job_type: fulltime, parttime, internship, contract
├── job_function
│   ├── interval: yearly, monthly, weekly, daily, hourly
│   ├── min_amount
│   ├── max_amount
│   ├── currency
│   └── salary_source: direct_data, description (parsed from posting)
├── date_posted
└── emails

Linkedin specific
└── job_level

Linkedin & Indeed specific
└── company_industry

Indeed specific
├── company_country
├── company_addresses
├── company_employees_label
├── company_revenue_label
├── company_description
└── company_logo

Naukri specific
├── skills
├── experience_range
├── company_rating
├── company_reviews_count
├── vacancy_count
└── work_from_home_type
```

## Bisect job scanner

What this fork adds to JobSpy:

- **New sites**, all through public JSON APIs, no browser and no login:
  - `greenhouse`, `ashby`, `lever`: a company's own job board, passed as
    `company_boards={"greenhouse": ["cloudbeds"], "ashby": ["enode"], "lever": ["acme"]}`.
  - `rippling`: a Rippling Recruiting board (`ats.rippling.com/<slug>/jobs`), read through
    `api.rippling.com/platform/api/ats/v1/board/<slug>/jobs`; only engineering titles are
    opened for their description, date and pay range.
    These see a role as soon as the company publishes it, before it is
    syndicated to LinkedIn or any aggregator.
  - `himalayas`: the remote-only board, filtered by the country you can work
    from (`location="Germany"`).
- **LinkedIn applicant counts** (`num_applicants`) when
  `linkedin_fetch_description=True`, and `location_restrictions` where a
  source lists the countries a remote role is open to.
- **`scanner/`**, a job-alert loop built on the library:
  - reads the boards, Himalayas and LinkedIn searches every 30 minutes;
  - keeps roles that match the stack you want, where you can legally work
    (home country, a region that includes it, or another EU country as a
    contractor), under an applicant limit, and not already seen;
  - learns new company boards from the links in LinkedIn and Himalayas
    results, so the next run reads those companies directly;
  - emails the new ones through any SMTP server given as a Symfony Mailer
    DSN (`smtp://user:password@smtp.example.com:587`).

### Setting it up

macOS, Python 3.11 or later (`uv` is used when installed). On Linux the
scanner and backups run the same way, but the schedule is yours to set up with
cron: `scanner/launchd/` is macOS only.

```bash
git clone <this repository> bisect-job-scanner && cd bisect-job-scanner
./setup.sh            # venv, your profile directory, an example config, an empty env, the pre-commit check
```

Then:

1. Edit `~/.job-scanner/config.toml` (`scanner/config.example.toml` explains every
   field): what to search for, where you can work, who gets the email, and
   `[profile]` (a contact address for the User-Agent, the launchd label).
2. Fill in `~/.job-scanner/env`, which `scanner/launchd/run.sh` sources:
   `JOB_SCANNER_MAILER_DSN` (an SMTP server as a Symfony Mailer DSN,
   `smtp://user:password@smtp.example.com:587`) and `JOB_SCANNER_MAIL_FROM`.
3. `.venv/bin/python -m scanner.run --dry-run` prints what would be sent.
4. `scanner/launchd/install.sh` schedules a scan every 30 minutes and a backup
   every day at 03:00 (`uninstall.sh` removes both).

```bash
.venv/bin/python -m scanner.run --add-board greenhouse somecompany
.venv/bin/python -m scanner.jobs              # what was emailed lately
.venv/bin/python -m scanner.triage list       # your verdicts on them
```

### Tracking applications with Bisect

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

### Where your data lives

Everything personal is in one profile directory outside the repository,
`$JOB_SCANNER_HOME` (default `~/.job-scanner`):

| File | What |
|---|---|
| `config.toml` | your searches, places, email address |
| `env` | secrets: the SMTP DSN and sender (mode 600) |
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

### Backups and restore

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

### Never commit

`config.toml`, `env` or any `.env*`, `*.sqlite3*`, `pending.json`, logs and
`backups/` are in `.gitignore`. The pre-commit check (`.githooks/pre-commit`,
enabled by `setup.sh`) also refuses staged database files and added lines with
an `smtp://` URL, a `JOB_SCANNER_MAILER_DSN=` value or a `~/.job-scanner` path.

### Reviewing the applications sent (optional)

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
