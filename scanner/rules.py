"""The filters a job has to pass before it is worth an email."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    flags: tuple[str, ...] = ()


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w.+#-]){re.escape(word)}(?![\w+#-])", text, re.IGNORECASE) is not None


def _any_word(text: str, words: list[str]) -> str | None:
    return next((w for w in words if _has_word(text, w)), None)


# Common short words of each language, for telling which one an advert is in.
_STOPWORDS = {
    "en": {"the", "and", "you", "we", "with", "for", "our", "are", "will", "your", "of", "to", "in", "is"},
    "de": {"und", "der", "die", "das", "wir", "mit", "für", "sie", "ist", "auf", "eine", "zu", "ihre", "bei"},
    "fr": {"et", "le", "la", "les", "nous", "vous", "pour", "avec", "des", "une", "est", "du", "au"},
    "nl": {"en", "het", "een", "wij", "jij", "voor", "met", "van", "je", "onze", "bij"},
    "es": {"y", "el", "los", "las", "para", "con", "una", "del", "nuestro", "tu"},
    "it": {"il", "gli", "per", "con", "una", "della", "nostro", "sei", "che"},
}


def is_english(text: str) -> bool:
    """True when English words outnumber those of each other language."""
    words = re.findall(r"[a-zäöüßéèàçñ]+", (text or "").lower())
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    return counts["en"] > 0 and counts["en"] > max(v for k, v in counts.items() if k != "en")


LEGAL_FORMS = {"uab", "srl", "sa", "gmbh", "ag", "inc", "ltd", "llc", "plc", "bv", "nv", "oy", "ab", "as", "sp", "zoo",
               "limited", "corp", "co", "kg", "sarl", "sas", "spa"}


def company_name(name: str | None) -> str:
    """A company's name for comparing: "REIZ TECH UAB" and "Reiz Tech" match,
    so do "Code Compass 🧭" and "Code Compass". Legal forms, punctuation and
    emoji are dropped."""
    words = re.sub(r"[^\w\s]", " ", (name or "").lower().replace("s.r.l.", "srl").replace("sp. z o.o.", "sp zoo")).split()
    while len(words) > 1 and words[-1] in LEGAL_FORMS:
        words.pop()
    return " ".join(words)


def same_company(name: str | None, names: list[str]) -> bool:
    mine = company_name(name)
    return bool(mine) and any(company_name(n) == mine for n in names)


# "PHP" is also the Philippine peso: "1,000 PHP De Minimis", "PHP 50,000 a month".
PESOS = re.compile(r"(?:₱|\bPHP\s?)\d[\d,.]*(?:\s?k\b)?|\b\d[\d,.]*\s?(?:k\s?)?PHP\b")


def check_content(job: dict, search: dict) -> Verdict:
    title = job.get("title") or ""
    # LinkedIn's company industry catches what an advert leaves unsaid
    # ("Gambling Facilities and Casinos" behind a WordPress role).
    text = f"{title}\n{job.get('description') or ''}\n{job.get('company_industry') or ''}"
    text = PESOS.sub(" ", text)
    if hit := _any_word(title, search.get("exclude_titles", [])):
        return Verdict(False, f"title: {hit}")
    # "(m/f/d)" is the law in German adverts, English ones included: such a
    # title is dropped only when the advert is not written in English.
    if (hit := _any_word(title, search.get("exclude_titles_unless_english", []))) \
            and not is_english(job.get("description") or ""):
        return Verdict(False, f"title: {hit}, advert not in English")
    if same_company(job.get("company"), search.get("exclude_companies", [])):
        return Verdict(False, "excluded company")
    if hit := _any_word(text, search.get("exclude", [])):
        return Verdict(False, f"mentions {hit}")
    if not _any_word(text, search.get("include", [])):
        return Verdict(False, "no wanted stack")
    flags = ()
    if same_company(job.get("company"), search.get("applied_companies", [])):
        flags = ("already applied here",)
    secondary = check_secondary_stack(title, text, search)
    if secondary is not None and not secondary.keep:
        return secondary
    return Verdict(True, flags=flags + (secondary.flags if secondary else ()))


def check_secondary_stack(title: str, text: str, search: dict) -> Verdict | None:
    """A job whose stack is only TypeScript/React/Python/Node, with none of
    the primary stack and no wanted title, has to match your strengths
    ([search] strengths) twice to be worth an email: React or Node counts once, and each group of
    domain words (payments, integrations, e-commerce, experiments, LLMs,
    migrations) once. None when the job is a primary-stack one."""
    secondary = search.get("secondary_stack", [])
    if not secondary:
        return None
    primary = [w for w in search.get("include", []) if w not in secondary]
    if _any_word(text, primary) or _any_word(title, search.get("title_terms", [])):
        return None
    hits = []
    if stack := _any_word(text, search.get("secondary_with", [])):
        hits.append(stack)
    for group in search.get("strengths", []):
        if word := _any_word(text, group):
            hits.append(word)
    if len(hits) < search.get("secondary_min_strengths", 2):
        return Verdict(False, "TypeScript/Python only, too few of your strengths")
    return Verdict(True, flags=("TypeScript/Python role: " + ", ".join(hits),))


# "Híbrido - Madrid", "hybride", "ibrido", "Hybrid", "presencial", "vor Ort" in a title or location.
HYBRID_WORDS = re.compile(r"\b(?:hybrid|h[ií]brid[oa]|hybride|ibrido|on-?site|presencial|presenziale|vor ort|sur site)\b", re.I)
NOT_REMOTE = re.compile(r"\b(?:no|not|non)[- ]remote\b|\bremote work is not\b", re.I)


def linkedin_city_abroad(job: dict, in_home: bool) -> bool:
    """A LinkedIn result placed in a city outside the home country whose advert
    does not itself offer remote work. LinkedIn's remote filter is loose: most
    of these are hybrid or on-site roles (Cisco Budapest, Zalando Berlin)."""
    location = job.get("location") or ""
    if job.get("site") != "linkedin" or in_home or "," not in location or "(remote search)" in location:
        return False
    from scanner.classify import HYBRID, REMOTE
    text = (job.get("description") or "")[:6000]
    says_remote = re.search(r"\bremote(?:ly)?\b", text, re.I) and not NOT_REMOTE.search(text)
    return not says_remote or bool(HYBRID.search(text) and not REMOTE.search(text))


def check_location(job: dict, rules: dict) -> Verdict:
    """Decide from the location and any country list whether you can work it.

    Home country: fine. Another listed EU country: fine as a contractor.
    A region that includes you: fine. Only other regions: out. Hybrid or
    on-site anywhere but home: out. Nothing stated: kept, marked unclear.
    """
    location = job.get("location") or ""
    restrictions = job.get("location_restrictions") or ""
    where = f"{location}; {restrictions}"
    home = rules.get("home", [])
    contract = rules.get("contract_ok", [])

    in_home = _any_word(where, home)
    if linkedin_city_abroad(job, bool(in_home)):
        return Verdict(False, "LinkedIn city abroad, advert does not offer remote")
    workplace = f"{where} {job.get('title') or ''}".lower()
    if HYBRID_WORDS.search(workplace) and not in_home:
        return Verdict(False, "hybrid/on-site abroad")
    if in_home:
        on_site = bool(HYBRID_WORDS.search(workplace))
        cities = rules.get("home_cities", [])
        if on_site and cities and not _any_word(where, cities):
            return Verdict(False, "on-site/hybrid outside home city")
        return Verdict(True)
    if hit := _any_word(where, rules.get("regions_ok", [])):
        return Verdict(True, flags=(f"open to {hit}",))
    if hit := _any_word(where, contract):
        return Verdict(True, flags=(f"{hit} only: offer B2B",))
    if hit := _any_word(where, rules.get("regions_no", [])):
        return Verdict(False, f"location: {hit}")
    if not location.strip() or location.strip().lower() in {"remote", "remote (remote)"}:
        return Verdict(True, flags=("location unclear",))
    return Verdict(False, f"location: {location}")


def check_applicants(job: dict, max_applicants: int | None) -> Verdict:
    count = job.get("num_applicants")
    if max_applicants and isinstance(count, (int, float)) and count == count and count >= max_applicants:
        return Verdict(False, f"{int(count)} applicants")
    return Verdict(True)
