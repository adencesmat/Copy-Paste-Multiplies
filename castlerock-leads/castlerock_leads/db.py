"""SQLite-backed history so each daily run only surfaces *new* leads."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

from .models import Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    fingerprint TEXT PRIMARY KEY,
    kind        TEXT,
    name        TEXT,
    address     TEXT,
    first_seen  TEXT,
    payload     TEXT
);
"""


class History:
    def __init__(self, path: str | Path = "leads.db"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "History":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def is_known(self, fingerprint: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM leads WHERE fingerprint = ?", (fingerprint,)
        )
        return cur.fetchone() is not None

    def filter_new(self, leads: Iterable[Lead]) -> list[Lead]:
        """Return only leads not already recorded, tagging first_seen."""
        today = date.today().isoformat()
        fresh: list[Lead] = []
        for lead in leads:
            if self.is_known(lead.fingerprint()):
                continue
            lead.first_seen = today
            fresh.append(lead)
        return fresh

    def record(self, leads: Iterable[Lead]) -> None:
        rows = []
        for lead in leads:
            rows.append(
                (
                    lead.fingerprint(),
                    lead.kind,
                    lead.name,
                    lead.address,
                    lead.first_seen or date.today().isoformat(),
                    json.dumps(lead.to_row(), default=str),
                )
            )
        self.conn.executemany(
            "INSERT OR IGNORE INTO leads "
            "(fingerprint, kind, name, address, first_seen, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
