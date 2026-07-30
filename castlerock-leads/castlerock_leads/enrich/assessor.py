"""Enrich leads with owner, address and value from the Douglas County
Assessor's public data-download files.

The county's GIS map layers carry only parcel geometry + a schedule number, so
they cannot answer "who owns this / what is it worth / where is it". The
Assessor instead publishes the whole active property roll as free bulk files at
https://www.douglas.co.us/assessor/data-downloads/ :

* **Property Ownership** — Account_No, Owner_Name, Mailing_Address_Line_1/2,
  Mailing_City_Name, Mailing_State, Mailing_Zip_Code
* **Property Location**  — Account_No + the situs (street) address
* **Actual and Assessed Property Values** — Account_No, Actual_Value, ...

All three share ``Account_No``. This module reads whatever of those files are
present in a local folder, merges them by account, and builds two indexes:

* by **owner name**  → turns a probate/obituary decedent into the parcel they
  owned (their house), with its mailing address and value.
* by **situs address** → confirms a foreclosure's property and attaches value.

The reader is format-tolerant: it sniffs the delimiter, unzips ``.zip`` files,
and maps columns by fuzzy header name, so it works whether the county ships CSV,
pipe- or tab-delimited text.
"""

from __future__ import annotations

import csv
import glob
import io
import logging
import os
import zipfile
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..config import Config
from ..http import HttpClient
from ..models import Lead, Property
from ..util import normalize_address, normalize_name, parse_money

log = logging.getLogger(__name__)

# Canonical field -> candidate header names (compared after normalization:
# lower-cased, non-alphanumerics collapsed to single underscores).
COLUMN_ALIASES: dict[str, list[str]] = {
    "account": [
        "account_no", "account", "account_number", "accountno", "schedule",
        "schedule_no", "schedule_number", "parcel", "parcel_no", "parcel_spn",
    ],
    "owner_name": ["owner_name", "owner", "ownername", "owner_names"],
    "mail1": ["mailing_address_line_1", "mailing_address_1", "mail_address_1"],
    "mail2": ["mailing_address_line_2", "mailing_address_2", "mail_address_2"],
    "mail_city": ["mailing_city_name", "mailing_city", "mail_city"],
    "mail_state": ["mailing_state", "mail_state"],
    "mail_zip": ["mailing_zip_code", "mailing_zip", "mail_zip"],
    "situs_address": [
        "location_address", "situs_address", "property_address", "site_address",
        "street_address", "location", "situs", "physical_address",
    ],
    "situs_city": ["location_city", "situs_city", "property_city", "site_city", "city"],
    "situs_zip": ["location_zip", "situs_zip", "property_zip", "site_zip", "zip", "zip_code"],
    "actual_value": ["actual_value", "actual", "total_actual_value", "market_value"],
    "assessed_value": ["assessed_value", "assessed", "total_assessed_value"],
}


def _norm_header(h: str) -> str:
    out, prev_us = [], False
    for ch in h.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def _build_alias_lookup() -> dict[str, str]:
    lookup = {}
    for canonical, names in COLUMN_ALIASES.items():
        for n in names:
            lookup[_norm_header(n)] = canonical
    return lookup


_ALIAS = _build_alias_lookup()


@dataclass
class AssessorRecord:
    account: str
    owner_name: Optional[str] = None
    situs_address: Optional[str] = None
    situs_city: Optional[str] = None
    situs_zip: Optional[str] = None
    mailing: Optional[str] = None
    mail_city: Optional[str] = None
    mail_zip: Optional[str] = None
    actual_value: Optional[float] = None
    assessed_value: Optional[float] = None


