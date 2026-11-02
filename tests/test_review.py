import pytest

from scanner.review import Library, parse_letter, read_feedback

LETTER = """Acme — Senior PHP Engineer (remote, EU)
Advert: https://jobs.example.com/acme/123 (Lisbon or remote)
Found: job scanner (LinkedIn), 2026-09-30
Bisect application: 01a0fcf7-70e2-7da4-919e-dfc660ff7953
Sent: 2026-10-01, Greenhouse form

--- Cover letter ---

Hello.
"""


@pytest.fixture
def jobs(tmp_path):
    letters = tmp_path / "direct" / "letters"
    (letters / "adverts").mkdir(parents=True)
    (letters / "acme-php-2026-10.txt").write_text(LETTER)
    (letters / "adverts" / "acme-php-2026-10.txt").write_text("The advert.")
    (letters / "sent" / "acme-php-2026-10").mkdir(parents=True)
    (letters / "sent" / "acme-php-2026-10" / "CV-Jane-Doe-Acme.pdf").write_bytes(b"%PDF-1.4")
    (letters / "old-one-2026-09.txt").write_text("Old Co — Developer\nSent: (pending)\n")
    return tmp_path


class TestParseLetter:
    def test_reads_the_headers(self):
        item = parse_letter("acme-php-2026-10", LETTER)
        assert item["company"] == "Acme"
        assert item["sent"] == "2026-10-01"
        assert item["advert_url"] == "https://jobs.example.com/acme/123"
        assert item["bisect_id"] == "01a0fcf7-70e2-7da4-919e-dfc660ff7953"
        assert not item["pending"]

    def test_pending_and_month_fallback(self):
        item = parse_letter("old-one-2026-09", "Old Co — Developer\nSent: (pending)\n")
        assert item["pending"] and item["sent"] is None
        assert item["date"] == "2026-09"


class TestLibrary:
    def test_lists_newest_first_with_files(self, jobs):
        library = Library(jobs)
        assert [i["slug"] for i in library.all()] == ["acme-php-2026-10", "old-one-2026-09"]
        detail = library.detail("acme-php-2026-10")
        assert detail["advert"] == "The advert."
        assert [f["kind"] for f in detail["files"]] == ["cv"]
        assert library.file(detail["files"][0]["name"]).name == "CV-Jane-Doe-Acme.pdf"

    def test_feedback_round_trip(self, jobs):
        library = Library(jobs)
        saved = library.save("acme-php-2026-10", {"rating": "ok", "notes": "Lead with payments.\n"})
        assert saved["rating"] == "ok" and saved["status"] == "new" and saved["notes"] == "Lead with payments."
        text = (jobs / "direct" / "feedback" / "acme-php-2026-10.md").read_text()
        assert "title: Acme — Senior PHP Engineer" in text
        assert read_feedback(jobs / "direct" / "feedback" / "acme-php-2026-10.md")["notes"] == "Lead with payments."
        assert library.summary("acme-php-2026-10")["feedback"]["rating"] == "ok"

    @pytest.mark.parametrize("name", ["../../../etc/passwd", "acme-php-2026-10.txt", "sent/../acme-php-2026-10.txt"])
    def test_serves_only_pdfs_and_letters_inside_the_folder(self, jobs, name):
        with pytest.raises(KeyError):
            Library(jobs).file(name)

    def test_rejects_unknown_applications_and_ratings(self, jobs):
        library = Library(jobs)
        with pytest.raises(KeyError):
            library.save("../x", {"notes": "x"})
        with pytest.raises(ValueError):
            library.save("acme-php-2026-10", {"rating": "great", "notes": ""})


def test_sent_date_is_the_one_after_the_word():
    text = ("Launchmetrics — Full Stack Engineer\nhttps://example.com/job\n"
            "Found on Himalayas. Applied on their site. Posting expires 2026-10-16.\n"
            "October 2026 version · application 01a0ed2b-b31d-7f55-8e81-fe2076fa33fd · sent 2026-09-29 on Teamtailor\n")
    item = parse_letter("launchmetrics-2026-09", text)
    assert item["sent"] == "2026-09-29"
    assert item["advert_url"] == "https://example.com/job"
    assert item["bisect_id"] == "01a0ed2b-b31d-7f55-8e81-fe2076fa33fd"
