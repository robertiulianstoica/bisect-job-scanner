"""What kind of job a posting is, for counting the market: whether it is an
engineering role, its main programming language, and its region."""

from __future__ import annotations

import re

ENGINEERING = re.compile(
    r"engineer|developer|programmer|architect|full.?stack|back.?end|front.?end|software|devops|\bsre\b|tech(nical)? lead",
    re.IGNORECASE,
)
NOT_ENGINEERING = re.compile(
    r"manager|director|head of|analyst|support|sales|recruit|intern|graduate|junior|co-?op", re.IGNORECASE)

LANGUAGES = {
    "PHP": r"\bPHP\b|\bSymfony\b|\bLaravel\b",
    "TypeScript/JavaScript": r"\bTypeScript\b|\bJavaScript\b|\bNode(\.js|JS)?\b|\bReact\b",
    "Python": r"\bPython\b|\bDjango\b|\bFastAPI\b",
    "Java/Kotlin": r"\bJava\b(?!Script)|\bKotlin\b|\bSpring\b",
    "Go": r"\bGolang\b|\bGo\b(?=[ ,/)]|$)",
    "C#/.NET": r"C#|\.NET\b",
    "Ruby": r"\bRuby\b|\bRails\b",
    "Rust": r"\bRust\b",
    "Scala": r"\bScala\b",
    "C++": r"C\+\+",
}
CASE_SENSITIVE = {"Go", "Rust"}
PATTERNS = {k: re.compile(p, 0 if k in CASE_SENSITIVE else re.I) for k, p in LANGUAGES.items()}

EUROPE = re.compile(
    r"europe|emea|\beu\b|romania|bucharest|germany|berlin|munich|hamburg|frankfurt|france|paris|spain|madrid|barcelona|"
    r"portugal|lisbon|porto|poland|warsaw|krak|wroc|netherlands|amsterdam|rotterdam|ireland|dublin|italy|milan|rome|"
    r"sweden|stockholm|denmark|copenhagen|finland|helsinki|austria|vienna|czech|prague|belgium|brussels|ghent|greece|"
    r"athens|hungary|budapest|estonia|tallinn|lithuania|vilnius|latvia|riga|croatia|zagreb|bulgaria|sofia|slovakia|"
    r"slovenia|luxembourg|norway|oslo|switzerland|zurich|geneva|united kingdom|england|london|manchester|edinburgh|"
    r"\buk\b|cyprus|malta|serbia|belgrade|ukraine|kyiv|cluj|iasi|iaşi",
    re.I,
)
US_NAMES = re.compile(
    r"united states|\bu\.s\.|new york|\bnyc\b|san francisco|bay area|seattle|austin|boston|chicago|"
    r"los angeles|denver|atlanta|miami|washington|dallas|houston|san diego|san jose|palo alto|mountain view|"
    r"portland|philadelphia|pittsburgh|salt lake|lehi|minneapolis|raleigh|nashville|phoenix",
    re.I,
)
# Case matters here: "US" and state codes, not the word "us".
US_CODES = re.compile(r"\bUSA?\b|,\s*(?:AL|AZ|CA|CO|CT|DC|FL|GA|IL|IN|MA|MD|MI|MN|MO|NC|NJ|NV|NY|OH|OR|PA|TN|TX|UT|VA|WA|WI)\b")


def _us(text: str) -> bool:
    return bool(US_NAMES.search(text) or US_CODES.search(text))


# AI work, two kinds. "builds": AI in the title, or the advert asks to build AI
# agents / apps / bots / features (a company describing itself as an AI
# platform does not count). "uses": the advert asks to work with AI tools.
AI_TITLE = re.compile(
    r"\bAI\b|\bA\.I\.|\bLLMs?\b|\bGenAI\b|Generative|Machine Learning|\bML\b|Applied Scientist|\bAgent(s|ic)?\b|"
    r"Chatbot|Conversational|\bNLP\b|Deep Learning|Computer Vision|MLOps", re.I)
AI_BUILD = re.compile(
    r"(?:build|develop|design|ship|creat|architect|implement)\w*\s+(?:\w+\s+){0,5}(?:AI|LLM|GenAI|agentic|conversational)"
    r"[- ](?:\w+[- ])?(?:agents?|apps?|applications?|features?|products?|bots?|chatbots?|assistants?|copilots?|"
    r"workflows?|pipelines?|solutions?|services?)"
    r"|\bchat ?bots?\b|\bconversational AI\b|\bRAG\b|retrieval[- ]augmented|\bLLM[- ]powered|"
    r"\bLLM (?:apps?|applications?|features?|integrations?)", re.I)
AI_USE = re.compile(
    r"\bCopilot\b|\bCursor\b|\bClaude Code\b|\bCodex\b|\bWindsurf\b|AI[- ]assisted|AI[- ]augmented|"
    r"AI[- ]native (?:development|engineering|workflows?)|AI (?:coding|developer|development) (?:tools?|assistants?)|"
    r"(?:use|using|leverag\w*|embrac\w*|comfortable with)\s+(?:\w+\s+){0,3}AI(?: tools?| assistants?)?\b|"
    r"\bAI tools?\b|\bLLM tools?\b|prompt engineering", re.I)


def ai_kind(title: str | None, text: str | None) -> str | None:
    """'builds', 'uses' or None, for an engineering role."""
    if AI_TITLE.search(title or "") or AI_BUILD.search(text or ""):
        return "builds"
    if AI_USE.search(text or ""):
        return "uses"
    return None