@dataclass
class AssessorData:
    by_account: dict[str, AssessorRecord] = field(default_factory=dict)
    by_owner: dict[str, list[str]] = field(default_factory=dict)
    by_situs: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.by_account)

    # --- loading ---------------------------------------------------------
    @classmethod
    def load_dir(cls, directory: str) -> "AssessorData":
        data = cls()
        if not directory or not os.path.isdir(directory):
            log.warning("Assessor data dir not found: %s", directory)
            return data
        paths = []
        for ext in ("*.csv", "*.txt", "*.tsv", "*.dat", "*.zip"):
            paths.extend(glob.glob(os.path.join(directory, ext)))
        for path in sorted(paths):
            try:
                data._ingest_file(path)
            except Exception as exc:  # noqa: BLE001 - skip an unreadable file
                log.error("Failed reading %s: %s", path, exc)
        data._build_indexes()
        log.info("Loaded %d assessor records from %s", data.count, directory)
        return data

    def _ingest_file(self, path: str) -> None:
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.lower().endswith((".csv", ".txt", ".tsv", ".dat")):
                        with zf.open(name) as fh:
                            self._ingest_rows(
                                io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                                name,
                            )
            return
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            self._ingest_rows(fh, os.path.basename(path))

    def _ingest_rows(self, fh, label: str) -> None:
        sample = fh.read(8192)
        fh.seek(0)
        delimiter = _sniff_delimiter(sample)
        reader = csv.DictReader(fh, delimiter=delimiter)
        if not reader.fieldnames:
            return
        colmap = {c: _ALIAS.get(_norm_header(c)) for c in reader.fieldnames}
        if "account" not in colmap.values():
            log.warning("No account column in %s (headers: %s)", label, reader.fieldnames)
            return
        added = 0
        for row in reader:
            self._merge_row(row, colmap)
            added += 1
        log.info("  %s: %d rows (delimiter %r)", label, added, delimiter)

    def _merge_row(self, row: dict, colmap: dict) -> None:
        vals: dict[str, str] = {}
        for col, canonical in colmap.items():
            if canonical:
                v = (row.get(col) or "").strip()
                if v:
                    vals[canonical] = v
        account = vals.get("account")
        if not account:
            return
        account = account.strip().upper()
        rec = self.by_account.get(account) or AssessorRecord(account=account)
        if "owner_name" in vals:
            rec.owner_name = vals["owner_name"]
        if "situs_address" in vals:
            rec.situs_address = vals["situs_address"]
        if "situs_city" in vals:
            rec.situs_city = vals["situs_city"]
        if "situs_zip" in vals:
            rec.situs_zip = vals["situs_zip"]
        if "mail1" in vals or "mail2" in vals:
            rec.mailing = " ".join(
                p for p in (vals.get("mail1"), vals.get("mail2")) if p
            ) or rec.mailing
        if "mail_city" in vals:
            rec.mail_city = vals["mail_city"]
        if "mail_zip" in vals:
            rec.mail_zip = vals["mail_zip"]
        if "actual_value" in vals:
            rec.actual_value = parse_money(vals["actual_value"])
        if "assessed_value" in vals:
            rec.assessed_value = parse_money(vals["assessed_value"])
        self.by_account[account] = rec

    def _build_indexes(self) -> None:
        for account, rec in self.by_account.items():
            if rec.owner_name:
                key = normalize_name(rec.owner_name)
                if key:
                    self.by_owner.setdefault(key, []).append(account)
            if rec.situs_address:
                key = normalize_address(rec.situs_address)
                if key:
                    self.by_situs.setdefault(key, account)

    # --- lookups ---------------------------------------------------------
    def by_address(self, address: str) -> Optional[AssessorRecord]:
        acct = self.by_situs.get(normalize_address(address))
        return self.by_account.get(acct) if acct else None

    def by_owner_name(self, name: str, in_area) -> tuple[Optional[AssessorRecord], int]:
        """Return (record, n_area_matches) for an owner name.

        Only parcels whose situs is in the configured area are considered, so a
        common surname doesn't attach a random property. If several qualify the
        first is returned and the count signals ambiguity to the caller.
        """
        accounts = self.by_owner.get(normalize_name(name), [])
        candidates = []
        for acct in accounts:
            rec = self.by_account.get(acct)
            if rec and in_area(rec.situs_address, rec.situs_zip):
                candidates.append(rec)
        if not candidates:
            return None, 0
        return candidates[0], len(candidates)


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",|\t;").delimiter
    except csv.Error:
        # Fall back to the most common delimiter present.
        for d in ("|", "\t", ",", ";"):
            if d in sample:
                return d
        return ","


class AssessorEnricher:
    def __init__(self, config: Config, client: Optional[HttpClient] = None):
        self.config = config
        self.client = client
        self.cfg = config.get("enrichment", {})
        self.data = AssessorData()
        if self.cfg.get("enabled", True):
            self._maybe_download()
            self.data = AssessorData.load_dir(self.cfg.get("assessor_data_dir", "assessor_data"))

    def _maybe_download(self) -> None:
        """Download configured file URLs into the data dir if missing."""
        downloads = self.cfg.get("downloads") or {}
        directory = self.cfg.get("assessor_data_dir", "assessor_data")
        if not downloads or not self.client:
            return
        os.makedirs(directory, exist_ok=True)
        for name, url in downloads.items():
            if not url:
                continue
            dest = os.path.join(directory, f"{name}{_ext_from_url(url)}")
            if os.path.exists(dest):
                continue
            try:
                resp = self.client.get(url)
                with open(dest, "wb") as fh:
                    fh.write(resp.content)
                log.info("Downloaded assessor file %s", dest)
            except Exception as exc:  # noqa: BLE001
                log.error("Could not download %s: %s", url, exc)

    def enrich_all(self, leads: Iterable[Lead]) -> None:
        if not self.cfg.get("enabled", True) or self.data.count == 0:
            if self.cfg.get("enabled", True):
                log.warning("No assessor data loaded; leads will not be enriched")
            return
        for lead in leads:
            try:
                self.enrich(lead)
            except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
                log.warning("Enrichment failed for %s: %s", lead.name, exc)

    def enrich(self, lead: Lead) -> None:
        rec: Optional[AssessorRecord] = None
        if lead.address:
            rec = self.data.by_address(lead.address)
        if rec is None and lead.name:
            rec, n = self.data.by_owner_name(lead.name, self.config.in_area)
            if rec and n > 1:
                lead.notes = ((lead.notes or "") + f" [{n} parcels match this owner name]").strip()
        if rec is None:
            return
        lead.matched_property = Property(
            account=rec.account,
            site_address=rec.situs_address,
            city=rec.situs_city,
            zip_code=rec.situs_zip,
            owner_name=rec.owner_name,
            actual_value=rec.actual_value,
            parcel_url=_assessor_url(self.cfg, rec.account),
        )
        if not lead.address and rec.situs_address:
            lead.address = rec.situs_address
        if not lead.zip_code and rec.situs_zip:
            lead.zip_code = rec.situs_zip


def _assessor_url(cfg: dict, account: str) -> Optional[str]:
    base = cfg.get("assessor_search_url")
    return f"{base.rstrip('/')}?account={account}" if base and account else None


def _ext_from_url(url: str) -> str:
    for ext in (".zip", ".csv", ".txt", ".tsv", ".dat"):
        if url.lower().endswith(ext):
            return ext
    return ".csv"


def _owner_matches(owner: str | None, target_normalized: str) -> bool:
    """Kept for the name-matching test and any external callers."""
    if not owner or not target_normalized:
        return False
    return normalize_name(owner) == target_normalized
