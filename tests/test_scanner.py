import tomllib
from pathlib import Path

import pytest

from jobspy.ats import matches_search, search_terms
from scanner.notify import parse_dsn, render
from scanner.rules import check_applicants, check_content, check_location
from scanner.state import boards_in

CONFIG = tomllib.loads((Path(__file__).parent / "fixtures" / "config.toml").read_text())
SEARCH, ELIGIBILITY = CONFIG["search"], CONFIG["eligibility"]


def job(**fields):
    base = {"title": "Senior PHP Developer", "company": "Acme", "description": "Symfony and MySQL."}
    base.update(fields)
    return base


class TestSearchTerms:
    def test_splits_a_linkedin_query(self):
        assert search_terms('"PHP" OR "Symfony" OR "Laravel"') == ["PHP", "Symfony", "Laravel"]

    def test_matches_whole_words_only(self):
        assert matches_search('"PHP"', "Senior PHP engineer")
        assert not matches_search('"PHP"', "salary 70000 PHPX")

    def test_no_term_matches_everything(self):
        assert matches_search(None, "anything")

    def test_title_terms_count_only_in_the_title(self):
        query = '"PHP" OR title:"AI Engineer" OR title:"Integrations"'
        assert matches_search(query, "Senior AI Engineer", "Python, LLMs")
        assert matches_search(query, "Software Engineer, Integrations", "TypeScript")
        assert not matches_search(query, "Backend Engineer", "work with our AI Engineer team on integrations")
        assert matches_search(query, "Backend Engineer", "PHP 8")

    def test_title_terms_are_plain_terms_for_site_queries(self):
        query = '"PHP" OR title:"Magento"'
        assert search_terms(query) == ["PHP", "Magento"]
        assert search_terms(query, titles=False) == ["PHP"]


class TestContent:
    def test_keeps_a_php_role(self):
        assert check_content(job(), SEARCH).keep

    def test_drops_a_role_whose_company_industry_is_excluded(self):
        search = {**SEARCH, "exclude": ["casinos"]}
        assert not check_content(job(company_industry="Gambling Facilities and Casinos"), search).keep

    def test_drops_junior_titles(self):
        assert not check_content(job(title="Junior PHP Developer"), SEARCH).keep

    def test_drops_local_language_titles(self):
        assert not check_content(job(title="PHP Entwickler (m/w/d)"), SEARCH).keep
        assert not check_content(job(title="Développeur PHP H/F"), SEARCH).keep

    def test_gender_tag_drops_only_adverts_not_in_english(self):
        english = "We are looking for a PHP engineer to join our team and you will work with Symfony."
        german = "Wir suchen einen PHP-Entwickler für unser Team und du arbeitest mit Symfony und der Cloud."
        assert check_content(job(title="Senior Fullstack Engineer (m/f/d)", description=english), SEARCH).keep
        verdict = check_content(job(title="Senior Fullstack Engineer (m/w/d)", description=german), SEARCH)
        assert not verdict.keep and "not in English" in verdict.reason

    def test_java_title_is_dropped_but_javascript_is_not(self):
        assert not check_content(job(title="Senior Java Developer"), SEARCH).keep
        assert check_content(job(title="JavaScript and PHP Engineer"), SEARCH).keep

    def test_drops_a_java_backend_even_with_react(self):
        verdict = check_content(job(title="Full Stack Engineer", description="Java 8, Spring Boot, React"), SEARCH)
        assert not verdict.keep

    def test_needs_a_wanted_stack(self):
        assert not check_content(job(title="Backend Engineer", description="Go and Rust"), SEARCH).keep

    def test_typescript_only_needs_two_strengths(self):
        weak = job(title="Senior Frontend Engineer", description="TypeScript and React, design systems.")
        verdict = check_content(weak, SEARCH)
        assert not verdict.keep and "strengths" in verdict.reason
        strong = job(title="Senior Full Stack Engineer", description="TypeScript, React, Stripe payments and webhooks.")
        verdict = check_content(strong, SEARCH)
        assert verdict.keep
        assert verdict.flags == ("TypeScript/Python role: React, payments, webhooks",)

    def test_php_roles_skip_the_strengths_check(self):
        verdict = check_content(job(description="Symfony and TypeScript"), SEARCH)
        assert verdict.keep and verdict.flags == ()

    def test_flags_a_company_already_applied_to(self):
        search = dict(SEARCH, applied_companies=["Acme"])
        assert check_content(job(), search).flags == ("already applied here",)


