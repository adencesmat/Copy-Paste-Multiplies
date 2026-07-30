"""Data models shared across the pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class Property:
    """A parcel matched from county GIS/assessor data."""

    account: Optional[str] = None
    site_address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    owner_name: Optional[str] = None
    actual_value: Optional[float] = None
    parcel_url: Optional[str] = None


@dataclass
class Lead:
    """A single actionable lead surfaced by the pipeline.

    ``kind`` is ``"foreclosure"``, ``"probate"`` or ``"obituary"``. Fields that
    do not apply to a given kind are simply left as ``None``.
    """

    kind: str
    source: str
    # Person
    name: Optional[str] = None
    age: Optional[int] = None
    # Location / property
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    # Foreclosure specifics
    pt_number: Optional[str] = None
    sale_date: Optional[date] = None
    original_balance: Optional[float] = None
    # Probate specifics
    case_number: Optional[str] = None
    contact_name: Optional[str] = None       # personal representative
    contact_address: Optional[str] = None
    # Obituary specifics
    death_date: Optional[date] = None
    # Provenance
    detail_url: Optional[str] = None
    notes: Optional[str] = None
    first_seen: Optional[str] = None
    # Enrichment
    matched_property: Optional[Property] = None
    # Scoring (filled by scoring.score_lead)
    score: Optional[int] = None
    estimated_equity: Optional[float] = None
    score_reasons: Optional[str] = None

    def fingerprint(self) -> str:
        """Stable id used for de-duplication across daily runs.

        Built from the immutable identity of the lead, not from volatile fields
        like ``first_seen`` or enrichment results, so the same underlying record
        maps to the same fingerprint every day.
        """
        basis = "|".join(
            str(x or "").strip().upper()
            for x in (
                self.kind,
                self.pt_number,
                self.case_number,
                self.name,
                self.address,
                self.death_date,
            )
        )
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def to_row(self) -> dict:
        row = asdict(self)
        prop = row.pop("matched_property")
        if prop:
            for k, v in prop.items():
                row[f"parcel_{k}"] = v
        row["fingerprint"] = self.fingerprint()
        return row
