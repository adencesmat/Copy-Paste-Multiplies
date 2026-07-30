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
from castlerock_leads.enrich.assessor import (  # noqa: E402
    AssessorData,
    AssessorEnricher,
    _owner_matches,
)
from castlerock_leads.util import normalize_address  # noqa: E402
from castlerock_leads.sources.probate import (  # noqa: E402
    is_estate_notice,
    notice_to_lead,
    parse_notice_text,
)
from castlerock_leads.scoring import score_lead, estimate_equity  # noqa: E402


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


# Realistic Colorado statutory Notice to Creditors (C.R.S. 15-12-801).
PROBATE_NOTICE = """
NOTICE TO CREDITORS
Estate of Margaret Ann Whitfield, a/k/a Margaret A. Whitfield, Deceased
Case Number 2026 PR 30145

All persons having claims against the above-named estate are required to
present them to the personal representative or to the District Court of
Douglas County, Colorado on or before November 30, 2026, or the claims may be
forever barred.

First Publication: July 24, 2026

Robert Whitfield
Personal Representative
815 Wilcox Street, Castle Rock, CO 80104
"""


def test_probate_notice_parsing():
    assert is_estate_notice(PROBATE_NOTICE)
    fields = parse_notice_text(PROBATE_NOTICE)
    assert fields["name"] == "Margaret Ann Whitfield"
    assert fields["case_number"] == "2026 PR 30145"
    assert fields["contact_name"] == "Robert Whitfield"
    assert "815 Wilcox Street" in fields["contact_address"]
    assert fields["first_publication"] == date(2026, 7, 24)


def test_probate_notice_to_lead():
    lead = notice_to_lead(PROBATE_NOTICE, "publicnoticecolorado.com", "http://x")
    assert lead is not None
    assert lead.kind == "probate"
    assert lead.name == "Margaret Ann Whitfield"
    assert lead.contact_name == "Robert Whitfield"
    # A non-estate notice yields nothing.
    assert notice_to_lead("NOTICE OF PUBLIC HEARING re: zoning", "s") is None


def test_scoring_ranks_equity_and_match():
    from castlerock_leads.models import Property

    from datetime import timedelta

    # High-equity foreclosure with a matched parcel and a sale ~30 days out.
    strong = Lead(
        kind="foreclosure", source="s", name="SMITH JOHN",
        original_balance=200000.0,
        sale_date=date.today() + timedelta(days=30),
        matched_property=Property(actual_value=600000.0, owner_name="SMITH JOHN"),
    )

    # Obituary with no matched property.
    weak = Lead(kind="obituary", source="s", name="Jane Doe", age=80)

    score_lead(strong)
    score_lead(weak)
    assert strong.score > weak.score
    assert strong.score >= 70            # parcel + equity + value + timing
    assert abs(estimate_equity(strong) - (400000 / 600000)) < 1e-6
    assert weak.score == 0
    assert "matched to parcel" in strong.score_reasons


def test_probate_lead_scores_contact_and_value():
    from castlerock_leads.models import Property

    lead = notice_to_lead(PROBATE_NOTICE, "publicnoticecolorado.com")
    lead.matched_property = Property(actual_value=550000.0, owner_name="WHITFIELD MARGARET")
    score_lead(lead)
    # Parcel match + named PR contact + partial equity + value.
    assert lead.score >= 60
    assert "named contact" in lead.score_reasons


def _write_assessor_files(dir_path):
    # Three files mirroring the Douglas County download schemas, deliberately
    # using different delimiters to exercise the sniffer.
    (dir_path / "ownership.csv").write_text(
        "Account_No,Owner_Name,Mailing_Address_Line_1,Mailing_City_Name,Mailing_State,Mailing_Zip_Code\n"
        "R001,WHITFIELD MARGARET A,815 WILCOX ST,CASTLE ROCK,CO,80104\n"
        "R002,SMITH JOHN R,123 WOLFENSBERGER RD,CASTLE ROCK,CO,80109\n"
        "R003,SMITH JOHN,9 FAKE ST,DENVER,CO,80202\n"
    )
    (dir_path / "location.txt").write_text(
        "Account_No|Location_Address|Location_City|Location_Zip\n"
        "R001|42 CASTLETON WAY|CASTLE ROCK|80104\n"
        "R002|123 WOLFENSBERGER RD|CASTLE ROCK|80109\n"
        "R003|9 FAKE ST|DENVER|80202\n"
    )
    (dir_path / "values.csv").write_text(
        "Account_No,Actual_Value,Assessed_Value\n"
        "R001,640000,45760\n"
        "R002,585000,41827\n"
        "R003,300000,21450\n"
    )


def test_assessor_data_loads_and_merges(tmp_path):
    _write_assessor_files(tmp_path)
    data = AssessorData.load_dir(str(tmp_path))
    assert data.count == 3
    rec = data.by_account["R001"]
    assert rec.owner_name == "WHITFIELD MARGARET A"
    assert rec.situs_address == "42 CASTLETON WAY"      # merged from location file
    assert rec.actual_value == 640000.0                 # merged from values file


def test_assessor_address_and_owner_lookup(tmp_path):
    _write_assessor_files(tmp_path)
    data = AssessorData.load_dir(str(tmp_path))

    # Address match tolerates "Rd." vs "RD" and trailing city/state.
    rec = data.by_address("123 Wolfensberger Rd, Castle Rock, CO 80109")
    assert rec and rec.account == "R002"

    cfg = _config()
    # Owner-name match, restricted to the Castle Rock area (R003 is in Denver).
    rec, n = data.by_owner_name("John R Smith", cfg.in_area)
    assert rec and rec.account == "R002"
    assert n == 1


def test_enricher_attaches_property_to_probate_lead(tmp_path):
    _write_assessor_files(tmp_path)
    cfg = Config(raw={
        "geography": {"city": "CASTLE ROCK", "zip_codes": ["80104", "80108", "80109"]},
        "enrichment": {"enabled": True, "assessor_data_dir": str(tmp_path)},
    })
    enricher = AssessorEnricher(cfg)
    lead = Lead(kind="probate", source="s", name="Margaret A Whitfield")
    enricher.enrich(lead)
    assert lead.matched_property is not None
    assert lead.matched_property.actual_value == 640000.0
    assert lead.address == "42 CASTLETON WAY"           # backfilled from parcel


def test_normalize_address():
    assert normalize_address("123 Wolfensberger Rd.") == normalize_address("123 WOLFENSBERGER ROAD")
    assert normalize_address("42 Castleton Way, Castle Rock, CO") == "42 CASTLETON WAY"


def test_fingerprint_stable_and_dedupes():
    a = Lead(kind="foreclosure", source="s", pt_number="2026-0123", name="SMITH")
    b = Lead(kind="foreclosure", source="s", pt_number="2026-0123", name="SMITH",
             matched_property=Property(account="X"))
    # Enrichment must not change identity.
    assert a.fingerprint() == b.fingerprint()
    c = Lead(kind="foreclosure", source="s", pt_number="2026-9999", name="SMITH")
    assert a.fingerprint() != c.fingerprint()
