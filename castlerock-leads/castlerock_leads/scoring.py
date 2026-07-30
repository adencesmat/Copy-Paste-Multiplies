"""Opportunity scoring so the best leads rise to the top of the daily report.

The score is a transparent 0-100 sum of components. The point isn't precision
to the decimal; it's ordering — a lead with a confirmed high-equity property and
a named contact should always outrank a bare name with no matched parcel. Every
component is explainable (``score_reasons``) and the weights live here so you
can tune them to what actually converts for you.
"""

from __future__ import annotations

from typing import Optional

from .models import Lead
from .util import days_until

# Component weights (max contribution to the 0-100 score).
W_PARCEL_MATCH = 40   # a confirmed property is what makes a lead actionable
W_EQUITY = 25         # equity is the deal: sellable value net of debt
W_VALUE = 15          # bigger properties = bigger opportunity
W_CONTACT = 10        # a named person to actually reach
W_TIMELINESS = 10     # foreclosure urgency window


def estimate_equity(lead: Lead) -> Optional[float]:
    """Return estimated equity as a fraction 0..1, or None if unknowable.

    Foreclosures carry the original loan balance, so equity is
    ``(value - balance) / value``. For probate/obituary leads there is no debt
    figure; we do not fabricate one (returns None) and lean on value instead.
    """
    prop = lead.matched_property
    value = prop.actual_value if prop else None
    if not value or value <= 0:
        return None
    if lead.original_balance:
        return max(-1.0, min(1.0, (value - lead.original_balance) / value))
    return None


def score_lead(lead: Lead) -> None:
    """Populate ``lead.score``, ``lead.estimated_equity`` and ``score_reasons``."""
    score = 0
    reasons: list[str] = []
    prop = lead.matched_property

    if prop is not None:
        score += W_PARCEL_MATCH
        reasons.append("matched to parcel")

    equity = estimate_equity(lead)
    lead.estimated_equity = equity
    if equity is not None:
        pts = round(W_EQUITY * max(0.0, equity))
        score += pts
        reasons.append(f"~{equity*100:.0f}% equity (+{pts})")
    elif prop and prop.actual_value:
        # No debt data (probate/obituary). Older decedents with a paid-for home
        # usually mean substantial equity; credit partial equity weight.
        partial = round(W_EQUITY * 0.5)
        score += partial
        reasons.append(f"equity likely, no debt data (+{partial})")

    if prop and prop.actual_value:
        pts = min(W_VALUE, round(prop.actual_value / 50000))
        score += pts
        reasons.append(f"value ${prop.actual_value:,.0f} (+{pts})")

    if lead.contact_name:
        score += W_CONTACT
        reasons.append("named contact")

    if lead.kind == "foreclosure":
        d = days_until(lead.sale_date)
        if d is not None and d >= 0:
            # Peak urgency ~14-45 days out; a sale next week may be too late to
            # work, one 4 months out is not yet pressing.
            if 7 <= d <= 60:
                score += W_TIMELINESS
                reasons.append(f"sale in {d}d (+{W_TIMELINESS})")
            elif d < 7:
                score += W_TIMELINESS // 2
                reasons.append(f"sale imminent {d}d (+{W_TIMELINESS // 2})")

    lead.score = min(100, score)
    lead.score_reasons = "; ".join(reasons)


def score_all(leads) -> list[Lead]:
    """Score every lead and return them sorted best-first."""
    for lead in leads:
        score_lead(lead)
    return sorted(leads, key=lambda x: (x.score or 0), reverse=True)
