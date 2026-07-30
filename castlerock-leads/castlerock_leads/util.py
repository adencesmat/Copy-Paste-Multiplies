"""Small parsing helpers shared across sources."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser


def make_soup(html: str) -> BeautifulSoup:
    """Parse HTML, preferring lxml but falling back to the stdlib parser.

    lxml is faster and more lenient, but it needs a compiled wheel that isn't
    always available on a fresh machine. Falling back to Python's built-in
    ``html.parser`` means the pipeline runs even if lxml failed to install.
    """
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - missing/broken lxml, use stdlib parser
        return BeautifulSoup(html, "html.parser")

_AGE_PATTERNS = [
    re.compile(r"\bage[d]?\s+(\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})\s+years?\s+(?:of\s+age|old)\b", re.I),
    re.compile(r",\s*(\d{1,3})\s*,"),  # "John Smith, 87, of Castle Rock"
]


def parse_age(text: str | None) -> Optional[int]:
    if not text:
        return None
    for pat in _AGE_PATTERNS:
        m = pat.search(text)
        if m:
            age = int(m.group(1))
            if 0 < age < 120:
                return age
    return None


def parse_date(text: str | None) -> Optional[date]:
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return dateparser.parse(text, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def parse_money(text: str | None) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[-+]?\$?\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def clean(text: str | None) -> Optional[str]:
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def days_until(d: Optional[date]) -> Optional[int]:
    if d is None:
        return None
    return (d - date.today()).days


def normalize_address(address: str | None) -> str:
    """Normalize a street address for matching across sources.

    Takes the street line (before the first comma), upper-cases it, strips
    punctuation, collapses whitespace, and standardizes common suffixes so that
    e.g. "123 Wolfensberger Rd." and "123 WOLFENSBERGER ROAD" compare equal.
    """
    if not address:
        return ""
    street = address.split(",")[0]
    up = re.sub(r"[^A-Z0-9 ]", " ", street.upper())
    tokens = up.split()
    suffix = {
        "STREET": "ST", "ROAD": "RD", "AVENUE": "AVE", "DRIVE": "DR",
        "LANE": "LN", "COURT": "CT", "BOULEVARD": "BLVD", "CIRCLE": "CIR",
        "PLACE": "PL", "TERRACE": "TER", "PARKWAY": "PKWY", "TRAIL": "TRL",
        "HIGHWAY": "HWY", "POINT": "PT", "PATH": "PATH", "WAY": "WAY",
    }
    tokens = [suffix.get(t, t) for t in tokens]
    return " ".join(tokens)


def normalize_name(name: str | None) -> str:
    """Normalize a person name for fuzzy matching against assessor owners.

    Assessor owner records are usually ``LAST FIRST`` and upper-cased; obituary
    names are ``First Last``. This reduces both to a sorted token set so the two
    orderings compare equal.
    """
    if not name:
        return ""
    tokens = re.findall(r"[A-Za-z]+", name.upper())
    # Drop common suffixes/titles that only appear on one side.
    drop = {"JR", "SR", "II", "III", "IV", "MR", "MRS", "MS", "DR", "THE", "ESTATE", "OF"}
    tokens = [t for t in tokens if t not in drop and len(t) > 1]
    return " ".join(sorted(tokens))
