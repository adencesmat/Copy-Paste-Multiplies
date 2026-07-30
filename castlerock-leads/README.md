# Castle Rock lead pipeline

A daily automated pipeline that surfaces two kinds of real-estate leads in
**Castle Rock, Colorado (Douglas County)** and cross-references each against the
county's GIS/parcel data:

1. **Foreclosures** — from the Douglas County **Public Trustee** foreclosure
   search (the authoritative source for Notices of Election & Demand and
   foreclosure sales).
2. **Obituaries** — recent Castle Rock obituaries (Legacy.com + Dignity
   Memorial), filtered to older decedents, as a signal for estate/probate
   sales.

Every lead is then run against the **Douglas County parcels/assessor GIS
service** to attach a real property: account number, site address, assessor
"actual value", and owner of record. That match is what turns a name in an
obituary into an actionable property — and it's the "connected to the local GIS
maps" piece you asked for.

Output each day: a dated **CSV** and a **HTML report**, plus an optional
**email digest**. A local SQLite history means each run only shows you what's
*new*.

```
foreclosure source ─┐
                    ├─► dedupe (SQLite) ─► GIS/assessor enrichment ─► CSV + HTML (+ email)
obituary sources  ──┘
```

---

## ⚠️ Read this first: where it can run

The county sites and Legacy.com **block datacenter / cloud IP ranges** (they
returned `403` to the build sandbox, and will do the same to GitHub-hosted
Actions runners). This is normal WAF behavior, not a bug in the code.

**Run it from a normal network** — your office server, a workstation, or a
self-hosted runner on a residential/commercial connection. Confirm reachability
before your first real run:

```bash
python -m castlerock_leads --config config.yaml check-endpoints
```

`check-endpoints` prints the live GIS **layer ids and field names** so you can
fill in the two config values that can only be read from the live service
(`enrichment.parcels_layer_id` and `enrichment.fields`), and confirms every
source responds.

---

## Setup

```bash
cd castlerock-leads
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # then edit config.yaml
```

Run once:

```bash
python -m castlerock_leads --config config.yaml run
```

Outputs land in `output/leads-YYYY-MM-DD.{csv,html}`.

## Configuration

Everything lives in `config.yaml` (copied from `config.example.yaml`, which is
fully commented). The knobs you'll most likely touch:

| Setting | Purpose |
|---|---|
| `geography.zip_codes` | Which ZIPs count as Castle Rock (default 80104/08/09). |
| `obituaries.min_age` | Minimum decedent age to surface (default 65). |
| `foreclosures.max_days_to_sale` | Ignore sales further out than N days. |
| `enrichment.parcels_layer_id` / `enrichment.fields` | GIS layer + field names — set these from `check-endpoints` output. |
| `email.*` | Turn on the daily email digest. |

**Secrets never go in the config file.** SMTP credentials for the email digest
are read from the environment: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`.

## Scheduling it daily

**Option A — cron on your own machine (recommended):**

```cron
0 7 * * *  /path/to/castlerock-leads/scripts/run_daily.sh >> /path/to/cron.log 2>&1
```

`scripts/run_daily.sh` activates the venv, loads an optional `.env` for SMTP
creds, and runs the pipeline.

**Option B — GitHub Actions:** `.github/workflows/castlerock-daily.yml` runs at
07:00 America/Denver, caches the dedupe DB between runs, and uploads the report
as an artifact. Only use this if a self-hosted runner (or a runner IP the county
doesn't block) is available — see the reachability note above.

## How the GIS match works

- **Foreclosures** already carry a street address → matched to a parcel by
  address prefix (tolerant of unit/formatting differences).
- **Obituaries** carry only a name → the assessor owner index is searched by
  last name, and candidates are confirmed with an order-independent name match
  (`SMITH JOHN` ⇄ `John Smith`) restricted to the Castle Rock area, so a common
  surname doesn't produce false hits.

Field names differ between counties; the defaults target the common Douglas
County parcels schema and are overridable in `enrichment.fields`.

## Testing

The parsing and matching logic is unit-tested offline (no network needed):

```bash
python -m pytest tests/ -q
```

Fixtures mirror the real providers' shapes, so when you confirm selectors
against the live sites you have a regression net.

## Layout

```
castlerock_leads/
  cli.py              # `run` and `check-endpoints` commands
  pipeline.py         # fetch → dedupe → enrich → report
  config.py           # config loading + area matching
  http.py             # polite client: UA, rate-limit, retries
  db.py               # SQLite dedupe history
  models.py           # Lead / Property
  util.py             # age/date/money/name parsing
  diagnostics.py      # check-endpoints
  report.py           # CSV + HTML
  notify.py           # optional email digest
  sources/
    foreclosures.py   # Douglas County Public Trustee
    obituaries.py     # Legacy.com + Dignity Memorial
  enrich/
    assessor.py       # ArcGIS parcel / assessor cross-reference
```

## Legal & ethical use

This pipeline reads **public records** (public-trustee foreclosure filings,
published obituaries, county assessor data). Before using leads for outreach:

- Scrub against the **National / Colorado Do-Not-Call** registries before
  calling, and honor opt-outs.
- Respect each site's Terms of Service and `robots.txt`; the client is
  rate-limited and identifies itself for this reason. Legacy.com in particular
  restricts bulk/automated collection — review their terms and prefer their
  official feeds.
- Obituary-derived outreach touches recently bereaved families. Contact
  respectfully, disclose who you are, and stop on request. Many investors work
  probate leads only after they appear in the public probate court record,
  which is a cleaner and less intrusive signal — consider adding the Douglas
  County probate docket as a source.

You are responsible for compliance with TCPA, state solicitation rules, and any
data-use restrictions that apply to your outreach.

## Extending it

Each source is a small class with a `fetch() -> list[Lead]`. To add one (e.g. a
funeral home site, the probate docket, or tax-lien sales), drop a module in
`sources/`, parse into `Lead` objects, and add it in `pipeline.run`. The
enrichment and reporting stages then apply automatically.
