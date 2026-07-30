"""Command-line entry point.

    python -m castlerock_leads run              # one daily run
    python -m castlerock_leads check-endpoints  # verify live sources
    python -m castlerock_leads --config path.yaml run
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .diagnostics import check_endpoints
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="castlerock_leads")
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--db", default="leads.db", help="history database path")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "command",
        choices=["run", "check-endpoints"],
        help="run the pipeline, or verify live endpoints from this machine",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)

    if args.command == "check-endpoints":
        return 1 if check_endpoints(config) else 0

    summary = run(config, db_path=args.db)
    print(
        f"Done: {summary['new']} new lead(s) "
        f"({summary['foreclosures']} foreclosure, {summary['probate']} probate, "
        f"{summary['obituaries']} obituary; {summary['enriched']} matched to a parcel; "
        f"top score {summary['top_score']})."
    )
    for f in summary["files"]:
        print(f"  wrote {f}")
    if summary["emailed"]:
        print("  emailed digest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
