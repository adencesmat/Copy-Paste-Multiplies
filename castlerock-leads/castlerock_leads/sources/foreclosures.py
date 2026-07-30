"""Douglas County Public Trustee foreclosure source.

The Public Trustee runs a legacy Struts application (``*.do``) at
``apps.douglas.co.us/apps/publictrustee``. There is no JSON API: a search is
submitted as form parameters and results come back as an HTML table, one row
per foreclosure, linking to ``propertyDetails.do?id=YYYY-NNNN``.

Because the exact form field names and result-table markup can only be read
from the live site (which blocks datacenter IPs), the selectors below are
centralised in ``PARSER`` and can be adjusted after running
``check-endpoints`` from your own network. The parsing itself is unit-tested
against a saved fixture so behaviour is verifiable offline.
"""

from __future__ import annotations

import logging
from typing import Iterable

from bs4 import BeautifulSoup

from ..config import Config
from ..http import HttpClient
from ..models import Lead
from ..util import clean, days_until, parse_date, parse_money

log = logging.getLogger(__name__)

# Column header text -> Lead attribute. Header matching is case-insensitive and
# substring-based so minor wording changes ("Sale Date" vs "Date of Sale") still
# map correctly. Adjust here if check-endpoints shows different headers.
COLUMN_MAP = {
    "pt": "pt_number",
    "pt no": "pt_number",
    "pt #": "pt_number",
    "grantor": "name",
    "owner": "name",
    "borrower": "name",
    "address": "address",
    "property address": "address",
    "sale date": "sale_date",
    "date of sale": "sale_date",
    "original": "original_balance",
    "amount": "original_balance",
}


def _map_header(header: str) -> str | None:
    h = header.strip().lower()
    for key, attr in COLUMN_MAP.items():
        if key in h:
            return attr
    return None


def parse_results_html(html: str, base_url: str, details_path: str) -> list[Lead]:
    """Parse a Public Trustee results table into Lead objects."""
    soup = BeautifulSoup(html, "lxml")
    table = _find_results_table(soup)
    if table is None:
        log.warning("No results table found in foreclosure response")
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    # Header row -> column index -> attribute
    header_cells = rows[0].find_all(["th", "td"])
    col_attr: dict[int, str] = {}
    for idx, cell in enumerate(header_cells):
        attr = _map_header(cell.get_text())
        if attr:
            col_attr[idx] = attr

    leads: list[Lead] = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        lead = Lead(kind="foreclosure", source="douglas_public_trustee")
        for idx, cell in enumerate(cells):
            attr = col_attr.get(idx)
            if not attr:
                continue
            value = clean(cell.get_text())
            if attr == "sale_date":
                lead.sale_date = parse_date(value)
            elif attr == "original_balance":
                lead.original_balance = parse_money(value)
            else:
                setattr(lead, attr, value)
            # Capture the details link if present.
            link = cell.find("a", href=True)
            if link and details_path.split("/")[-1] in link["href"]:
                lead.detail_url = _absolutize(base_url, link["href"])
        if lead.pt_number or lead.name or lead.address:
            leads.append(lead)
    return leads


def _find_results_table(soup: BeautifulSoup):
    """Heuristically locate the results table.

    Prefers a table whose header row mentions a PT number or sale date, which
    distinguishes the real results grid from layout tables.
    """
    best = None
    best_score = 0
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        text = header.get_text(" ", strip=True).lower()
        score = sum(1 for key in ("pt", "grantor", "sale", "address") if key in text)
        if score > best_score:
            best, best_score = table, score
    return best if best_score >= 2 else None


def _absolutize(base_url: str, href: str) -> str:
    if href.startswith("http"):
        return href
    return base_url.rstrip("/") + "/" + href.lstrip("/")


class ForeclosureSource:
    def __init__(self, config: Config, client: HttpClient):
        self.config = config
        self.client = client
        self.cfg = config["foreclosures"]

    def fetch(self) -> list[Lead]:
        if not self.cfg.get("enabled", True):
            return []
        base = self.cfg["base_url"].rstrip("/")
        search_url = base + self.cfg["search_path"]

        # The Struts search accepts empty criteria to list all active
        # foreclosures. Field names default to the app's known parameters and
        # can be overridden in config under foreclosures.search_params.
        params = self.cfg.get(
            "search_params",
            {"searchType": "criteria", "action": "Search"},
        )
        try:
            resp = self.client.post(search_url, data=params)
        except Exception as exc:  # noqa: BLE001 - source failures are non-fatal
            log.error("Foreclosure search failed: %s", exc)
            return []

        leads = parse_results_html(resp.text, base, self.cfg["details_path"])
        return list(self._filter(leads))

    def _filter(self, leads: Iterable[Lead]) -> Iterable[Lead]:
        max_days = self.cfg.get("max_days_to_sale", 0)
        for lead in leads:
            if not self.config.in_area(lead.address, lead.zip_code):
                continue
            if max_days:
                d = days_until(lead.sale_date)
                if d is not None and (d < 0 or d > max_days):
                    continue
            yield lead
