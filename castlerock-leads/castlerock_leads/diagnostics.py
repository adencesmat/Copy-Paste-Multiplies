"""First-run diagnostics: confirm live sources + assessor data from *your*
network/machine.

The county sites block datacenter IPs, so these checks must be run from the
machine that will host the pipeline. ``check-endpoints`` confirms each web
source responds and reports how many Assessor records were loaded from the
local data files.
"""

from __future__ import annotations

from .config import Config
from .enrich.assessor import AssessorData
from .http import HttpClient
from .pipeline import build_client
from .sources.obituaries import DIGNITY_PAGE, LEGACY_FEED


def check_endpoints(config: Config) -> int:
    client = build_client(config)
    problems = 0

    print("== Assessor data files (local) ==")
    problems += _check_assessor_files(config)

    print("\n== Public Trustee foreclosure app ==")
    fc = config["foreclosures"]
    url = fc["base_url"].rstrip("/") + fc["search_path"]
    problems += _probe(client, "GET", url, "foreclosure search page")

    print("\n== Probate estate notices ==")
    pr = config.get("probate", {})
    problems += _probe(
        client, "GET",
        pr.get("search_url", "https://www.publicnoticecolorado.com/Search.aspx"),
        "publicnoticecolorado.com search",
    )

    print("\n== Obituary feeds ==")
    problems += _probe(
        client, "GET", config["obituaries"].get("legacy_feed_url", LEGACY_FEED),
        "Legacy.com JSON feed",
    )
    problems += _probe(
        client, "GET", config["obituaries"].get("dignity_url", DIGNITY_PAGE),
        "Dignity Memorial page",
    )

    print(f"\n{'OK — all endpoints reachable' if not problems else f'{problems} issue(s) — see above'}")
    return problems


def _check_assessor_files(config: Config) -> int:
    enr = config.get("enrichment", {})
    if not enr.get("enabled", True):
        print("  enrichment disabled in config — skipping")
        return 0
    directory = enr.get("assessor_data_dir", "assessor_data")
    data = AssessorData.load_dir(directory)
    if data.count == 0:
        print(f"  ! no assessor records loaded from '{directory}/'.")
        print("    Download these from https://www.douglas.co.us/assessor/data-downloads/")
        print("    and place them in that folder: Property Ownership, Property")
        print("    Location, Actual and Assessed Property Values.")
        return 1
    with_owner = sum(1 for r in data.by_account.values() if r.owner_name)
    with_value = sum(1 for r in data.by_account.values() if r.actual_value)
    with_situs = sum(1 for r in data.by_account.values() if r.situs_address)
    print(f"  OK  {data.count:,} parcels loaded from '{directory}/'")
    print(f"      with owner name: {with_owner:,} | with value: {with_value:,} "
          f"| with situs address: {with_situs:,}")
    if not with_owner:
        print("  !   no owner names loaded — add the Property Ownership file "
              "(needed for probate/obituary name matching)")
        return 1
    return 0


def _probe(client: HttpClient, method: str, url: str, label: str) -> int:
    try:
        resp = client._request(method, url)  # noqa: SLF001 - diagnostic use
        print(f"  OK  {label}: HTTP {resp.status_code} ({len(resp.content)} bytes)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  !   {label}: {exc}")
        return 1
