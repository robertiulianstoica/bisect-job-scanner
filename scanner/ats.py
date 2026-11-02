"""Read a CV PDF the way an ATS parser does, and score it against an advert.

An ATS reads the PDF's text layer, not the page. This extracts that layer with
pdftotext (brew install poppler) and checks what a parser needs: text at all,
contact details as literal text, the usual section headings, your name near
the top ([profile] name in the config), and, for a PDF from Bisect, the
application's tracking id. With an advert, it scores the skills the advert asks
for (the vocabulary in scanner/cvterms.py) against the ones the CV text names.

    python -m scanner.ats <cv.pdf>                                 # the text layer only
    python -m scanner.ats <cv.pdf> --job <job url or key>          # an advert the scanner has read
    python -m scanner.ats <cv.pdf> --advert advert.txt             # any advert, as a text file
    python -m scanner.ats <cv.pdf> --job <url> --id <Bisect application id>

The PDF to check is the one you will send: with Bisect, the one
bisect_get_application_pdf returns for the application (CLAUDE.md).

A missing skill is a question, not an instruction: never change the CV to
match an advert. Either the CV already holds the experience under another
name (say so in the letter, or add it to the CV in Bisect with its evidence),
or it is a real gap (state it after the proof).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from scanner.cvterms import count, found

HEADINGS = ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"]


def need_poppler() -> None:
    if not shutil.which("pdftotext"):
        raise SystemExit("pdftotext not found: install poppler (brew install poppler, or apt install poppler-utils)")


def pdf_text(pdf: Path) -> str:
    need_poppler()
    return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout


def pdf_pages(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    return int(m.group(1)) if m else 0


def check_layer(text: str, raw: bytes, name: str | None = None,
                application_id: str | None = None) -> tuple[list[str], list[str]]:
    """What a parser would trip on in the text layer: (problems, notes)."""
    problems: list[str] = []
    notes: list[str] = [f"{len(text.split())} words in the text layer"]
    if application_id:
        ids = set(re.findall(rb"a=([0-9a-f-]{36})", raw))
        if ids != {application_id.encode()}:
            problems.append(f"tracking ids in the PDF: {sorted(i.decode() for i in ids) or 'none'}, "
                            f"expected {application_id}")
    if len(text.split()) < 200:
        problems.append("almost no extractable text: an ATS would read an empty CV")
    if "\ufffd" in text or re.search("[\ue000-\uf8ff]", text):
        problems.append("garbled or private-use glyphs in the text layer (icon fonts?)")
    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        problems.append("no email address as literal text")
    if not re.search(r"\+?\d[\d ()-]{8,}\d", text):
        problems.append("no phone number as literal text")
    for site in ("linkedin.com", "github.com"):
        if site in text.lower():
            continue
        if site.encode() in raw:
            problems.append(f"{site} URL only behind a link label, which parsers drop: write it out")
        else:
            notes.append(f"no {site} URL")
    if name:
        if not re.search(r"\s+".join(map(re.escape, name.split())), text[:400], re.I):
            problems.append(f"name ({name}) not in the first lines")
    else:
        notes.append("name not checked: set [profile] name in the config")
    for heading in HEADINGS:
        if not re.search(rf"^\f?{heading}\s*$", text, re.M | re.I):
            problems.append(f"no '{heading}' heading on a line of its own")
    return problems, notes


def coverage(advert: str, cv: str) -> tuple[set[str], list[str], list[str]]:
    """The known skills an advert asks for, those the CV names (most named
    first), and those it never names."""
    asked = found(advert)
    have = found(cv)
    covered = sorted(asked & have, key=lambda t: (-count(cv, t), t))
    return asked, covered, sorted(asked - have)


def advert_text(db_path: str, ref: str) -> tuple[str, str]:
    """(company | title, advert text) for a job the scanner has read, by URL or key."""
    from scanner.state import posting_text

    db = sqlite3.connect(f"file:{Path(db_path).expanduser()}?mode=ro", uri=True)
    try:
        row = db.execute("select job_key, company, title from postings where url = ? or job_key = ?", (ref, ref)).fetchone() \
            or db.execute("select job_key, company, title from seen where url = ? or job_key = ?", (ref, ref)).fetchone()
        if not row:
            raise SystemExit(f"no job {ref} in the scanner's database; save the advert as a file and use --advert")
        key, company, title = row
        blob = db.execute("select text_z from posting_texts where job_key = ?", (key,)).fetchone()
        text = posting_text(blob[0]) if blob and blob[0] else ""
        if not text:
            detail = db.execute("select description from details where job_key = ?", (key,)).fetchone()
            text = detail[0] if detail and detail[0] else ""
        if not text:
            raise SystemExit(f"the scanner has no text for {ref}; save the advert as a file and use --advert")
        # The title is kept apart from the text, and often names the main skill ("PHP Developer").
        return f"{company} | {title}", f"{title}\n\n{text}"
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--job", help="a job the scanner has read: its URL or key")
    parser.add_argument("--advert", type=Path, help="an advert as a text file")
    parser.add_argument("--id", help="the Bisect application id the PDF's tracking link must carry")
    parser.add_argument("--config", help="default: $JOB_SCANNER_HOME/config.toml")
    args = parser.parse_args(argv)

    from scanner.settings import config_path, load_config
    config = load_config(args.config) if (args.config or config_path().is_file()) else {}
    raw = args.pdf.read_bytes()
    if not raw.startswith(b"%PDF-"):
        print("FAIL: not a PDF")
        return 1
    text = pdf_text(args.pdf)
    problems, notes = check_layer(text, raw, config.get("profile", {}).get("name") or None, args.id)
    notes.insert(0, f"{pdf_pages(args.pdf)} pages")

    advert, label = None, None
    if args.job:
        from scanner.settings import profile_home
        label, advert = advert_text(config.get("run", {}).get("state_path") or str(profile_home() / "state.sqlite3"), args.job)
    elif args.advert:
        label, advert = args.advert.name, args.advert.read_text(errors="replace")
    if advert is not None:
        asked, covered, missing = coverage(advert, text)
        share = len(covered) / len(asked) if asked else 1
        print(f"{label}")
        print(f"Skill coverage: the advert asks for {len(asked)} known skills; the CV names {len(covered)} ({share:.0%}).")
        print("  named:   " + (", ".join(f"{t} ({count(text, t)})" for t in covered) or "none"))
        print("  missing: " + (", ".join(missing) or "none"))
        print()

    for line in notes:
        print(line)
    if problems:
        print("Problems:")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("OK: the text layer parses cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
