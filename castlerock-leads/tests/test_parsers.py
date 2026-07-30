"""Offline tests for the parsing/matching logic.

These run without network access, using inline fixtures that mirror the real
providers' shapes. They lock in the extraction behaviour so that when the
selectors are confirmed against the live sites, regressions are caught.
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from castlerock_leads.config import Config  # noqa: E402
from castlerock_leads.models import Lead, Property  # noqa: E402
from castlerock_leads.sources.foreclosures import parse_results_html  # noqa: E402
from castlerock_leads.sources.obituaries import (  # noqa: E402
    parse_dignity_html,
    parse_legacy_json,
)
from castlerock_leads.util import (  # noqa: E402
    normalize_name,
    parse_age,
    parse_money,
)
from castlerock_leads.enrich.assessor import _owner_matches  # noqa: E402


FORECLOSURE_HTML = """
<html><body>
<table>
  <tr><th>PT No</th><th>Grantor</th><th>Property Address</th>
      <th>Sale Date</th><th>Original Balance</th></tr>
  <tr>
    <td><a href="propertyDetails.do?id=2026-0123">2026-0123</a></td>
    <td>SMITH, JOHN</td>
    <td>123 Wolfensberger Rd, Castle Rock, CO 80109</td>
    <td>09/15/2026</td>
    <td>$412,500.00</td>
  </tr>
  <tr>
    <td><a href="propertyDetails.do?id=2026-0124">2026-0124</a></td>
    <td>DOE, JANE</td>
    <td>9 Main St, Denver, CO 80202</td>
    <td>09/20/2026</td>
    <td>$250,000.00</td>
  </tr>
</table>
</body></html>
"""

LEGACY_JSON = {
    "obituaries": [
        {
            "fullName": "Edmund Brandt",
            "age": 90,
            "deathDate": "2026-05-25",
            "url": "/us/obituaries/name/edmund-brandt-obituary",
        },
        {
            "firstName": "Mary",
            "lastName": "Doria",
            "age": "85",
            "dateOfDeath": "February 21, 2026",
            "obituaryUrl": "https://www.legacy.com/x",
        },
    ]
}

DIGNITY_HTML = """
<html><body>
<article class="obituary-card">
  <h3 class="name">Bernard Joseph Musso Jr.</h3>
  <time datetime="2026-05-24">May 24, 2026</time>
  <p>Bernard, age 76, of Castle Rock, passed away.</p>
  <a href="/obituaries/castle-rock-co/bernard-musso-123">details</a>
</article>
</body></html>
"""


def _config():
    return Config(
        raw={
            "geography": {"city": "CASTLE ROCK", "zip_codes": ["80104", "80108", "80109"]}
        }
    )


def test_foreclosure_parsing_and_area_filter():
    leads = parse_results_html(
        FORECLOSURE_HTML, "https://apps.douglas.co.us/apps/publictrustee",
        "/propertyDetails.do",
    )
    assert len(leads) == 2
    john = leads[0]
    assert john.pt_number == "2026-0123"
    assert john.name == "SMITH, JOHN"
    assert john.sale_date == date(2026, 9, 15)
    assert john.original_balance == 412500.0
    assert john.detail_url.endswith("propertyDetails.do?id=2026-0123")

    cfg = _config()
    in_area = [x for x in leads if cfg.in_area(x.address, x.zip_code)]
    assert len(in_area) == 1  # Denver row filtered out
    assert in_area[0].pt_number == "2026-0123"


def test_legacy_json_parsing():
    leads = parse_legacy_json(LEGACY_JSON)
    assert len(leads) == 2
    assert leads[0].name == "Edmund Brandt"
    assert leads[0].age == 90
    assert leads[0].death_date == date(2026, 5, 25)
    assert leads[0].detail_url.startswith("https://www.legacy.com/")
    assert leads[1].name == "Mary Doria"
    assert leads[1].age == 85


def test_dignity_html_parsing():
    leads = parse_dignity_html(DIGNITY_HTML)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.name.startswith("Bernard")
    assert lead.age == 76
    assert lead.death_date == date(2026, 5, 24)
    assert lead.detail_url.startswith("https://www.dignitymemorial.com/")


def test_age_parsing_variants():
    assert parse_age("age 87") == 87
    assert parse_age("John Smith, 92, of Castle Rock") == 92
    assert parse_age("passed away at 78 years of age") == 78
    assert parse_age("no age here") is None


def test_money_parsing():
    assert parse_money("$412,500.00") == 412500.0
    assert parse_money("250000") == 250000.0
    assert parse_money(None) is None


def test_name_normalization_and_owner_match():
    # Assessor "LAST FIRST" vs obituary "First Last" must compare equal.
    assert normalize_name("SMITH JOHN") == normalize_name("John Smith")
    assert _owner_matches("BRANDT, EDMUND", normalize_name("Edmund Brandt"))
    assert not _owner_matches("BRANDT, EDMUND", normalize_name("Jane Doe"))


def test_fingerprint_stable_and_dedupes():
    a = Lead(kind="foreclosure", source="s", pt_number="2026-0123", name="SMITH")
    b = Lead(kind="foreclosure", source="s", pt_number="2026-0123", name="SMITH",
             matched_property=Property(account="X"))
    # Enrichment must not change identity.
    assert a.fingerprint() == b.fingerprint()
    c = Lead(kind="foreclosure", source="s", pt_number="2026-9999", name="SMITH")
    assert a.fingerprint() != c.fingerprint()
