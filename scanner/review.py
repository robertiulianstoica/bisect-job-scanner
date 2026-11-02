"""A local screen for reviewing every application sent, and for leaving
feedback that the next applications take into account. Optional: it is
for a jobs folder kept in the layout below, set as [review] jobs_dir in the
config; without one it does not start.

    python -m scanner.review                       # http://127.0.0.1:8790, dashboard at /market
    python -m scanner.review --port 8791 --jobs ~/path/to/jobs

It reads what the applications left behind in the jobs folder:

    direct/letters/<slug>.txt           the letter file: headers, form answers, letter, replies
    direct/letters/<slug>.md, .pdf      a letter kept in another form
    direct/letters/adverts/<slug>.txt   the advert as it was when applying
    direct/letters/sent/<slug>/*.pdf    the files uploaded: CV-*.pdf, cover letters

and writes your notes to direct/feedback/<slug>.md, for the next
application to take into account.

Nothing here opens the CV host (bisect.eu). PDFs are drawn as images in the browser,
so the tracking links inside them cannot be clicked by accident: a click would count
as the company reading the CV.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from scanner.settings import config_path, load_config

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "review" / "index.html"

SLUG = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
# Bisect's ids are UUIDv7; the ATS ids in the same files (Ashby, Greenhouse) are v4.
BISECT_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
# "sent 2026-09-28", "Applied 2026-09-17", "Sent: 2026-10-02": the date right after the word, not
# a later one on the same line ("Applied on their site. Posting expires 2026-10-16").
SENT_ON = re.compile(r"\b(?:sent|applied)\b[: ]{0,3}(?:on )?(20\d\d-\d\d-\d\d)\b", re.I)
URL = re.compile(r"https?://\S+")
RATINGS = ("good", "ok", "bad")
STATUSES = ("new", "folded")


def first(pattern: re.Pattern, text: str | None) -> str | None:
    match = pattern.search(text or "")
    return match.group(1) if match and match.groups() else match.group(0) if match else None


def header(text: str, *names: str) -> str | None:
    """The value of the first `Name: value` line among the names given."""
    for name in names:
        match = re.search(rf"^{re.escape(name)}:\s*(.+)$", text, re.M)
        if match:
            return match.group(1).strip()
    return None


def parse_letter(slug: str, text: str, other_title: str | None = None) -> dict:
    """What a letter file says about its application. Files from before the
    Sent: header put the facts in prose ("sent 2026-09-28", "Applied
    2026-09-17"), and a few start with the letter itself, so the title can come
    from the letter kept beside it as Markdown."""
    lines = [line.strip() for line in text.strip().splitlines()]
    title = (lines[0].lstrip("# ") if lines and " — " in lines[0] and len(lines[0]) < 180 else None) or other_title
    if not title:
        title = " ".join(w.capitalize() for w in re.sub(r"-20\d\d-\d\d$", "", slug).split("-"))
    company = re.split(r"\s+[—–]\s+", title, maxsplit=1)[0].strip()
    sent_line = header(text, "Sent")
    sent = first(DATE, sent_line) or first(SENT_ON, text)
    found = first(DATE, header(text, "Found"))
    month = re.search(r"(20\d\d)-(\d\d)$", slug)
    advert = first(URL, header(text, "Advert", "Adverts")) or next(
        (u for u in URL.findall("\n".join(lines[:4])) if "bisect.eu" not in u), None)
    return {
        "slug": slug,
        "title": title,
        "company": company,
        "sent": sent,
        "pending": bool(sent_line and "pending" in sent_line.lower()),
        "date": sent or found or (f"{month.group(1)}-{month.group(2)}" if month else None),
        "advert_url": advert,
        "bisect_id": first(BISECT_ID, header(text, "Bisect application") or text),
    }


def read_feedback(path: Path) -> dict | None:
    if not path.exists():
        return None
    text = path.read_text()
    meta, body = {}, text
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        for line in head.splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return {"rating": meta.get("rating") or None, "status": meta.get("status") or "new",
            "updated": meta.get("updated"), "notes": body.strip()}


def write_feedback(path: Path, slug: str, title: str, rating: str | None, notes: str, status: str) -> dict:
    if rating not in (None, "", *RATINGS):
        raise ValueError(f"rating must be one of {RATINGS}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    updated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\napplication: {slug}\ntitle: {title}\nrating: {rating or ''}\nstatus: {status}\n"
                    f"updated: {updated}\n---\n\n{notes.strip()}\n")
    return read_feedback(path)


class Library:
    """The applications under a jobs folder."""

    def __init__(self, jobs: Path):
        self.letters = jobs / "direct" / "letters"
        self.feedback = jobs / "direct" / "feedback"

    def slugs(self) -> list[str]:
        return sorted(p.stem for p in self.letters.glob("*.txt"))

    def files(self, slug: str) -> list[dict]:
        """PDFs and other letter forms, with whether each was saved after the send."""
        found = []
        sent_dir = self.letters / "sent" / slug
        for path in sorted(sent_dir.glob("*.pdf")) if sent_dir.is_dir() else []:
            found.append((f"sent/{slug}/{path.name}", path))
        for suffix in (".pdf", ".md"):
            path = self.letters / f"{slug}{suffix}"
            if path.exists():
                found.append((path.name, path))
        out = []
        for name, path in found:
            kind = "cv" if path.name.startswith("CV-") else "pdf" if path.suffix == ".pdf" else "text"
            saved = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
            out.append({"name": name, "label": path.name, "kind": kind, "saved": saved})
        return out

    def parse(self, slug: str) -> dict:
        markdown = self.letters / f"{slug}.md"
        heading = next((line.lstrip("# ").strip() for line in markdown.read_text().splitlines()
                        if line.startswith("# ")), None) if markdown.exists() else None
        return parse_letter(slug, (self.letters / f"{slug}.txt").read_text(), heading)

    def summary(self, slug: str) -> dict:
        item = self.parse(slug)
        feedback = read_feedback(self.feedback / f"{slug}.md")
        item["feedback"] = {k: feedback[k] for k in ("rating", "status", "updated")} if feedback else None
        item["has_cv"] = any(f["kind"] == "cv" for f in self.files(slug))
        return item

    def all(self) -> list[dict]:
        items = [self.summary(slug) for slug in self.slugs()]
        return sorted(items, key=lambda i: (i["date"] or "", i["slug"]), reverse=True)

    def detail(self, slug: str) -> dict:
        self.check(slug)
        item = self.summary(slug)
        item["text"] = (self.letters / f"{slug}.txt").read_text()
        advert = self.letters / "adverts" / f"{slug}.txt"
        item["advert"] = advert.read_text() if advert.exists() else None
        item["files"] = self.files(slug)
        for f in item["files"]:
            if f["kind"] == "text":
                f["text"] = (self.letters / f["name"]).read_text()
        item["feedback"] = read_feedback(self.feedback / f"{slug}.md")
        return item

    def check(self, slug: str) -> None:
        if not SLUG.match(slug) or not (self.letters / f"{slug}.txt").exists():
            raise KeyError(slug)

    def file(self, name: str) -> Path:
        """A file named by files(); anything else, or outside the letters folder, is a KeyError."""
        path = (self.letters / name).resolve()
        if self.letters.resolve() not in path.parents or path.suffix not in (".pdf", ".md") or not path.is_file():
            raise KeyError(name)
        return path

    def save(self, slug: str, body: dict) -> dict:
        self.check(slug)
        title = self.parse(slug)["title"]
        return write_feedback(self.feedback / f"{slug}.md", slug, title, body.get("rating") or None,
                              str(body.get("notes") or ""), body.get("status") or "new")


NAV = '<a href="/" style="margin-left:auto;margin-right:16px;font-size:14px;color:inherit">Applications ↗</a>'


def market_page(state_path: str) -> bytes:
    """The Stack & Pay dashboard, rebuilt from the scanner's database on each load."""
    from scanner.metrics import dashboard_html
    from scanner.state import State
    return dashboard_html(State(state_path)).replace("<!--NAV-->", NAV, 1).encode()


def handler(library: Library, state_path: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet: one line per error only
            if args and str(args[1]).startswith(("4", "5")):
                sys.stderr.write(f"{self.command} {self.path} {args[1]}\n")

        def send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, status: int = 200) -> None:
            self.send(status, json.dumps(data).encode(), "application/json")

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path in ("/", "/index.html"):
                    return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if path == "/market" and state_path:
                    return self.send(200, market_page(state_path), "text/html; charset=utf-8")
                if path == "/api/applications":
                    return self.json(library.all())
                if path.startswith("/api/applications/"):
                    return self.json(library.detail(path.removeprefix("/api/applications/")))
                if path.startswith("/files/"):
                    file = library.file(path.removeprefix("/files/"))
                    kind = "application/pdf" if file.suffix == ".pdf" else "text/plain; charset=utf-8"
                    return self.send(200, file.read_bytes(), kind)
            except KeyError:
                pass
            self.json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            match = re.fullmatch(r"/api/applications/([^/]+)/feedback", urlparse(self.path).path)
            if not match:
                return self.json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            # Only this page may write: a form on another site cannot set this header.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.json({"error": "JSON only"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                return self.json(library.save(match.group(1), body))
            except KeyError:
                return self.json({"error": "no such application"}, HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=Path, help="the jobs folder (default: [review] jobs_dir in the config)")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    config = load_config() if config_path().is_file() else {}
    jobs = args.jobs or config.get("review", {}).get("jobs_dir")
    if not jobs:
        raise SystemExit("the review tool is off: set [review] jobs_dir in the config, or pass --jobs")
    library = Library(Path(jobs).expanduser())
    if not library.letters.is_dir():
        raise SystemExit(f"no letters folder at {library.letters}")
    state_path = config.get("run", {}).get("state_path")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(library, state_path))
    print(f"Reviewing {len(library.slugs())} applications at http://127.0.0.1:{args.port}"
          + (f", market dashboard at http://127.0.0.1:{args.port}/market" if state_path else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
