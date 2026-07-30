# Castle Rock lead pipeline

A daily automated pipeline that surfaces motivated-seller leads in **Castle
Rock, Colorado (Douglas County)**, cross-references each against the county's
GIS/parcel data, and **ranks them by opportunity** so the best deals surface
first.

Three sources, in order of signal strength:

1. **Foreclosures** — the Douglas County **Public Trustee** foreclosure search
   (authoritative for Notices of Election & Demand and foreclosure sales).
2. **Probate estate notices** *(primary estate-sale source)* — Colorado law
   (C.R.S. 15-12-801) requires every probated estate to publish a **Notice to
   Creditors**, aggregated at publicnoticecolorado.com. These mark an estate
   *actively being settled* and **name the personal representative** — the
   actual decision-maker to contact. Far stronger than a raw obituary.
3. **Obituaries** *(secondary signal)* — Legacy.com + Dignity Memorial,
   filtered to older decedents. Broader but noisier, with no contact.

Every lead is run against the **Douglas County Assessor's public data files**
to attach a real property — owner of record, situs + mailing address, and
assessor "actual value". (The county's GIS map layers hold only parcel geometry
and a schedule number; owner and value live in the Assessor's downloadable data
roll, so that's what the pipeline uses — see "Assessor data" below.) Foreclosures
match by address; probate/obituary leads match by **owner name**, which is what
turns a decedent into the specific house they owned. Then each lead gets an
**opportunity score (0-100)** built from estimated equity, whether it matched a
real parcel, property value, whether there's a named contact, and foreclosure
timing.

Output each day: a dated, **ranked CSV + HTML report**, plus an optional
**email digest**. A local SQLite history means each run only shows what's *new*.

```
foreclosure ─┐
probate      ├─► dedupe (SQLite) ─► GIS/assessor enrich ─► score & rank ─► CSV + HTML (+ email)
obituary   ──┘
```

### Why this design converts

Anyone can pull a raw foreclosure or obituary list. What actually drives deals
is (a) a **higher-signal estate source** — a probate notice means the estate is
being administered *and* hands you the personal representative to call, which a
death notice never does; and (b) **ranking**, so you work the three
high-equity, parcel-matched leads today instead of reading a 40-row dump. Both
are built in.

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

`check-endpoints` confirms every web source responds from your machine and
reports how many Assessor records loaded from your local data files.

---

## Setup

```bash
cd castlerock-leads
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # then edit config.yaml
```

### Assessor data (one-time, then refresh periodically)

Owner names and property values come from the county's free bulk data files, not
a live API. Download these three from
<https://www.douglas.co.us/assessor/data-downloads/> (they cover active accounts
only) and drop them in an `assessor_data/` folder inside `castlerock-leads`:

* **Property Ownership** — owner names + mailing addresses
* **Property Location** — situs (street) addresses
* **Actual and Assessed Property Values** — the value used for equity ranking

The reader auto-detects each file's format and matches columns by name, so no
editing is needed — just place the files. Re-download every so often (monthly is
plenty) to keep owners and values current. Verify they loaded:

```bash
python -m castlerock_leads --config config.yaml check-endpoints
# => "OK  N parcels loaded ... with owner name / value / situs address"
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
| `enrichment.assessor_data_dir` | Folder holding the downloaded county Assessor files. |
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

## How the property match works

The Assessor files are merged by account number into one record per parcel
(owner, situs address, mailing address, value), then indexed two ways:

- **Foreclosures** already carry a street address → matched by **situs address**,
  normalized so `123 Wolfensberger Rd.` and `123 WOLFENSBERGER ROAD` compare
  equal.
- **Probate / obituaries** carry only a name → matched by **owner name** with an
  order-independent comparison (`SMITH JOHN` ⇄ `John Smith`), restricted to
  parcels whose situs is in the Castle Rock area so a common surname doesn't
  attach a random property. If more than one qualifies, the lead is flagged with
  the count for a quick manual check.

Column names are matched by fuzzy header (e.g. `Owner_Name`, `Account_No`,
`Actual_Value`), so the loader adapts if the county tweaks its file layout.

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
  scoring.py          # opportunity score (equity, match, contact, timing)
  util.py             # age/date/money/name parsing
  diagnostics.py      # check-endpoints
  report.py           # ranked CSV + HTML
  notify.py           # optional email digest
  sources/
    foreclosures.py   # Douglas County Public Trustee
    probate.py        # probate Notice-to-Creditors (publicnoticecolorado.com)
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
  respectfully, disclose who you are, and stop on request. The **probate notice
  source is the cleaner, higher-signal path** and is the pipeline's primary
  estate source: a published Notice to Creditors is a legally public record of
  an estate being administered, and it names the personal representative — the
  appropriate person to contact — rather than reaching out cold off a death
  notice. Prefer working those leads.

You are responsible for compliance with TCPA, state solicitation rules, and any
data-use restrictions that apply to your outreach.

## Extending it

Each source is a small class with a `fetch() -> list[Lead]`. To add one (e.g. a
funeral home site, the probate docket, or tax-lien sales), drop a module in
`sources/`, parse into `Lead` objects, and add it in `pipeline.run`. The
enrichment and reporting stages then apply automatically.
