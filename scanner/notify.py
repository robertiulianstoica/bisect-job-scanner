"""Email through an SMTP server given as a Symfony Mailer DSN
(smtp://user:password@smtp.example.com:587), so the scanner can share a sender with
an existing app."""

from __future__ import annotations

import html
import smtplib
import ssl
from datetime import date, datetime, timezone
from email.message import EmailMessage
from urllib.parse import unquote, urlparse


def parse_dsn(dsn: str) -> dict:
    parsed = urlparse(dsn)
    scheme = parsed.scheme.lower()
    if scheme not in {"smtp", "smtps"}:
        raise ValueError(f"unsupported mailer scheme '{scheme}' (use smtp:// or smtps://)")
    port = parsed.port or (465 if scheme == "smtps" else 587)
    return {
        "host": parsed.hostname,
        "port": port,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "implicit_tls": scheme == "smtps" or port == 465,
    }


def send(dsn: str, sender: str, to: str, subject: str, text: str, html_body: str) -> None:
    conf = parse_dsn(dsn)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    if conf["implicit_tls"]:
        server = smtplib.SMTP_SSL(conf["host"], conf["port"], context=context, timeout=30)
    else:
        server = smtplib.SMTP(conf["host"], conf["port"], timeout=30)
        server.starttls(context=context)
    with server:
        if conf["user"]:
            server.login(conf["user"], conf["password"] or "")
        server.send_message(message)


# Sources whose dates are not the posting date (hipo shows its daily refresh).
UNDATED = {"bestjobs", "hipo"}


def _moment(value) -> datetime | None:
    """A posted_at as it comes out of the DataFrame: Timestamp, NaT, string or None."""
    if value is None or value != value:  # NaT and NaN are not equal to themselves
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def freshness(job: dict, now: datetime | None = None) -> str | None:
    """How long ago the advert went up: to the minute when the source gives a
    time, to the day when it gives only a date, nothing when its date is not
    the posting date. Midnight exactly means a date without a time."""
    if job.get("site") in UNDATED:
        return None
    now = now or datetime.now(timezone.utc)
    at = _moment(job.get("posted_at"))
    if at and (at.hour, at.minute, at.second) != (0, 0, 0):
        minutes = max(0, int((now - at).total_seconds() // 60))
        if minutes < 60:
            return f"posted {minutes} min ago"
        if minutes < 48 * 60:
            return f"posted {minutes // 60} h ago"
        return f"posted {minutes // 1440} days ago"
    day = job.get("date_posted")
    if hasattr(day, "date"):
        day = day.date()
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day[:10])
        except ValueError:
            day = None
    if not isinstance(day, date):
        return None
    days = (now.date() - day).days
    return "posted today" if days <= 0 else "posted yesterday" if days == 1 else f"posted {days} days ago ({day})"


def applicants(job: dict) -> str | None:
    """LinkedIn's count; "Be among the first 25" is read as 25, so 25 reads as under 25."""
    count = job.get("num_applicants")
    if not isinstance(count, (int, float)) or count != count:
        return None
    return "under 25 applicants" if int(count) == 25 else f"{int(count)} applicants"


def render(jobs: list[dict]) -> tuple[str, str, str]:
    """Subject, plain text and HTML for a batch of new jobs."""
    subject = f"{len(jobs)} new job{'s' if len(jobs) != 1 else ''}: " + ", ".join(
        dict.fromkeys(j.get("company") or "?" for j in jobs)
    )
    lines, rows = [], []
    secondary_started = False
    for job in jobs:
        if not secondary_started and any(str(f).startswith("TypeScript/Python role") for f in job.get("flags") or []):
            secondary_started = True
            lines.append("--- TypeScript / Python roles (matched on your strengths) ---\n")
            rows.append('</ul><h3 style="font-family:sans-serif">TypeScript / Python roles (matched on your strengths)</h3>'
                        '<ul style="font-family:sans-serif;line-height:1.4">')
        facts = [freshness(job), applicants(job), job.get("site"), job.get("location") or "location not stated"]
        facts += list(job.get("flags") or [])
        facts = [str(f) for f in facts if f]
        lines.append(f"{job.get('title')} at {job.get('company')}\n  {' · '.join(facts)}\n  {job.get('job_url')}\n")
        rows.append(
            f"<li><a href=\"{html.escape(str(job.get('job_url')))}\"><b>{html.escape(str(job.get('title')))}</b></a>"
            f" at {html.escape(str(job.get('company')))}<br><small>{html.escape(' · '.join(facts))}</small></li>"
        )
    text = "\n".join(lines)
    body = f"<ul style=\"font-family:sans-serif;line-height:1.4\">{''.join(rows)}</ul>"
    return subject, text, body
