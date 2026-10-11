"""Reviewer page (app/review.py, app/review_api.py): only escalated runs get a packet; the open question's option amounts
come from the policy engine; a decision is validated and recomputed on the server; an evidence request never closes the case.

    stored runs        the reviewable set is exactly the ops page's 23 "Needs a human" cases, each with a question
    packets            B-0002 $0.00 / $4.61; B-0013 $6.74 / $14.72 (F4 settled $6.74); B-0024 safety, $7.25 settled;
                       B-0047 no adoptable option; nothing pre-selected
    decisions          reason / cited ids / client amount / manual amount / account action; segment findings carried
    evidence request   queue item stays open, review status awaiting_evidence
    API                GET / preview / POST, 404 / 409, demo token
"""
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import review
from app.main import app
from app.review import DecisionError, HumanDecision, NotReviewable, apply_decision, build_packet
from core.schemas import Case, CaseRecord
from core.stretch import sla
from core.stretch._util import now

ROOT = Path(__file__).resolve().parents[1]
COURT = ROOT / "bench" / "results" / "court"
ESCALATED = {"B-0002", "B-0010", "B-0013", "B-0017", "B-0023", "B-0024", "B-0025", "B-0041", "B-0044", "B-0045", "B-0046", "B-0047",
             "B-0048", "B-0054", "B-0055", "B-0056", "B-0057", "B-0058", "B-0059", "B-0060", "B-0061", "B-0064", "B-0065"}


def packet(cid: str) -> review.ReviewPacket:
    rec = CaseRecord.load(COURT / f"{cid}.record.json")
    case = Case.model_validate(json.loads((ROOT / "data" / "bench" / "cases" / f"{cid}.json").read_text()))
    return build_packet(rec, case)


def opts(p: review.ReviewPacket, qid: str) -> dict:
    q = next(q for q in p.questions if q.id == qid)
    return {o.id: o for o in q.options}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.review_api as ra
    monkeypatch.setattr(ra, "RUNS_DIR", tmp_path)
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    return TestClient(app)


# --------------------------------------------------------------------------------------------------------- who reaches a person

def test_reviewable_set_is_exactly_the_escalated_queue(client):
    stored = {p.stem for p in (ROOT / "runs").glob("*.json") if re.match(r"[A-Z]+-\d+", p.stem)}      # not queue / precedents / reviews
    stored |= {p.name.removesuffix(".record.json") for d in (COURT, ROOT / "bench" / "results" / "blind" / "court") for p in d.glob("*.record.json")}
    got = {}
    for cid in sorted(stored):
        r = client.get(f"/api/review/{cid}")
        assert r.status_code in (200, 409), (cid, r.status_code, r.text)
        if r.status_code == 200:
            got[cid] = r.json()
    assert set(got) == ESCALATED == set(review.ops_queue_ids())
    for cid, p in got.items():
        assert p["questions"], cid
        assert all(q["options"] for q in p["questions"]), cid
    assert {r["case_id"] for r in client.get("/api/review").json()} == ESCALATED


@pytest.mark.parametrize("cid", ["B-0026", "B-0019", "B-0004"])     # refund + flag only; no refund + flag; no refund
def test_auto_cleared_cases_get_no_packet(cid, client):
    rec = CaseRecord.load(COURT / f"{cid}.record.json")
    assert review.auto_cleared(rec)
    with pytest.raises(NotReviewable):
        packet(cid)
    r = client.get(f"/api/review/{cid}")
    assert r.status_code == 409 and "cleared automatically" in r.json()["detail"]
    body = {"outcome": "own_judgment", "checked": True, "findings": {}, "reason": "x" * 20, "cited_facts": ["F1"]}
    assert client.post(f"/api/review/{cid}", json=body).status_code == 409
    assert client.post(f"/api/review/{cid}/preview", json=body).status_code == 409


def test_unknown_case_is_404_and_demo_run_not_on_the_queue_is_409(client):
    assert client.get("/api/review/B-9999").status_code == 404
    assert client.get("/api/review/C-0003").status_code == 409          # a demo run that was cleared


# --------------------------------------------------------------------------------------------------------- packets

def test_b0002_one_segment_amounts_from_the_engine():
    p = packet("B-0002")
    assert [q.id for q in p.questions] == ["seg:F3"]
    o = opts(p, "seg:F3")
    assert o["exempt"].amount == 0.0 and o["exempt"].ruling == "no_action"
    assert o["counts"].amount == 4.61 and o["counts"].ruling == "refund_partial"
    assert p.evidence_gap is not None and p.evidence_gap.status == "unknown"
    assert p.questions[0].adoptable                                       # unknown is not insufficient: the options stand