class TestLocation:
    def test_home_country(self):
        assert check_location(job(location="Lisbon, Portugal"), ELIGIBILITY).keep

    def test_other_eu_country_is_a_b2b_offer(self):
        verdict = check_location(job(location="Remote", location_restrictions="Poland"), ELIGIBILITY)
        assert verdict.keep and verdict.flags == ("Poland only: offer B2B",)

    def test_europe_wide(self):
        assert check_location(job(location="Remote - Europe"), ELIGIBILITY).keep

    def test_us_only_is_out(self):
        assert not check_location(job(location="Remote - United States"), ELIGIBILITY).keep

    def test_hybrid_abroad_is_out(self):
        assert not check_location(job(location="London (Hybrid)"), ELIGIBILITY).keep
        assert not check_location(job(title="Backend - hybrid (Berlin)", location="Berlin, Germany"), ELIGIBILITY).keep

    def test_hybrid_at_home_is_fine(self):
        assert check_location(job(location="Lisbon, Portugal (Hybrid)"), ELIGIBILITY).keep

    def test_unstated_remote_is_kept_and_flagged(self):
        verdict = check_location(job(location="Remote"), ELIGIBILITY)
        assert verdict.keep and "location unclear" in verdict.flags


class TestApplicants:
    def test_under_the_limit(self):
        assert check_applicants({"num_applicants": 99}, 120).keep

    def test_at_the_limit(self):
        assert not check_applicants({"num_applicants": 120}, 120).keep

    def test_unknown_count_is_kept(self):
        assert check_applicants({"num_applicants": None}, 120).keep


class TestBoards:
    def test_finds_boards_in_job_links(self):
        assert boards_in(
            "https://job-boards.greenhouse.io/cloudbeds/jobs/4728563005",
            "https://jobs.ashbyhq.com/enode/24deb411",
            "https://jobs.eu.lever.co/acme/123",
            "https://www.linkedin.com/jobs/view/1",
        ) == [("greenhouse", "cloudbeds"), ("ashby", "enode"), ("lever", "acme")]

    def test_eu_greenhouse(self):
        assert boards_in("https://job-boards.eu.greenhouse.io/whitetech/jobs/1") == [("greenhouse", "whitetech")]
        assert boards_in("https://jobs.gem.com/modular/4606150005") == [("gem", "modular")]

    def test_workday_board_from_a_job_link(self):
        assert boards_in(
            "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced/job/Bucharest/Lead_R171728"
        ) == [("workday", "adobe.wd5/external_experienced")]
        assert boards_in("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/x") == [
            ("workday", "nvidia.wd5/NVIDIAExternalCareerSite")
        ]
        assert boards_in("https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/x/jobs") == []


class TestBoardQuery:
    def test_board_terms_join_the_stack_terms_not_the_titles(self):
        from scanner.run import board_query

        query = board_query({"terms": '"PHP"', "board_terms": ["TypeScript"], "title_terms": ["AI Engineer"]})
        assert query == '"PHP" OR "TypeScript" OR title:"AI Engineer"'
        assert matches_search(query, "Senior Engineer", "We build in TypeScript and Node")
        assert not matches_search(query, "Senior Engineer", "We build in Go")


