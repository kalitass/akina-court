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

ROOT = Path(__file__).resolve().parents[1]
EXEMPT = {"C-0001": {"F4": True, "F5": False}, "C-0002": {"F3": False}, "C-0003": {"F3": True}}


def load(cid):
    case = Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))
    exp = json.loads((ROOT / "data" / "expected" / f"{cid}.json").read_text())
    return case, exp


def ruling_from_expected(cid, exp, cert):
    findings = [SegmentFinding(fact_id=f, exempt=e, reason="ref") for f, e in EXEMPT.get(cid, {}).items()]
    return Ruling(ruling=exp["ruling"], amount=exp.get("amount"), recommended_action="x" + (" + flag_account" if cert.flag_required else ""), flag_account=bool(cert.flag_required),
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
                                                                        "segment_findings": [SegmentFinding(fact_id="F3", exempt=False, reason="x")]})
    ok, why = check_ruling(cert, r)
    assert not ok and any("contradicts code" in w for w in why)


def test_fake_citation_escalates():
    case, exp = load("C-0005")
    table = build_fact_table(case); cert = evaluate(case, table)
    r = ruling_from_expected("C-0005", exp, cert).model_copy(update={"cited_policy": exp["cited_policy"] + ["RD-9"]})
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and "RD-9" in (out.escalation_reason or "")


@pytest.mark.parametrize("name,base,allowed", [
    ("swap_profiles", "C-0001", ["refund_partial", "no_action"]), ("heavy_rain", "C-0001", ["refund_partial", "no_action"]),
    ("grace_179", "C-0005", ["refund_full"]), ("grace_181", "C-0005", ["no_action"]),
    ("no_consent", "C-0001", ["refund_partial"]), ("metered_to_fixed", "C-0001", ["no_action"]),
])
def test_counterfactuals_move_only_where_the_clause_says(name, base, allowed):
    case, _ = load(base)
    cf = apply(case, name)
    cert = evaluate(cf, build_fact_table(cf))
    assert cert.allowed == allowed
