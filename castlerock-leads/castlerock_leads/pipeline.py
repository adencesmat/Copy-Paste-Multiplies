"""Orchestrates a single daily run: fetch -> enrich -> dedupe -> report."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .config import Config
from .db import History
from .enrich.assessor import AssessorEnricher
from .http import HttpClient
from .notify import maybe_email
from .report import write_csv, write_html
from .sources.foreclosures import ForeclosureSource
from .sources.obituaries import ObituarySource

log = logging.getLogger(__name__)


def build_client(config: Config) -> HttpClient:
    h = config.get("http", {})
    return HttpClient(
        user_agent=h.get("user_agent", "CastleRockLeadsBot/1.0"),
        min_delay_seconds=h.get("min_delay_seconds", 2.0),
        timeout_seconds=h.get("timeout_seconds", 30),
        max_retries=h.get("max_retries", 3),
    )


def run(config: Config, db_path: str = "leads.db") -> dict:
    """Execute one run and return a summary dict."""
    client = build_client(config)

    leads = []
    leads += ForeclosureSource(config, client).fetch()
    leads += ObituarySource(config, client).fetch()
    log.info("Fetched %d candidate lead(s) before dedupe", len(leads))

    with History(db_path) as history:
        fresh = history.filter_new(leads)
        log.info("%d new lead(s) after dedupe", len(fresh))

        if config.get("enrichment", {}).get("enabled", True):
            AssessorEnricher(config, client).enrich_all(fresh)

        history.record(fresh)

    out = config.get("output", {})
    out_dir = Path(out.get("dir", "output"))
    stamp = date.today().isoformat()
    written = []
    if out.get("keep_csv", True):
        written.append(str(write_csv(fresh, out_dir / f"leads-{stamp}.csv")))
    if out.get("keep_html", True):
        written.append(str(write_html(fresh, out_dir / f"leads-{stamp}.html")))

    emailed = maybe_email(config, fresh)

    return {
        "candidates": len(leads),
        "new": len(fresh),
        "foreclosures": sum(1 for x in fresh if x.kind == "foreclosure"),
        "obituaries": sum(1 for x in fresh if x.kind == "obituary"),
        "enriched": sum(1 for x in fresh if x.matched_property is not None),
        "files": written,
        "emailed": emailed,
    }