# Scam signals in an advert's own text. Sentences that negate or warn ("we will
# never ask for a fee", "beware of recruiters on Telegram") are skipped: legitimate
# companies write those, and they are counted apart as fraud warnings.
SCAM_SIGNALS = {
    "asks for a fee": re.compile(
        r"\b(?:registration|training|application|processing|onboarding|starter)\s+fee\b|\bpay (?:a|the|an) (?:fee|deposit)\b|"
        r"purchase (?:your own|a|the) (?:laptop|equipment|starter kit)|\bgift cards?\b|send (?:money|payment)", re.I),
    "contact off-platform": re.compile(
        r"(?:contact|message|reach|text|apply|send)\w*\s+(?:\w+\s+){0,4}(?:on|via|through|at)\s+"
        r"(?:telegram|whatsapp|signal|skype|wechat)\b|telegram:\s*@|\bt\.me/|wa\.me/", re.I),
    "asks for ID or bank details": re.compile(
        r"(?:send|provide|submit) (?:\w+\s+){0,3}(?:passport|ID card|identity card|bank (?:details|account)|"
        r"social security|SSN|IBAN)\b", re.I),
    "unnamed client": re.compile(
        r"\b(?:on behalf of|for) (?:a|our) (?:confidential|undisclosed|prestigious|big ?4) client\b|\bconfidential client\b", re.I),
}
NEGATED = re.compile(r"\b(?:never|not|no|won't|don't|doesn't|cannot|beware|scams?|fraud|fraudulent|phishing|"
                     r"impersonat\w*|legitimate|suspicious|caution|warning)\b", re.I)
FRAUD_WARNING = re.compile(
    r"recruit(?:ment|ing) (?:fraud|scams?)|job (?:scams?|fraud)|impersonat\w+ (?:our|recruiters)|fraudulent (?:job|recruit|offers?)|"
    r"(?:never|not) (?:ask|request|require)\w* (?:\w+\s+){0,4}(?:fee|payment|money|bank)", re.I)


def scam_signals(text: str | None) -> list[str]:
    body = " ".join(s for s in re.split(r"(?<=[.!?\n])\s+", text or "") if not NEGATED.search(s))
    return [name for name, pattern in SCAM_SIGNALS.items() if pattern.search(body)]


def warns_of_fraud(text: str | None) -> bool:
    return bool(FRAUD_WARNING.search(text or ""))


HYBRID = re.compile(r"\bhybrid\b|\b(?:[1-4]|one|two|three|four) days? (?:a|per|each) week (?:in|at|from) (?:the |our )?"
                    r"(?:office|studio|hub)|\bin[- ]office (?:[1-4]|one|two|three|four) days?|"
                    r"\b(?:in|at) (?:the |our )?(?:office|studio|hub) (?:[1-4]|one|two|three|four) days?", re.I)
REMOTE = re.compile(r"\bfully remote\b|\b100\s?% remote\b|\bremote[- ]first\b|\bwork from anywhere\b|"
                    r"\bremote (?:role|position|job|opportunity)\b|\bthis (?:role|position) is remote\b|\bwork remotely\b", re.I)
ONSITE = re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\bin the office (?:five|5) days\b|\boffice[- ]based\b|"
                    r"\bin[- ]person\b|\bfull[- ]time in (?:the|our) office\b", re.I)


def work_mode(location: str | None, is_remote, text: str | None) -> str | None:
    """remote, hybrid, on-site, or None when the advert does not say. The
    location and the site's own flags first (Ashby: "(Remote)", "(Hybrid)",
    "(OnSite)"), then the text."""
    location = location or ""
    if re.search(r"\bhybrid\b", location, re.I):
        return "hybrid"
    if re.search(r"\bon-?site\b|\bin office\b", location, re.I):
        return "on-site"
    head = (text or "")[:6000]
    if re.search(r"\bremote\b", location, re.I) or is_remote in (1, True):
        return "hybrid" if HYBRID.search(head) else "remote"
    if HYBRID.search(head):
        return "hybrid"
    if REMOTE.search(head):
        return "remote"
    if ONSITE.search(head):
        return "on-site"
    return None


def is_engineering(title: str | None) -> bool:
    return bool(title) and bool(ENGINEERING.search(title)) and not NOT_ENGINEERING.search(title)


def main_language(title: str | None, text: str | None) -> str | None:
    """The language in the title, else the one the text names most often."""
    for name, pattern in PATTERNS.items():
        if pattern.search(title or ""):
            return name
    counts = {name: len(pattern.findall(text or "")) for name, pattern in PATTERNS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] else None


def region(location: str | None, text: str | None = None) -> str:
    """EU (Europe, UK and Switzerland included), US, or other. The location
    decides; the text only when the location says nothing more than Remote."""
    location = location or ""
    bare = not re.sub(r"(?i)remote|worldwide|anywhere|global|[\s(),/-]", "", location)
    place = f"{location} {(text or '')[:400]}" if bare else location
    europe, us = bool(EUROPE.search(place)), _us(place)
    if europe and not us:
        return "EU"
    if us and not europe:
        return "US"
    if europe and us:
        return "EU" if EUROPE.search(location) and not _us(location) else "US" if _us(location) else "other"
    return "other"
