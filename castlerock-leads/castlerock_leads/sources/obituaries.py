"""Obituary sources for Castle Rock, CO.

Two providers cover almost all Castle Rock funeral homes:

* **Legacy.com** aggregates most local funeral homes and exposes a JSON feed
  behind the visible listing page.
* **Dignity Memorial** covers the SCI-owned homes and renders obituary cards
  server-side.

Both are parsed into the same ``Lead`` shape. The extraction logic lives in
pure functions (``parse_legacy_json`` / ``parse_dignity_html``) that are unit
tested against saved fixtures, so the parsers are verifiable without network
access. Selectors/URLs are configurable for when a provider changes markup.
"""

from __future__ import annotations

import logging
from typing import Iterable

from bs4 import BeautifulSoup

from ..config import Config
from ..http import HttpClient
from ..models import Lead
from ..util import clean, parse_age, parse_date

log = logging.getLogger(__name__)

LEGACY_FEED = (
    "https://www.legacy.com/api/_frontend/search/location"
    "?state=colorado&city=castle-rock&limit=50"
)
LEGACY_PAGE = "https://www.legacy.com/us/obituaries/local/colorado/castle-rock"
DIGNITY_PAGE = "https://www.dignitymemorial.com/obituaries/castle-rock-co"


# --- pure parsers ---------------------------------------------------------
def parse_legacy_json(payload: dict) -> list[Lead]:
    """Parse Legacy.com's obituary search JSON.

    The feed nests obituary objects under ``data``/``obituaries``/``results``
    depending on endpoint version; we probe each. Each object typically carries
    ``name``/``fullName``, ``age``, a death date and a canonical URL.
    """
    items = _first_list(
        payload,
        ("obituaries", "results", "data", "items", "hits"),
    )
    leads: list[Lead] = []
    for obj in items:
        if not isinstance(obj, dict):
            continue
        name = clean(
            obj.get("fullName")
            or obj.get("name")
            or _join_name(obj.get("firstName"), obj.get("lastName"))
        )
        age = obj.get("age")
        if isinstance(age, str):
            age = int(age) if age.strip().isdigit() else parse_age(age)
        death = parse_date(
            obj.get("deathDate")
            or obj.get("dateOfDeath")
            or obj.get("publishDate")
        )
        url = obj.get("url") or obj.get("obituaryUrl") or obj.get("link")
        if url and url.startswith("/"):
            url = "https://www.legacy.com" + url
        if not name:
            continue
        leads.append(
            Lead(
                kind="obituary",
                source="legacy.com",
                name=name,
                age=age if isinstance(age, int) else None,
                death_date=death,
                detail_url=url,
                city="Castle Rock",
            )
        )
    return leads


def parse_dignity_html(html: str) -> list[Lead]:
    """Parse Dignity Memorial obituary cards from server-rendered HTML."""
    soup = BeautifulSoup(html, "lxml")
    leads: list[Lead] = []
    # Cards are anchors/containers whose class contains "obituary" and hold a
    # name element plus a life-dates element.
    cards = soup.select(
        "[class*=obituary-card], [class*=obituaryCard], article[class*=obituary]"
    )
    for card in cards:
        name_el = card.select_one(
            "[class*=name], h2, h3, [class*=title]"
        )
        name = clean(name_el.get_text()) if name_el else None
        if not name:
            continue
        text = card.get_text(" ", strip=True)
        link = card.find("a", href=True)
        url = link["href"] if link else None
        if url and url.startswith("/"):
            url = "https://www.dignitymemorial.com" + url
        leads.append(
            Lead(
                kind="obituary",
                source="dignitymemorial.com",
                name=name,
                age=parse_age(text),
                death_date=_extract_death_date(card, text),
                detail_url=url,
                city="Castle Rock",
            )
        )
    return leads


def _extract_death_date(card, text: str):
    date_el = card.select_one("[class*=date], time")
    if date_el:
        d = parse_date(date_el.get("datetime") or date_el.get_text())
        if d:
            return d
    # Fall back to explicit month-day-year strings in the card text. We do not
    # infer a date from bare "1938 - 2026" life spans because that yields only a
    # year, which is too coarse for the lookback window and dedup fingerprint.
    return None


# --- helpers --------------------------------------------------------------
def _first_list(payload: dict, keys) -> list:
    for key in keys:
        val = payload.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            nested = _first_list(val, keys)
            if nested:
                return nested
    return []


def _join_name(first, last) -> str | None:
    parts = [p for p in (first, last) if p]
    return " ".join(parts) if parts else None


# --- source ---------------------------------------------------------------
class ObituarySource:
    def __init__(self, config: Config, client: HttpClient):
        self.config = config
        self.client = client
        self.cfg = config["obituaries"]

    def fetch(self) -> list[Lead]:
        if not self.cfg.get("enabled", True):
            return []
        leads: list[Lead] = []
        sources = self.cfg.get("sources", {})
        if sources.get("legacy", True):
            leads.extend(self._fetch_legacy())
        if sources.get("dignity", True):
            leads.extend(self._fetch_dignity())
        return list(self._filter(leads))

    def _fetch_legacy(self) -> list[Lead]:
        try:
            payload = self.client.get_json(
                self.cfg.get("legacy_feed_url", LEGACY_FEED)
            )
            if payload:
                return parse_legacy_json(payload)
        except Exception as exc:  # noqa: BLE001
            log.error("Legacy.com feed failed: %s", exc)
        return []

    def _fetch_dignity(self) -> list[Lead]:
        try:
            resp = self.client.get(self.cfg.get("dignity_url", DIGNITY_PAGE))
            return parse_dignity_html(resp.text)
        except Exception as exc:  # noqa: BLE001
            log.error("Dignity Memorial fetch failed: %s", exc)
        return []

    def _filter(self, leads: Iterable[Lead]) -> Iterable[Lead]:
        min_age = self.cfg.get("min_age", 0)
        keep_unknown = self.cfg.get("keep_when_age_unknown", True)
        for lead in leads:
            if lead.age is None:
                if not keep_unknown:
                    continue
            elif lead.age < min_age:
                continue
            yield lead
