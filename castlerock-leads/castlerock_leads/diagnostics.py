"""First-run diagnostics: confirm live endpoints from *your* network.

The county sites block datacenter IPs, so these checks must be run from the
machine that will host the pipeline. ``check-endpoints`` prints the real
MapServer layer ids + field names (so you can fill in ``enrichment.fields`` and
``parcels_layer_id``) and confirms each source responds.
"""

from __future__ import annotations

from .config import Config
from .http import HttpClient
from .pipeline import build_client
from .sources.obituaries import DIGNITY_PAGE, LEGACY_FEED


def check_endpoints(config: Config) -> int:
    client = build_client(config)
    problems = 0

    print("== Douglas County parcels MapServer ==")
    problems += _check_mapserver(config, client)

    print("\n== Public Trustee foreclosure app ==")
    fc = config["foreclosures"]
    url = fc["base_url"].rstrip("/") + fc["search_path"]
    problems += _probe(client, "GET", url, "foreclosure search page")

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


def _check_mapserver(config: Config, client: HttpClient) -> int:
    base = config["enrichment"]["parcels_mapserver"].rstrip("/")
    payload = None
    try:
        payload = client.get_json(base + "?f=json")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not reach MapServer: {exc}")
        return 1
    if not payload:
        print("  ! MapServer returned no JSON")
        return 1
    layers = payload.get("layers", [])
    print("  Layers (use the id for parcels_layer_id):")
    for layer in layers:
        print(f"    [{layer.get('id')}] {layer.get('name')}")

    # Print field names for the configured parcels layer so the user can fill in
    # enrichment.fields correctly.
    layer_id = config["enrichment"].get("parcels_layer_id", 0)
    try:
        detail = client.get_json(f"{base}/{layer_id}?f=json")
        fields = [f.get("name") for f in (detail or {}).get("fields", [])]
        print(f"  Fields on layer {layer_id}: {', '.join(fields) or '(none)'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not read layer {layer_id} fields: {exc}")
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
