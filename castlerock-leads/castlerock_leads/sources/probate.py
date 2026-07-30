"""Probate estate legal notices — the primary estate-sale signal.

Colorado law (C.R.S. 15-12-801) requires the personal representative of every
probated estate to publish a **Notice to Creditors** in a county newspaper.
For Douglas County these run in the Douglas County News-Press and are
aggregated on the Colorado Press Association's site,
``publicnoticecolorado.com`` (and the county's own ``publicnotices.douglas.co.us``).

Why this beats scraping obituaries:

* It marks an estate that is *actively being administered* — real estate is
  genuinely likely to sell, not merely a death that may lead nowhere.
* It **names the personal representative** (and often their address/attorney) —
  the actual decision-maker to contact. Obituaries never give you that.
* It is public *by legal design*, published precisely to be read — no terms of
  service friction.

The notice body is fixed by statute, so ``parse_notice_text`` is genuinely
correct and unit-tested offline. Only the search/fetch selectors depend on the
live site and are confirmed with ``check-endpoints``.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from ..config import Config
from ..http import HttpClient
from ..models import Lead
from ..util import clean, parse_date

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.publicnoticecolorado.com/Search.aspx"

# --- statutory notice parsing (pure, unit-tested) -------------------------
_DECEDENT = re.compile(
    r"Estate\s+of\s+(.+?)\s*(?:,\s*(?:a[./]?k[./]?a|aka)\b|,?\s*Deceased\b|,?\s*Case\b)",
    re.I | re.S,
)
_CASE = re.compile(r"Case\s*(?:Number|No\.?|#)?\s*[:\-]?\s*(\d{2,4}\s*PR\s*\d+)", re.I)
# Name capture is deliberately case-sensitive (names start with a capital) so
# the case-insensitive label does not run on into lowercase prose such as
# "...to the personal representative or to the District Court...". Only the
# literal label words are matched case-insensitively via the inline (?i:) group.
_PR_LABELED = re.compile(
    r"(?i:Personal\s+Representative)\s*[:\-]\s*([A-Z][A-Za-z.''\-]+(?:\s+[A-Z][A-Za-z.''\-]+){0,3})",
)
_PR_SIGNATURE = re.compile(
    r"([A-Z][A-Za-z.''\-]+(?:\s+[A-Z][A-Za-z.''\-]+){1,3})\s*[,\n]\s*(?i:Personal\s+Representative)",
)
_ADDRESS = re.compile(
    r"(\d{1,6}\s+[A-Za-z0-9.\- ]+(?:St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Ln|Lane|"
    r"Ct|Court|Way|Blvd|Cir|Circle|Pl|Place|Ter|Trail|Pkwy)\.?[,\s]+"
    r"[A-Za-z ]+,?\s*CO\s*\d{5})",
    re.I,
)
_FIRST_PUB = re.compile(
    r"First\s+Publication[:\s]+([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})",
    re.I,
)


def parse_notice_text(text: str) -> dict:
    """Extract structured fields from a Notice to Creditors body."""
    flat = re.sub(r"[ \t]+", " ", text)
    out: dict = {
        "name": None,
        "case_number": None,
        "contact_name": None,
        "contact_address": None,
        "first_publication": None,
    }

    m = _DECEDENT.search(flat)
    if m:
        out["name"] = clean(m.group(1))

    m = _CASE.search(flat)
    if m:
        out["case_number"] = re.sub(r"\s+", " ", m.group(1)).strip().upper()

    m = _PR_LABELED.search(flat) or _PR_SIGNATURE.search(flat)
    if m:
        out["contact_name"] = clean(m.group(1))

    m = _ADDRESS.search(flat)
    if m:
        out["contact_address"] = clean(m.group(1))

    m = _FIRST_PUB.search(flat)
    if m:
        d = parse_date(m.group(1))
        if d:
            out["first_publication"] = d

    return out


def notice_to_lead(text: str, source: str, url: Optional[str] = None) -> Optional[Lead]:
    fields = parse_notice_text(text)
    if not fields["name"]:
        return None
    return Lead(
        kind="probate",
        source=source,
        name=fields["name"],
        case_number=fields["case_number"],
        contact_name=fields["contact_name"],
        contact_address=fields["contact_address"],
        death_date=fields["first_publication"],  # proxy timestamp for dedupe
        detail_url=url,
        city="Castle Rock",
    )


def is_estate_notice(text: str) -> bool:
    """True if the notice text looks like a probate Notice to Creditors."""
    t = text.lower()
    return "estate of" in t and (
        "notice to creditors" in t or "personal representative" in t
    )


# --- source ---------------------------------------------------------------
class ProbateSource:
    def __init__(self, config: Config, client: HttpClient):
        self.config = config
        self.client = client
        self.cfg = config.get("probate", {})

    def fetch(self) -> list[Lead]:
        if not self.cfg.get("enabled", True):
            return []
        try:
            html = self._fetch_search()
        except Exception as exc:  # noqa: BLE001
            log.error("Probate notice search failed: %s", exc)
            return []
        leads = self._parse_search_page(html)
        return list(self._filter(leads))

    def _fetch_search(self) -> str:
        # The CPA search is an ASP.NET form. Keyword + county are configurable;
        # confirm the exact field names with check-endpoints. We look for estate
        # notices in the configured county.
        url = self.cfg.get("search_url", SEARCH_URL)
        params = self.cfg.get(
            "search_params",
            {
                "keyword": "estate of",
                "county": self.cfg.get("county", "Douglas"),
            },
        )
        resp = self.client.get(url, params=params)
        return resp.text

    def _parse_search_page(self, html: str) -> list[Lead]:
        """Extract notices from a search results page.

        Handles two shapes: results that embed the full notice text inline, and
        results that link to a detail page we must follow.
        """
        soup = BeautifulSoup(html, "lxml")
        leads: list[Lead] = []

        # Inline notice blocks.
        for block in soup.select(
            "[class*=notice], [class*=result], article, .searchResult"
        ):
            text = block.get_text("\n", strip=True)
            if is_estate_notice(text):
                link = block.find("a", href=True)
                url = _absolutize(link["href"]) if link else None
                lead = notice_to_lead(text, "publicnoticecolorado.com", url)
                if lead:
                    leads.append(lead)

        # Fall back to following detail links if no inline notices were found.
        if not leads:
            for link in soup.select("a[href]"):
                href = link.get("href", "")
                if "notice" in href.lower() or "detail" in href.lower():
                    lead = self._fetch_detail(_absolutize(href))
                    if lead:
                        leads.append(lead)

        return leads

    def _fetch_detail(self, url: str) -> Optional[Lead]:
        try:
            resp = self.client.get(url)
        except Exception as exc:  # noqa: BLE001
            log.debug("probate detail fetch failed %s: %s", url, exc)
            return None
        text = BeautifulSoup(resp.text, "lxml").get_text("\n", strip=True)
        if not is_estate_notice(text):
            return None
        return notice_to_lead(text, "publicnoticecolorado.com", url)

    def _filter(self, leads: Iterable[Lead]) -> Iterable[Lead]:
        # These notices are already county-scoped by the search; keep all of
        # them (the property, if any, is confirmed later by GIS enrichment).
        seen: set[str] = set()
        for lead in leads:
            fp = lead.fingerprint()
            if fp in seen:
                continue
            seen.add(fp)
            yield lead


def _absolutize(href: str) -> str:
    if href.startswith("http"):
        return href
    return "https://www.publicnoticecolorado.com/" + href.lstrip("/")
