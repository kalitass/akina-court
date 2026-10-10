"""Policy execution engine + verifier against the six demo cases and their human reference rulings."""
import json
from pathlib import Path

import pytest

from core.counterfactual import apply
from core.facts.tools import build_fact_table
from core.policy import citable_ids
from core.policy_engine import check_ruling, evaluate, expected_amount
from core.schemas import Case, Ruling, SegmentFinding
from core.verify import verify_ruling


def _sf(**kw):
    """A SegmentFinding whose ground follows its finding (the tests here are about timing, basis and amounts, not the ground)."""
    kw.setdefault("ground", {"exempt": "general_route_consent", "counts": "consent_after_or_none", "undetermined": "named_road_untied"}[kw["finding"]])
    return SegmentFinding(**kw)


ROOT = Path(__file__).resolve().parents[1]
EXEMPT = {"C-0001": {"F4": True, "F5": False}, "C-0002": {"F3": False}, "C-0003": {"F3": True}}


def load(cid):
    case = Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))
    exp = json.loads((ROOT / "data" / "expected" / f"{cid}.json").read_text())
    return case, exp


def basis_for(cert, fid):
    """Rider messages on record before the segment started: what an exempt finding must rest on."""
    start = cert.segments[fid].get("start")
    return [b for b, m in cert.chat_index.items() if m["from"] == "rider" and not m["statement"] and m["ts"] and start and m["ts"] < start]


def ruling_from_expected(cid, exp, cert):
    findings = [_sf(fact_id=f, finding="exempt" if e else "counts", basis=basis_for(cert, f) if e else [], reason="ref")
                for f, e in EXEMPT.get(cid, {}).items()]
    upheld = any(f.finding == "counts" for f in findings) or any(sg["exempt"] is False for sg in cert.segments.values())
    flag = bool(cert.flag_required) if cert.flag_required is not None else bool(cert.flag_conditional and upheld)
    return Ruling(ruling=exp["ruling"], amount=exp.get("amount"), recommended_action="x" + (" + flag_account" if flag else ""), flag_account=flag,
                  safety_concern="none", evidence_status="sufficient",
                  confidence=0.9, reasoning="[F1][RD-1]", cited_facts=["F1"], cited_policy=exp["cited_policy"],
                  segment_findings=findings, escalate=exp["escalate"])


@pytest.mark.parametrize("cid", [f"C-{n:04d}" for n in range(1, 7)])
def test_reference_ruling_is_consistent_with_certificate(cid):
    case, exp = load(cid)
    table = build_fact_table(case)
    cert = evaluate(case, table)
    assert exp["ruling"] in cert.allowed, (cid, cert.allowed)
    r = ruling_from_expected(cid, exp, cert)
    ok, why = check_ruling(cert, r)
    assert ok, why
    if exp.get("amount") and cid.startswith("C-000") and cert.dispute_type == "route_deviation":
        assert abs(expected_amount(cert, EXEMPT[cid]) - exp["amount"]) <= 0.011


def test_wrong_amount_is_blocked():
    case, exp = load("C-0001")
    table = build_fact_table(case); cert = evaluate(case, table)
    r = ruling_from_expected("C-0001", exp, cert).model_copy(update={"amount": exp["amount"] + 1})
    ok, why = check_ruling(cert, r)
    assert not ok and any("amount" in w for w in why)
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and out.ruling == "escalate"


def test_flipped_code_settled_finding_is_blocked():
    case, exp = load("C-0003")
    table = build_fact_table(case); cert = evaluate(case, table)
    r = ruling_from_expected("C-0003", exp, cert).model_copy(update={"ruling": "refund_partial", "amount": 1.18,
                                                                        "segment_findings": [_sf(fact_id="F3", finding="counts", reason="x")]})
    ok, why = check_ruling(cert, r)
    assert not ok and any("contradicts code" in w for w in why)


def test_fake_citation_escalates():
    case, exp = load("C-0005")
    table = build_fact_table(case); cert = evaluate(case, table)
    r = ruling_from_expected("C-0005", exp, cert).model_copy(update={"cited_policy": exp["cited_policy"] + ["RD-9"]})
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and "RD-9" in (out.escalation_reason or "")


@pytest.mark.parametrize("name,base,allowed", [
    ("swap_profiles", "C-0001", ["refund_partial", "no_action", "escalate"]), ("heavy_rain", "C-0001", ["refund_partial", "no_action", "escalate"]),
    ("grace_179", "C-0005", ["refund_full", "escalate"]), ("grace_181", "C-0005", ["no_action", "escalate"]),
    ("no_consent", "C-0001", ["refund_partial", "no_action", "escalate"]),   # the driver's messages and statement remain: the judge reads them (and finds no consent)
    ("metered_to_fixed", "C-0001", ["no_action", "escalate"]),
])
def test_counterfactuals_move_only_where_the_clause_says(name, base, allowed):
    case, _ = load(base)
    cf = apply(case, name)
    cert = evaluate(cf, build_fact_table(cf))
    assert cert.allowed == allowed