def test_b0013_other_segment_held_at_its_final_finding():
    p = packet("B-0013")
    o = opts(p, "seg:F3")
    assert (o["exempt"].amount, o["counts"].amount) == (6.74, 14.72)
    f4 = next(s for s in p.settled if s.subject == "F4")
    assert (f4.finding, f4.amount, f4.by) == ("counts", 6.74, "judge")
    assert p.settled_amount == 6.74
    assert p.queue == "review_24h" and p.sla_hours == 24 and p.due_at is not None
    assert p.questions[0].sides["rider"].ground == "named_road_untied"
    assert all(e.fact_id in p.facts for e in p.questions[0].evidence) and 3 <= len(p.questions[0].evidence) <= 5
    assert {"F9", "F10"} <= {e.fact_id for e in p.questions[0].evidence if e.quote}
    assert p.links["court"] == "/replay.html?case=B-0013&phase=court" and p.links["receipt"] == "/receipt.html?run=B-0013"


def test_b0024_safety_question_with_the_route_refund_settled():
    p = packet("B-0024")
    assert [q.id for q in p.questions] == ["safety"] and p.queue == "urgent_safety"
    assert p.settled_amount == 7.25
    q = p.questions[0]
    assert q.vocabulary == "proposed" and all(o.proposed for o in q.options)
    assert {o.id for o in q.options} == {"none", "misconduct", "threat_or_harassment", "unsubstantiated"}
    assert all(o.amount == 7.25 and o.ruling == "refund_partial" for o in q.options)
    threat = opts(p, "safety")["threat_or_harassment"]
    assert threat.flag_account and threat.requires_confirmation


def test_b0047_evidence_gap_leaves_no_adoptable_option():
    p = packet("B-0047")
    assert p.evidence_gap.status == "insufficient" and "F3" in p.evidence_gap.facts
    assert not any(q.adoptable for q in p.questions)
    d = HumanDecision(outcome="adopt_option", checked=True, choices={"safety": "unsubstantiated"})
    with pytest.raises(DecisionError, match="cannot support"):
        apply_decision(p, d)
    own = HumanDecision(outcome="own_judgment", checked=True, findings={"safety": "unsubstantiated"},
                        reason="No record of the cabin; both accounts conflict.", cited_facts=["F3", "F4"])
    r = apply_decision(p, own)
    assert r.ruling == "no_action" and r.safety_concern == "suspected" and not r.escalate


def test_nothing_is_preselected_and_no_option_leans_without_a_rule():
    for cid in sorted(ESCALATED):
        for q in packet(cid).questions:
            assert all(o.lean is None for o in q.options), cid


# --------------------------------------------------------------------------------------------------------- decisions

def test_adopt_recomputes_the_amount_and_carries_segment_findings():
    p = packet("B-0013")
    r = apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "exempt"}))
    assert (r.ruling, r.amount, r.escalate) == ("refund_partial", 6.74, False)
    f = {s.fact_id: s for s in r.segment_findings}
    assert f["F3"].finding == "exempt" and f["F3"].ground == "named_road_tied"
    assert f["F4"].finding == "counts" and f["F4"].ground == "consent_after_or_none"     # the court's finding is kept
    r0 = apply_decision(packet("B-0002"), HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "exempt"}))
    assert r0.ruling == "no_action" and r0.amount is None


def test_adopt_rejects_a_client_amount_and_unknown_options():
    p = packet("B-0013")
    with pytest.raises(DecisionError, match="computed by code"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "counts"}, amount=99.0))
    with pytest.raises(DecisionError, match="unknown option"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "half"}))
    with pytest.raises(DecisionError, match="choose an option"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True))
    with pytest.raises(DecisionError, match="checked"):
        apply_decision(p, HumanDecision(outcome="adopt_option", choices={"seg:F3": "counts"}))


def test_own_judgment_needs_a_reason_and_real_fact_ids():
    p = packet("B-0013")
    base = dict(outcome="own_judgment", checked=True, findings={"seg:F3": "counts"}, cited_facts=["F3", "F10"])
    with pytest.raises(DecisionError, match="15 characters"):
        apply_decision(p, HumanDecision(**base, reason="too short"))
    with pytest.raises(DecisionError, match="unknown fact"):
        apply_decision(p, HumanDecision(**{**base, "cited_facts": ["F3", "F99"]}, reason="The reply answered a different road."))
    with pytest.raises(DecisionError, match="at least one fact"):
        apply_decision(p, HumanDecision(**{**base, "cited_facts": []}, reason="The reply answered a different road."))
    r = apply_decision(p, HumanDecision(**base, reason="The reply answered a different road."))
    assert r.amount == 14.72 and r.cited_facts == ["F3", "F10"]


def test_manual_amount_needs_a_second_confirmation_and_keeps_the_formula(tmp_path):
    p = packet("B-0013")
    d = dict(outcome="own_judgment", checked=True, findings={"seg:F3": "counts"}, cited_facts=["F3"], reason="Only half of F3 was off the agreed road.")
    with pytest.raises(DecisionError, match="confirm it a second time"):
        apply_decision(p, HumanDecision(**d, amount_override={"amount": 10.0}))
    dec = HumanDecision(**d, amount_override={"amount": 10.0, "confirmed": True})
    r = apply_decision(p, dec)
    assert r.amount == 10.0 and "formula $14.72" in r.recommended_action
    out = review.record_decision(p, dec, tmp_path)
    assert out["review"]["formula_amount"] == 14.72 and out["override"]["human_amount"] == 10.0
    with pytest.raises(DecisionError, match="amount_override"):
        apply_decision(p, HumanDecision(**d, amount=10.0))


