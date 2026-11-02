"""Minimal RSS reading for job boards that publish a feed."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from jobspy.ats import DEFAULT_HEADERS


def fetch_items(url: str, timeout: int = 30) -> list[ET.Element]:
    try:
        response = requests.get(url, headers={**DEFAULT_HEADERS, "Accept": "application/rss+xml,application/xml"}, timeout=timeout)
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return []
    return root.findall("./channel/item")


def text(item: ET.Element, tag: str, ns: dict | None = None) -> str | None:
    node = item.find(tag, ns or {})
    return node.text.strip() if node is not None and node.text else None


def pub_date(item: ET.Element):
    raw = text(item, "pubDate")
    try:
        return parsedate_to_datetime(raw) if raw else None
    except (TypeError, ValueError):
        return None
