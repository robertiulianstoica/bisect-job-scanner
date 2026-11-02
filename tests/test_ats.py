from scanner.ats import advert_text, check_layer, coverage
from scanner.gap import adverts, gaps
from scanner.state import State

CV = """Jane Doe
Senior Backend Developer · jane@example.com · +351 912 345 678
linkedin.com/in/janedoe · github.com/janedoe

SUMMARY
Laravel and PHP developer; Vue on the front end; Docker in production.

EXPERIENCE
Acme: PHP, Laravel, Vue, Docker, PostgreSQL. Built payments with Stripe.

SKILLS
PHP, Laravel, Vue, Docker, PostgreSQL

EDUCATION
BSc Computer Science
""" + "word " * 200


def test_a_clean_text_layer_has_no_problems():
    problems, notes = check_layer(CV, b"%PDF-1.4 ...", name="Jane Doe")
    assert problems == []
    assert any("words in the text layer" in n for n in notes)


def test_what_a_parser_would_trip_on():
    text = "SUMMARY\nPHP developer\n" + "word " * 50
    raw = b"%PDF-1.4 /URI (https://linkedin.com/in/x) a=01aaaaaa-0000-7000-8000-000000000000"
    problems, notes = check_layer(text, raw, name="Jane Doe", application_id="01bbbbbb-0000-7000-8000-000000000000")
    joined = "\n".join(problems)
    for expected in ("tracking ids in the PDF", "almost no extractable text", "no email address",
                     "no phone number", "linkedin.com URL only behind a link label", "name (Jane Doe)",
                     "'EXPERIENCE'", "'SKILLS'", "'EDUCATION'"):
        assert expected in joined, expected
    assert "no github.com URL" in notes  # absent, not hidden: a note, not a problem


def test_the_name_is_only_checked_when_configured():
    problems, notes = check_layer(CV.replace("Jane Doe", "Someone Else"), b"%PDF-1.4")
    assert problems == [] and any("[profile] name" in n for n in notes)


def test_coverage_names_what_the_cv_has_and_misses():
    advert = "We use Laravel, Vue and Docker; Kubernetes and AWS are a plus."
    asked, covered, missing = coverage(advert, CV)
    assert {"Laravel", "Vue", "Docker", "Kubernetes", "AWS"} <= asked
    assert {"Laravel", "Vue", "Docker"} <= set(covered) and {"Kubernetes", "AWS"} <= set(missing)
    assert not set(covered) & set(missing)


def test_adverts_come_from_the_scanner_database(tmp_path):
    db = str(tmp_path / "state.sqlite3")
    state = State(db)
    for key, text, verdict in (("a", "Laravel and Vue, Kubernetes on AWS.", "applied"),
                               ("b", "Laravel and Vue, Kubernetes on AWS.", None),  # the same advert again
                               ("c", "Java and Spring Boot.", None)):
        state.db.execute("insert into seen (job_key, title, company, url, first_seen, emailed) values (?,?,?,?,?,1)",
                         (key, "Developer", "Acme", f"https://example.com/{key}", "2026-10-30T10:00:00+00:00"))
        state.db.execute("insert into details (job_key, description) values (?, ?)", (key, text))
        if verdict:
            state.set_triage(key, verdict)
    state.db.execute("insert into postings (job_key, url, company, title) values ('a', 'https://example.com/a', 'Acme', 'Developer')")
    state.commit()

    ads = adverts(db, "2026-10-01")
    assert len(ads) == 2 and sum(a for _, a in ads) == 1
    assert len(adverts(db, "2026-10-01", grep="laravel")) == 1
    table = {name: (share, share_applied, in_cv) for share, share_applied, name, in_cv in gaps(ads, CV)}
    assert table["Kubernetes"] == (0.5, 1.0, 0)  # half the adverts, every one applied to, never in the CV
    assert table["Laravel"][2] >= 3
    assert "Kotlin" not in table  # nobody asked

    label, text = advert_text(db, "https://example.com/a")
    assert label == "Acme | Developer" and "Kubernetes" in text and text.startswith("Developer\n")