def test_account_action_needs_a_second_confirmation():
    p = packet("B-0024")
    d = dict(outcome="adopt_option", checked=True, choices={"safety": "threat_or_harassment"})
    with pytest.raises(DecisionError, match="account"):
        apply_decision(p, HumanDecision(**d))
    r = apply_decision(p, HumanDecision(**d, confirm_account_action=True))
    assert (r.ruling, r.amount, r.flag_account, r.safety_concern) == ("refund_partial", 7.25, True, "confirmed")


def test_rd6_flag_follows_a_counted_segment():
    p = packet("B-0065")                                   # fixed fare, driver with prior upheld route disputes
    o = opts(p, "seg:F3")
    assert o["counts"].flag_account and not o["exempt"].flag_account and o["counts"].amount is None
    r = apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "counts"}))
    assert r.ruling == "no_action" and r.flag_account and "RD-6" in r.cited_policy


# --------------------------------------------------------------------------------------------------------- evidence request

def test_request_evidence_keeps_the_case_open(tmp_path):
    p = packet("B-0002")
    d = HumanDecision(outcome="request_evidence", checked=True,
                      request={"to": "driver", "items": ["Which road did you drive 12:29-12:39?"], "due_in_hours": 48, "on_timeout": "decide_on_record"})
    with pytest.raises(DecisionError):
        apply_decision(p, d)                                # no ruling comes out of a request
    out = review.request_evidence(p, d, tmp_path)
    assert out["status"] == "awaiting_evidence"
    item = next(i for i in sla.list_queue(tmp_path) if i.case_id == "B-0002")
    assert item.status == "open" and item.resolved_at is None and item.note.startswith("awaiting_evidence")
    assert abs((item.due_at - now()) - timedelta(hours=48)) < timedelta(minutes=1)
    assert review.review_status("B-0002", tmp_path) == "awaiting_evidence"
    assert not (tmp_path / "overrides.json").exists()
    # the person later decides: the item is resolved through the existing override path
    review.record_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "counts"}), tmp_path)
    assert review.review_status("B-0002", tmp_path) == "decided"
    assert next(i for i in sla.list_queue(tmp_path) if i.case_id == "B-0002").status == "resolved"


def test_evidence_request_shape_is_validated():
    with pytest.raises(ValueError):
        HumanDecision(outcome="request_evidence", request={"to": "police", "items": ["x"], "due_in_hours": 24, "on_timeout": "decide_on_record"})
    with pytest.raises(ValueError):
        HumanDecision(outcome="request_evidence", request={"to": "rider", "items": [" "], "due_in_hours": 24, "on_timeout": "decide_on_record"})
    with pytest.raises(ValueError):
        HumanDecision(outcome="request_evidence", request={"to": "rider", "items": ["x"], "due_in_hours": 24, "on_timeout": "refund"})


# --------------------------------------------------------------------------------------------------------- API

def test_api_preview_decide_and_status(client, tmp_path):
    r = client.get("/api/review/B-0013")
    assert r.status_code == 200 and r.json()["status"] == "open"
    body = {"outcome": "adopt_option", "checked": True, "choices": {"seg:F3": "counts"}}
    pv = client.post("/api/review/B-0013/preview", json=body).json()
    assert pv["ruling"]["amount"] == 14.72 and "$14.72" in pv["notices"]["rider"]
    assert not (tmp_path / "reviews.json").exists()                        # a preview stores nothing
    bad = client.post("/api/review/B-0013", json={**body, "amount": 1.0})
    assert bad.status_code == 422 and "computed by code" in bad.json()["detail"]
    ok = client.post("/api/review/B-0013", json=body)
    assert ok.status_code == 200 and ok.json()["status"] == "decided"
    assert json.loads((tmp_path / "overrides.json").read_text())[-1]["human_amount"] == 14.72
    assert any(e["case_id"] == "B-0013" and e["source"] == "human" for e in json.loads((tmp_path / "precedents.json").read_text()))
    assert client.get("/api/review/B-0013").json()["status"] == "decided"
    req = {"outcome": "request_evidence", "checked": True, "request": {"to": "platform", "items": ["navigation log"], "due_in_hours": 24, "on_timeout": "close_no_action"}}
    assert client.post("/api/review/B-0010", json=req).json()["status"] == "awaiting_evidence"
    got = client.get("/api/review/B-0010").json()
    assert got["status"] == "awaiting_evidence" and got["pending_request"]["request"]["to"] == "platform"


def test_api_uses_the_demo_token(client, monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "s3cret")
    body = {"outcome": "adopt_option", "checked": True, "choices": {"seg:F3": "counts"}}
    assert client.post("/api/review/B-0013", json=body).status_code == 401
    assert client.post("/api/review/B-0013", json=body, headers={"X-Demo-Token": "s3cret"}).status_code == 200
    assert client.post("/api/review/B-0013/preview", json=body).status_code == 200    # a dry run writes nothing
