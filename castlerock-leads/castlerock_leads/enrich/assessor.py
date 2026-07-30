"""Cross-reference leads against Douglas County parcel/assessor GIS data.

This is the "connected to the GIS maps" layer. Two lookups:

* **By address** (foreclosures already carry an address) -> confirm the parcel,
  attach the assessor account number and actual value.
* **By owner name** (obituaries carry only a decedent name) -> find whether
  that person owned a parcel in the Castle Rock area, and if so attach it. This
  is what turns an obituary into an actionable property lead.

The county parcels layer is a standard ArcGIS ``MapServer`` that supports the
REST ``/query`` operation (``where=... &outFields=* &f=json``). Field names
vary by county; they are read from config and can be confirmed with
``check-endpoints``.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..config import Config
from ..http import HttpClient
from ..models import Lead, Property
from ..util import normalize_name, parse_money

log = logging.getLogger(__name__)


class AssessorEnricher:
    def __init__(self, config: Config, client: HttpClient):
        self.config = config
        self.client = client
        self.cfg = config["enrichment"]
        self.fields = self.cfg.get("fields", {})
        self.owner_field = self.fields.get("owner", "OWNER_NAME")
        self.addr_field = self.fields.get("site_address", "SITE_ADDR")
        self.account_field = self.fields.get("account", "ACCOUNT")
        self.city_field = self.fields.get("city", "SITE_CITY")
        self.zip_field = self.fields.get("zip", "SITE_ZIP")

    @property
    def query_url(self) -> str:
        base = self.cfg["parcels_mapserver"].rstrip("/")
        layer = self.cfg.get("parcels_layer_id", 0)
        return f"{base}/{layer}/query"

    def enrich_all(self, leads: Iterable[Lead]) -> None:
        if not self.cfg.get("enabled", True):
            return
        for lead in leads:
            try:
                self.enrich(lead)
            except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
                log.warning("Enrichment failed for %s: %s", lead.name, exc)

    def enrich(self, lead: Lead) -> None:
        prop: Optional[Property] = None
        if lead.address:
            prop = self._by_address(lead.address)
        if prop is None and lead.name:
            prop = self._by_owner(lead.name)
        if prop:
            lead.matched_property = prop
            # Backfill address on obituary leads from the matched parcel.
            if not lead.address and prop.site_address:
                lead.address = prop.site_address
            if not lead.zip_code and prop.zip_code:
                lead.zip_code = prop.zip_code

    # --- lookups ----------------------------------------------------------
    def _by_address(self, address: str) -> Optional[Property]:
        # Match on the street-number + name prefix to tolerate unit/formatting
        # differences between the foreclosure list and the parcel table.
        needle = _sql_escape(address.split(",")[0].strip().upper())
        where = f"UPPER({self.addr_field}) LIKE '{needle}%'"
        return self._query_one(where)

    def _by_owner(self, name: str) -> Optional[Property]:
        # Assessor owners are stored "LAST FIRST"; search on the last name then
        # confirm the full normalized name client-side to avoid false hits.
        last = name.strip().split()[-1] if name.strip() else ""
        if not last:
            return None
        needle = _sql_escape(last.upper())
        where = f"UPPER({self.owner_field}) LIKE '%{needle}%'"
        target = normalize_name(name)
        for prop in self._query_many(where, limit=25):
            if _owner_matches(prop.owner_name, target):
                if self.config.in_area(prop.site_address, prop.zip_code):
                    return prop
        return None

    def _query_one(self, where: str) -> Optional[Property]:
        results = self._query_many(where, limit=1)
        return results[0] if results else None

    def _query_many(self, where: str, limit: int = 25) -> list[Property]:
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "resultRecordCount": limit,
            "f": "json",
        }
        payload = self.client.get_json(self.query_url, params=params)
        if not payload:
            return []
        features = payload.get("features", [])
        return [self._to_property(f.get("attributes", {})) for f in features]

    def _to_property(self, attrs: dict) -> Property:
        value = attrs.get("ACTUAL_VALUE") or attrs.get("TOTAL_VALUE") or attrs.get("ACTUAL")
        account = attrs.get(self.account_field)
        parcel_url = None
        if account:
            parcel_url = (
                f"{self.cfg.get('assessor_search_url', '').rstrip('/')}"
                f"?account={account}"
            )
        return Property(
            account=str(account) if account is not None else None,
            site_address=attrs.get(self.addr_field),
            city=attrs.get(self.city_field),
            zip_code=str(attrs.get(self.zip_field)) if attrs.get(self.zip_field) else None,
            owner_name=attrs.get(self.owner_field),
            actual_value=parse_money(str(value)) if value is not None else None,
            parcel_url=parcel_url,
        )


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _owner_matches(owner: str | None, target_normalized: str) -> bool:
    if not owner or not target_normalized:
        return False
    return normalize_name(owner) == target_normalized