class TestWorkday:
    def test_slug(self):
        from jobspy.workday import parse_slug

        assert parse_slug("adobe.wd5/external_experienced") == (
            "adobe.wd5.myworkdayjobs.com", "adobe", "external_experienced"
        )
        assert parse_slug("adobe") is None

    def test_country_facet_picks_one_facet(self):
        from jobspy.workday import country_facet

        facets = [
            {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Engineering", "id": "e", "count": 9}]},
            {"facetParameter": "locationMainGroup", "values": [
                {"facetParameter": "locationHierarchy1", "values": [
                    {"descriptor": "Romania", "id": "ro", "count": 18}, {"descriptor": "Spain", "id": "es", "count": 4}]},
                {"facetParameter": "locations", "values": [
                    {"descriptor": "Romania, Remote", "id": "ro-r", "count": 1}]},
            ]},
        ]
        assert country_facet(facets, "Romania") == {"locationHierarchy1": ["ro"]}
        assert country_facet(facets, "Portugal") == {}

    def test_engineering_titles(self):
        from jobspy.workday import ENGINEERING

        assert ENGINEERING.search("Senior Fullstack Engineer – Enterprise Data Collaboration")
        assert ENGINEERING.search("Senior SRE - Observability")
        assert not ENGINEERING.search("Talent Coordinator")
        assert not ENGINEERING.search("Principal Data Analyst")


class TestEmail:
    def test_parses_a_symfony_dsn(self):
        conf = parse_dsn("smtp://user%40x.com:p%40ss@smtp.example.com:587")
        assert conf == {"host": "smtp.example.com", "port": 587, "user": "user@x.com", "password": "p@ss", "implicit_tls": False}

    def test_port_465_is_implicit_tls(self):
        assert parse_dsn("smtp://u:p@smtp.example.com:465")["implicit_tls"]

    def test_rejects_other_transports(self):
        with pytest.raises(ValueError):
            parse_dsn("null://null")

    def test_renders_a_batch(self):
        subject, text, body = render([
            {"title": "PHP Dev", "company": "Acme", "site": "ashby", "location": "Remote - Europe",
             "job_url": "https://jobs.ashbyhq.com/acme/1", "num_applicants": 12, "flags": ["open to Europe"]},
        ])
        assert subject == "1 new job: Acme"
        assert "12 applicants" in text and "open to Europe" in text
        assert 'href="https://jobs.ashbyhq.com/acme/1"' in body


class TestMoreBoards:
    def test_personio_and_recruitee_links(self):
        assert boards_in(
            "https://probis-software-gmbh.jobs.personio.com/job/2809025",
            "https://acme.jobs.personio.de/job/1",
            "https://madewithlove.recruitee.com/o/experienced-software-engineer",
        ) == [("personio", "probis-software-gmbh"), ("personio", "acme"), ("recruitee", "madewithlove")]

    def test_workable_account_links(self):
        assert boards_in("https://apply.workable.com/creatunity-llc/j/75350DEDD0/",
                         "https://apply.workable.com/j/CB6D50E61E") == [("workable", "creatunity-llc")]

    def test_workable_account_merges_one_copy_per_country(self, monkeypatch):
        import jobspy.workable as workable
        from jobspy.model import ScraperInput, Site
        copy = {"title": "Lead Full Stack Engineer", "description": "<p>We use PHP and React.</p>",
                "telecommuting": True, "published_on": "2026-10-01", "url": "https://apply.workable.com/j/A1"}
        data = {"name": "Creatunity", "jobs": [
            dict(copy, shortcode="A1", country="Poland", locations=[{"country": "Poland"}]),
            dict(copy, shortcode="A2", country="Spain", locations=[{"country": "Spain"}]),
            dict(copy, title="Copywriter", shortcode="B1", country="Poland", locations=[{"country": "Poland"}]),
        ]}
        monkeypatch.setattr(workable, "get_json", lambda url, params=None: data)
        posts = workable.Workable().scrape(ScraperInput(
            site_type=[Site.WORKABLE], company_boards={"workable": ["creatunity-llc"]})).jobs
        lead = next(p for p in posts if p.title == "Lead Full Stack Engineer")
        assert len(posts) == 2 and lead.location_restrictions == ["Poland", "Spain"]
        assert lead.source_board == "workable:creatunity-llc" and lead.is_remote


class TestTimestamps:
    def test_recruitee_utc_suffix(self):
        from jobspy.ats import parse_timestamp
        assert parse_timestamp("2026-08-28 11:47:31 UTC").isoformat() == "2026-08-28T11:47:31+00:00"


class TestHomeCities:
    def test_on_site_in_another_home_city_is_out(self):
        rules = dict(ELIGIBILITY, home_cities=["Lisbon", "Lisboa"])
        assert not check_location(job(location="Porto, Portugal (on-site)"), rules).keep
        assert check_location(job(location="Lisboa, Portugal (hybrid)"), rules).keep
        assert check_location(job(location="Braga, Portugal (remote)"), rules).keep


class TestBoardTiers:
    def test_hot_boards_every_run_cold_in_rotation(self, tmp_path):
        from scanner.state import State
        state = State(str(tmp_path / "s.sqlite3"))
        state.add_board("greenhouse", "hotco", "config")
        for i in range(5):
            state.add_board("greenhouse", f"cold{i}", "import", tier="cold")
        first = state.boards_to_read(cold_limit=2)
        assert first["greenhouse"][0] == "hotco" and len(first["greenhouse"]) == 3
        state.mark_read(first)
        second = state.boards_to_read(cold_limit=2)["greenhouse"]
        assert "hotco" in second and not set(second[1:]) & set(first["greenhouse"][1:])

    def test_a_board_named_again_becomes_hot(self, tmp_path):
        from scanner.state import State
        state = State(str(tmp_path / "s.sqlite3"))
        state.add_board("ashby", "acme", "import", tier="cold")
        state.add_board("ashby", "acme", "linkedin")
        assert state.board_counts() == {"hot": 1}


class TestSeenDetails:
    def test_records_location_applicants_flags_and_reason(self, tmp_path):
        from scanner.state import State
        state = State(str(tmp_path / "s.sqlite3"))
        state.mark_seen({"id": "a", "title": "PHP Dev", "company": "Acme", "location": "Berlin, Germany",
                         "num_applicants": 30.0, "flags": ["Germany only: offer B2B"]}, emailed=True)
        state.mark_seen({"id": "b", "title": "Java Dev", "company": "Beta"}, emailed=False, reason="title: Java")
        rows = list(state.db.execute("select job_key, location, applicants, flags, reason from seen order by job_key"))
        assert rows == [("a", "Berlin, Germany", 30, "Germany only: offer B2B", None), ("b", None, None, None, "title: Java")]


class TestDjangoDates:
    def test_phpjobs_dates(self):
        from jobspy.phpjobsro import parse_django_date
        assert parse_django_date("Jan. 9, 2023, 1:17 p.m.").isoformat() == "2023-01-09T13:17:00+00:00"
        assert parse_django_date("Sept. 28, 2026, 10 a.m.").isoformat() == "2026-09-28T10:00:00+00:00"
        assert parse_django_date("July 7, 2025, 8:44 a.m.").isoformat() == "2025-07-07T08:44:00+00:00"


class TestVet:
    def test_registrable_domain(self):
        from scanner.vet import registrable
        assert registrable("www.medserv.ie") == "medserv.ie"
        assert registrable("careers.example.co.uk") == "example.co.uk"

    def test_flags_a_young_domain_and_cloned_adverts(self, monkeypatch):
        from datetime import date
        from scanner import vet
        board = vet.Board("workable", "Agency", ["AI Engineer"] * 6 + ["Other"], "AI Engineer",
                          "https://agency.com", markers=("workable.com",))
        monkeypatch.setattr(vet, "read_board", lambda url: board)
        monkeypatch.setattr(vet, "domain_created", lambda d: date(2025, 9, 5))
        monkeypatch.setattr(vet, "site_links_board", lambda d, b: None)
        facts, warnings = vet.vet("https://jobs.workable.com/view/x", today=date(2026, 9, 30))
        text = " ".join(warnings)
        assert "posted 6 times" in text and "under 2 years" in text and "no link" in text

    def test_same_title_different_description_is_not_a_clone(self, monkeypatch):
        from datetime import date
        from scanner import vet
        board = vet.Board("greenhouse", "big", ["Senior SWE"] * 3, "Senior SWE", markers=("x",),
                          bodies=[("Senior SWE", "a"), ("Senior SWE", "b"), ("Senior SWE", "c")], body="a")
        monkeypatch.setattr(vet, "read_board", lambda url: board)
        monkeypatch.setattr(vet, "domain_created", lambda d: date(1995, 1, 1))
        monkeypatch.setattr(vet, "site_links_board", lambda d, b: "https://big.com/careers")
        facts, warnings = vet.vet("https://job-boards.greenhouse.io/big/jobs/1", "big.com", today=date(2026, 9, 30))
        assert warnings == []


class TestBoardDiscovery:
    def test_a_job_link_does_not_promote_a_board_in_rotation(self, tmp_path):
        from scanner.state import State
        state = State(str(tmp_path / "s.sqlite3"))
        state.add_board("greenhouse", "acme", "import", tier="cold")
        state.add_board("greenhouse", "acme", "greenhouse", promote_existing=False)
        assert state.board_counts().get("hot", 0) == 0
        state.add_board("greenhouse", "acme", "manual")
        assert state.board_counts().get("hot") == 1


class TestTriage:
    def test_verdicts_are_kept_and_updated(self, tmp_path):
        import sqlite3
        from scanner.state import State
        state = State(str(tmp_path / "s.sqlite3"))
        key = state.add_manual_job("Senior AI Fullstack Engineer", "Jimdo", "https://example.com/jimdo")
        state.set_triage(key, "shortlist", "TypeScript AI role")
        state.set_triage(key, "applied", bisect_id="01abc")
        row = state.db.execute("select verdict, reason, bisect_id from triage where job_key = ?", (key,)).fetchone()
        assert tuple(row) == ("applied", "TypeScript AI role", "01abc")

    def test_rejects_an_unknown_verdict(self, tmp_path):
        import pytest
        from scanner.state import State
        state = State(str(tmp_path / "s.sqlite3"))
        with pytest.raises(ValueError):
            state.set_triage("x", "great")

    def test_finds_a_job_by_words_or_url(self, tmp_path):
        import sqlite3
        import pytest
        from scanner.state import State
        from scanner.triage import find_job
        state = State(str(tmp_path / "s.sqlite3"))
        state.db.row_factory = sqlite3.Row
        state.add_manual_job("Senior PHP Engineer", "Airalo", "https://jobs.lever.co/airalo/1")
        state.add_manual_job("Senior PHP Engineer", "Spyrosoft", "https://nofluffjobs.com/job/x")
        assert find_job(state, "airalo php")["company"] == "Airalo"
        assert find_job(state, "https://nofluffjobs.com/job/x?utm=1")["company"] == "Spyrosoft"
        state.add_manual_job("Staff Engineer", "Housecall Pro", "https://hcp.com/open/?gh_jid=1")
        state.add_manual_job("Staff Engineer", "Housecall Pro", "https://hcp.com/open/?gh_jid=2")
        assert find_job(state, "https://hcp.com/open/?gh_jid=2")["url"].endswith("=2")
        with pytest.raises(SystemExit):
            find_job(state, "senior php")


class TestDetails:
    def test_stack_tags(self):
        from scanner.stack import tags

        found = tags("Senior Engineer", "We use TypeScript, React and Postgres on AWS. Go is a plus. Not Java.")
        assert {"TypeScript", "React", "PostgreSQL", "AWS", "Go", "Java"} <= set(found)
        assert "JavaScript" not in found and "Rust" not in found
        assert tags("Let's go to the next step") == []

    def test_saves_the_advert_and_counts_runs(self, tmp_path):
        import json

        from scanner.state import State

        state = State(str(tmp_path / "s.sqlite3"))
        job_row = {"id": "gh-1", "site": "greenhouse", "title": "PHP Engineer", "company": "Acme",
                   "job_url": "https://x/1", "description": "Symfony and Stripe payments.",
                   "min_amount": 60000.0, "max_amount": float("nan"), "currency": "EUR", "is_remote": True,
                   "source_board": "greenhouse:acme"}
        state.mark_seen(job_row, emailed=True)
        row = state.db.execute(
            "select description, stack, salary_min, salary_max, is_remote, source_board from details").fetchone()
        assert row[0] == "Symfony and Stripe payments."
        assert json.loads(row[1]) == ["PHP", "Symfony", "Payments"]
        assert row[2:] == (60000.0, None, 1, "greenhouse:acme")
        state.touch(["gh-1"])
        assert state.db.execute("select last_seen from seen").fetchone()[0]


class TestSalary:
    def test_ranges_as_written(self):
        from scanner.salary import parse_salary

        assert parse_salary("Compensation Range: PLN 18K - PLN 22K") == (18000, 22000, "PLN", None)
        assert parse_salary("USD 8,200-9,700/month B2B") == (8200, 9700, "USD", "month")
        assert parse_salary("60.000 - 75.000 EUR brutto") == (60000, 75000, "EUR", None)
        assert parse_salary("CDI, 45k à 60k €") == (45000, 60000, "EUR", None)
        assert parse_salary("€60,000 - €80,000 per year") == (60000, 80000, "EUR", "year")
        assert parse_salary("3-5 years of experience") is None

    def test_yearly_eur_drops_what_is_not_pay(self):
        from scanner.salary import yearly_eur

        assert yearly_eur(8200, 9700, "USD", "month") == (8200 * 0.92 * 12, 9700 * 0.92 * 12)
        assert yearly_eur(5, 10, "EUR", "year") is None
        assert yearly_eur(3100, 4500, "EUR", None) == (37200, 54000)  # unstated: judged a month

    def test_main_language(self):
        from scanner.classify import main_language

        assert main_language("Senior PHP Developer", "React and TypeScript too") == "PHP"
        assert main_language("Backend Engineer", "Python, Python, and some Go") == "Python"
        assert main_language("Engineer", "Let's go") is None


class TestPostings:
    def test_every_job_is_kept_and_seen_again(self, tmp_path):
        import json

        from scanner.state import State, posting_text

        state = State(str(tmp_path / "s.sqlite3"))
        jobs = [
            {"id": "gh-1", "site": "greenhouse", "title": "Go Engineer", "company": "A",
             "description": "Go and Kubernetes. €70k - €90k per year.", "source_board": "greenhouse:a"},
            {"id": "gh-2", "site": "greenhouse", "title": "Recruiter", "company": "A", "description": None},
        ]
        state.save_postings(jobs)
        row = state.db.execute(
            "select p.title, p.stack, p.pay_min, p.pay_max, x.text_z, p.first_seen, p.pay_currency, p.pay_period, p.pay_source"
            " from postings p join posting_texts x using (job_key) where job_key='gh-1'").fetchone()
        assert row[0] == "Go Engineer" and json.loads(row[1]) == ["Go", "Kubernetes"]
        assert (row[2], row[3], row[6], row[7], row[8]) == (70000, 90000, "EUR", "year", "text")
        assert posting_text(row[4]).startswith("Go and Kubernetes")
        assert state.db.execute("select count(*) from postings").fetchone()[0] == 2
        state.save_postings(jobs[:1])
        first, last = state.db.execute("select first_seen, last_seen from postings where job_key='gh-1'").fetchone()
        assert last >= first
        state.db.execute("update postings set last_seen = '2020-01-01T00:00:00+00:00' where job_key='gh-1'")
        assert state.drop_old_texts(30) == 1
        assert state.db.execute("select count(*) from postings").fetchone()[0] == 2
        assert state.db.execute("select count(*) from posting_texts").fetchone()[0] == 0

    def test_moves_texts_out_of_an_old_postings_table(self, tmp_path):
        import sqlite3
        import zlib

        from scanner.state import State, posting_text

        path = tmp_path / "old.sqlite3"
        db = sqlite3.connect(path)
        db.execute("create table postings (job_key text primary key, title text, last_seen text, text_z blob)")
        db.execute("insert into postings values ('k', 'T', '2026-10-01', ?)", (zlib.compress(b"hello"),))
        db.commit(); db.close()
        state = State(str(path))
        assert "text_z" not in {r[1] for r in state.db.execute("pragma table_info(postings)")}
        assert posting_text(state.db.execute("select text_z from posting_texts").fetchone()[0]) == "hello"


class TestClassify:
    def test_region(self):
        from scanner.classify import region

        assert region("Bucharest, Romania") == "EU"
        assert region("San Francisco, CA") == "US"
        assert region("Remote", "We hire across EMEA.") == "EU"
        assert region("Chicago", "Offices in Chicago and London (EMEA)") == "US"
        assert region("Remote", "Anywhere.") == "other"

    def test_metrics_record_and_export(self, tmp_path):
        from scanner import metrics
        from scanner.state import State

        state = State(str(tmp_path / "s.sqlite3"))
        state.save_postings([
            {"id": "a", "title": "Senior PHP Developer", "location": "Berlin, Germany",
             "description": "PHP and Symfony. €60k - €80k per year.", "date_posted": "2026-10-01"},
            {"id": "b", "title": "Backend Engineer", "location": "New York, NY",
             "description": "Python services.", "min_amount": 150000.0, "max_amount": 190000.0,
             "currency": "USD", "interval": "yearly"},
            {"id": "c", "title": "Recruiter", "location": "Berlin", "description": "PHP hiring."},
        ])
        metrics.record(state)
        data = metrics.export(state)
        assert data["current"]["EU"]["PHP"]["open_jobs"] == 1
        assert data["current"]["EU"]["PHP"]["min_p50"] == 60000
        assert data["current"]["US"]["Python"]["max_p50"] == 190000 * 0.92
        assert data["current"]["global"]["all"]["open_jobs"] == 2
        assert {d["region"] for d in data["daily"]} == {"global", "EU", "US"}


class TestCompanies:
    def test_hiring_by_company_age(self, tmp_path):
        from datetime import date

        from scanner import metrics
        from scanner.companies import SCHEMA
        from scanner.state import State

        state = State(str(tmp_path / "s.sqlite3"))
        state.save_postings([
            {"id": "a", "title": "PHP Developer", "location": "Berlin, Germany", "description": "PHP",
             "source_board": "greenhouse:old"},
            {"id": "b", "title": "Python Engineer", "location": "Paris, France", "description": "Python",
             "source_board": "ashby:young"},
        ])
        state.db.execute(SCHEMA)
        year = date.today().year
        state.db.execute("insert into companies (board, name, founded, founded_source) values"
                         " ('greenhouse:old', 'Old Co', ?, 'wikidata'), ('ashby:young', 'Young Co', ?, 'domain')",
                         (year - 30, year - 1))
        data = metrics.companies_by_age(state)
        cohorts = {c["label"]: c for c in data["EU"]["cohorts"]}
        assert cohorts["over 20 years"]["open_jobs"] == 1 and cohorts["over 20 years"]["languages"] == {"PHP": 100.0}
        assert cohorts["under 3 years"]["companies"] == 1
        assert {c["name"] for c in data["EU"]["top"]} == {"Old Co", "Young Co"}


class TestAI:
    def test_ai_kind(self):
        from scanner.classify import ai_kind

        assert ai_kind("Senior AI Engineer", "") == "builds"
        assert ai_kind("Backend Engineer", "You will build LLM-powered features and AI agents for support.") == "builds"
        assert ai_kind("Backend Engineer", "We use Cursor and Claude Code every day.") == "uses"
        assert ai_kind("Backend Engineer", "We are an AI agents platform. You will build billing in Go.") is None


class TestScams:
    def test_signals_skip_warnings(self):
        from scanner.classify import scam_signals, warns_of_fraud

        warning = "We will never ask you to pay a fee. Beware of recruiters on Telegram."
        assert scam_signals(warning) == [] and warns_of_fraud(warning)
        scam = "Great pay. To start, pay a registration fee of $50. Contact our HR on Telegram: @hr_jobs"
        assert scam_signals(scam) == ["asks for a fee", "contact off-platform"]


class TestWorkMode:
    def test_work_mode(self):
        from scanner.classify import work_mode

        assert work_mode("London (Hybrid)", False, "") == "hybrid"
        assert work_mode("Remote", True, "") == "remote"
        assert work_mode("Remote - Spain", True, "You will be in the office 2 days a week.") == "hybrid"
        assert work_mode("Berlin", False, "This is a fully remote role within Germany.") == "remote"
        assert work_mode("Austin, TX", False, "This role is on-site in Austin.") == "on-site"
        assert work_mode("Paris", False, "Great team.") is None


class TestClosed:
    def test_closed_when_a_listing_read_misses_it_and_reopened_when_seen(self, tmp_path):
        from scanner.state import State, now

        state = State(str(tmp_path / "s.sqlite3"))
        jobs = [{"id": "a", "title": "PHP Developer", "source_board": "greenhouse:acme", "description": "PHP"},
                {"id": "b", "title": "Go Engineer", "source_board": "greenhouse:acme", "description": "Go"}]
        import time
        state.save_postings(jobs)
        time.sleep(1.1)
        started = now()
        time.sleep(1.1)
        state.save_postings(jobs[:1])                          # this read lists only "a"
        assert state.close_missing(started, {"greenhouse:acme"}) == 1
        assert state.db.execute("select closed_at is not null from postings where job_key='b'").fetchone()[0] == 1
        assert state.close_missing(started, set()) == 0        # a board that listed nothing closes nothing
        state.save_postings(jobs[1:])                          # "b" is back
        assert state.db.execute("select closed_at from postings where job_key='b'").fetchone()[0] is None


class TestBoardTitleTerms:
    def test_full_stack_titles_are_searched_on_the_boards(self):
        from scanner.run import board_query
        query = board_query(SEARCH)
        assert matches_search(query, "Senior Fullstack Engineer", "We use Vue and Go.")
        assert matches_search(query, "Full-Stack Developer", "")
        assert not matches_search(query, "Backend Engineer", "Our full stack team uses Go.")

    def test_but_still_held_to_the_strengths_rule(self):
        from scanner.rules import check_secondary_stack
        assert not check_secondary_stack("Full Stack Engineer", "React and TypeScript.", SEARCH).keep
        assert check_secondary_stack("Full Stack Engineer", "React, Stripe payments, webhooks.", SEARCH).keep


class TestFindJob:
    def test_a_query_that_names_the_job_is_not_dropped(self, tmp_path):
        import sqlite3
        from scanner.state import State
        from scanner.triage import find_job
        state = State(str(tmp_path / "s.sqlite3"))
        state.db.row_factory = sqlite3.Row
        state.add_manual_job("Senior Backend Engineer", "8am", "https://www.8am.com/openings/?gh_jid=1")
        with pytest.raises(SystemExit):
            find_job(state, "https://www.8am.com/openings/?gh_jid=2")
        state.add_manual_job("Developer", "Acme", "https://acme.com/jobs/7")
        assert find_job(state, "https://acme.com/jobs/7?utm_source=linkedin")["company"] == "Acme"


class TestHipo:
    PAGE = """<script type="application/ld+json">{"@type": "JobPosting", "title": "PHP Backend Engineer &amp; APIs",
      "datePosted": "2026-10-02", "description": "PPC este liderul pieÈ\u009bei",
      "educationRequirements": ": Symfony and Stripe webhooks",
      "hiringOrganization": {"name": "PPC ROMANIA"},
      "jobLocation": {"address": {"addressLocality": "BUCURESTI ,"}}}</script>
      <td>Remote work:</td><td> On-site </td>"""

    def test_reads_the_job_page(self):
        from jobspy.hipo import parse_job
        job = parse_job("https://www.hipo.ro/x", self.PAGE)
        assert job["title"] == "PHP Backend Engineer & APIs"
        assert job["city"] == "Bucuresti" and job["work_mode"] == "on-site"
        assert job["description"].startswith("Symfony and Stripe webhooks")
        assert "pieței" in job["description"]

    def test_skips_hipos_own_promotions(self):
        from jobspy.hipo import job_links
        page = ('<a href="/locuri-de-munca/locuri_de_munca/267339/Angajatori-de-TOP/Inscrie-te">'
                '<a href="/locuri-de-munca/locuri_de_munca/272416/PPC-ROMANIA/PHP-Backend-Engineer">')
        assert list(job_links(page)) == ["272416"]


def test_an_advert_seen_through_another_source_is_seen(tmp_path):
    from scanner.state import State
    state = State(str(tmp_path / "s.sqlite3"))
    url = "https://www.hipo.ro/locuri-de-munca/locuri_de_munca/272416/PPC-ROMANIA/PHP-Backend-Engineer"
    state.mark_seen({"id": "peviitor-" + url, "job_url": url, "title": "PHP Backend Engineer", "company": "PPC"}, emailed=True)
    assert state.is_seen("hipo-272416", url)
    assert not state.is_seen("hipo-1", "https://www.hipo.ro/other")


class TestFreshness:
    NOW = __import__("datetime").datetime(2026, 10, 2, 16, 30, tzinfo=__import__("datetime").timezone.utc)

    def test_to_the_minute_when_the_source_gives_a_time(self):
        from datetime import timedelta
        from scanner.notify import freshness
        assert freshness({"site": "ashby", "posted_at": self.NOW - timedelta(minutes=49)}, self.NOW) == "posted 49 min ago"
        assert freshness({"site": "ashby", "posted_at": self.NOW - timedelta(hours=5)}, self.NOW) == "posted 5 h ago"

    def test_to_the_day_otherwise_and_not_for_refresh_dates(self):
        from datetime import date
        from scanner.notify import freshness
        assert freshness({"site": "ejobs", "date_posted": date(2026, 10, 1)}, self.NOW) == "posted yesterday"
        assert freshness({"site": "hipo", "date_posted": date(2026, 10, 2)}, self.NOW) is None

    def test_linkedin_relative_times(self):
        from jobspy.linkedin import posted_ago
        assert (self.NOW - posted_ago("49 minutes ago", self.NOW)).total_seconds() == 49 * 60
        assert posted_ago("2 days ago", self.NOW) is None

    def test_be_among_the_first_25(self):
        from scanner.notify import applicants
        assert applicants({"num_applicants": 25}) == "under 25 applicants"
        assert applicants({"num_applicants": 76}) == "76 applicants"


def test_company_names_compare_without_legal_forms():
    from scanner.rules import same_company
    assert same_company("REIZ TECH UAB", ["Reiz Tech"])
    assert same_company("Code Compass 🧭", ["Code Compass"])
    assert same_company("PPC PRODUCTIE ROMANIA S.R.L.", ["PPC Productie Romania"])
    assert not same_company("Reiz", ["Reiz Tech"])
    assert not same_company("", ["Reiz Tech"])


def test_philippine_pesos_are_not_the_php_language():
    from scanner.rules import check_content
    perks = "Admin assistant. Perks: 1,000 PHP De Minimis, WI-FI allowance, PHP 5,000 bonus, ₱20,000 a month."
    assert not check_content(job(title="Business Project Manager", description=perks), SEARCH).keep
    assert check_content(job(title="Moodle Developer", description="PHP and Moodle plugins. Pay: 50,000 PHP a month."), SEARCH).keep


class TestLinkedInCityAbroad:
    RULES = ELIGIBILITY

    def test_a_city_abroad_without_remote_in_the_advert_is_dropped(self):
        from scanner.rules import check_location
        job = {"site": "linkedin", "location": "Budapest, Budapest, Hungary", "description": "Join our Budapest office."}
        assert not check_location(job, self.RULES).keep

    def test_kept_when_the_advert_offers_remote(self):
        from scanner.rules import check_location
        job = {"site": "linkedin", "location": "Munich, Bavaria, Germany",
               "description": "Full Stack Engineer. 🌍 Remote. Remote and flexible working options available."}
        assert check_location(job, self.RULES).keep

    def test_hybrid_only_adverts_are_dropped_and_other_sites_untouched(self):
        from scanner.rules import check_location, linkedin_city_abroad
        hybrid = {"site": "linkedin", "location": "Paris, Île-de-France, France",
                  "description": "Hybrid: 3 days a week in the office. Remote days on Friday."}
        assert not check_location(hybrid, self.RULES).keep
        board = dict(hybrid, site="greenhouse")
        assert not linkedin_city_abroad(board, False)
        search = {"site": "linkedin", "location": "European Union (remote search)", "description": ""}
        assert not linkedin_city_abroad(search, False)


def test_hybrid_in_other_languages_counts_as_hybrid():
    from scanner.rules import check_location
    job = {"site": "linkedin", "title": "Senior Backend Developer (PHP) - Híbrido - Madrid",
           "location": "European Union (remote search)", "description": "PHP"}
    assert not check_location(job, ELIGIBILITY).keep


class TestSendHours:
    from datetime import datetime as dt

    def test_due_once_a_send_hour_has_passed(self):
        from scanner.run import send_due
        assert send_due([8, 14], self.dt(2026, 10, 9, 13, 30), self.dt(2026, 10, 9, 14, 0))

    def test_not_due_between_send_hours(self):
        from scanner.run import send_due
        assert not send_due([8, 14], self.dt(2026, 10, 9, 14, 0), self.dt(2026, 10, 9, 20, 30))

    def test_a_slot_missed_while_asleep_is_sent_on_wake(self):
        from scanner.run import send_due
        assert send_due([8, 14], self.dt(2026, 10, 8, 14, 0), self.dt(2026, 10, 9, 10, 15))

    def test_before_the_first_hour_counts_from_yesterday(self):
        from scanner.run import send_due
        assert not send_due([8, 14], self.dt(2026, 10, 8, 14, 0), self.dt(2026, 10, 9, 7, 30))

    def test_queue_round_trip(self, tmp_path):
        from scanner.run import load_queue, save_queue
        path = tmp_path / "pending.json"
        assert load_queue(path) == {"last_sent": None, "jobs": []}
        save_queue(path, self.dt(2026, 10, 9, 14, 0), [{"title": "PHP", "date_posted": self.dt(2026, 10, 9).date()}])
        queue = load_queue(path)
        assert queue["last_sent"] == self.dt(2026, 10, 9, 14, 0)
        assert queue["jobs"][0]["date_posted"] == "2026-10-09"


class TestRippling:
    def test_board_from_a_job_link(self):
        assert boards_in("https://ats.rippling.com/nexcess/jobs/3603175e-98ea-4792-8260-c5b4ea0cd35e?src=LinkedIn") == [
            ("rippling", "nexcess")
        ]
        assert boards_in("https://ats.rippling.com/en-GB/acme/jobs") == [("rippling", "acme")]

    def test_pay_takes_the_widest_range(self):
        from jobspy.rippling import pay
        comp = pay([
            {"currency": "EUR", "frequency": "MONTH", "rangeStart": 4000.0, "rangeEnd": 5000.0},
            {"currency": "EUR", "frequency": "MONTH", "rangeStart": 5000.0, "rangeEnd": 6000.0},
        ])
        assert (comp.min_amount, comp.max_amount, comp.currency, comp.interval.value) == (4000.0, 6000.0, "EUR", "monthly")

    def test_pay_skips_mixed_currencies(self):
        from jobspy.rippling import pay
        assert pay([
            {"currency": "EUR", "frequency": "MONTH", "rangeStart": 4000.0, "rangeEnd": 5000.0},
            {"currency": "USD", "frequency": "YEAR", "rangeStart": 90000.0, "rangeEnd": 120000.0},
        ]) is None

    def test_description_sections_are_joined(self):
        from jobspy.rippling import description_html
        assert description_html({"description": {"company": "<p>A</p>", "role": "<p>B</p>"}}) == "<p>A</p><p>B</p>"
