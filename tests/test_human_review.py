"""Human review UI (app/human_review.py, app/human_review_api.py): only escalated runs get a packet; the open question's option amounts
come from the policy engine; a decision is validated and recomputed on the server; an evidence request never closes the case.

    stored runs        the reviewable set is exactly the ops page's 12 "Needs a human" cases, each with a question
    packets            the stored queue holds no open route segment, so those packets are built from stored court runs with one
                       segment finding set to undetermined (B-0013 one segment: $0.00 / $7.81; B-0015 F4 held at the court's
                       "counts": $6.49 / $14.54; B-0006 prior upheld disputes: RD-6 flag on "counts"); B-0012 safety with the
                       $8.15 route refund settled; B-0050 no adoptable option; nothing pre-selected
    decisions          reason / cited ids / client amount / manual amount / account action; segment findings carried
    trace question     B-0027 (TH-1: $63.10 above the limit) is approved by adopting the refund option or by own judgment;
                       B-0035 (GPS hole in the wait) offers the outcomes but none can be adopted
    evidence request   queue item stays open, review status awaiting_evidence
    API                GET / preview / POST, 404 / 409, demo token
"""
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import human_review
from app.main import app
from app.human_review import DecisionError, HumanDecision, NotReviewable, apply_decision, build_packet
from core.schemas import Case, CaseRecord
from core.stretch import sla
from core.stretch._util import now

ROOT = Path(__file__).resolve().parents[1]
COURT = ROOT / "bench" / "results" / "court"
ESCALATED = {"B-0001", "B-0011", "B-0012", "B-0024", "B-0027", "B-0035", "B-0040", "B-0044", "B-0047", "B-0048", "B-0049", "B-0050"}


def bench_case(cid: str) -> Case:
    return Case.model_validate(json.loads((ROOT / "data" / "bench" / "cases" / f"{cid}.json").read_text()))


def packet(cid: str) -> human_review.ReviewPacket:
    return build_packet(CaseRecord.load(COURT / f"{cid}.record.json"), bench_case(cid))


def escalated(cid: str, seg: str, ground: str = "named_road_untied") -> human_review.ReviewPacket:
    """A stored court run whose finding on `seg` is turned into "undetermined" (the court could not tell what the rider's
    agreement covered), so the run escalates on that one segment and every other finding stays as the court found it."""
    rec = CaseRecord.load(COURT / f"{cid}.record.json")
    r = rec.ruling
    sfs = [sf.model_copy(update={"finding": "undetermined", "ground": ground}) if sf.fact_id == seg else sf for sf in r.segment_findings]
    assert any(sf.fact_id == seg for sf in sfs), (cid, seg)
    r = r.model_copy(update={"ruling": "escalate", "amount": None, "escalate": True, "flag_account": False, "segment_findings": sfs,
                             "evidence_status": "unknown", "evidence_gap": "the record does not say which road the rider meant",
                             "escalation_reason": f"segment finding undetermined for {seg}"})
    rec = rec.model_copy(update={"ruling": r, "eligibility": {**(rec.eligibility or {}), "auto": False,
                                                             "reasons": [f"segment {seg} undetermined and the finding changes the outcome → a person decides (escalate)"]}})
    return build_packet(rec, bench_case(cid))


def opts(p: human_review.ReviewPacket, qid: str) -> dict:
    q = next(q for q in p.questions if q.id == qid)
    return {o.id: o for o in q.options}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.human_review_api as ra
    monkeypatch.setattr(ra, "RUNS_DIR", tmp_path)
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    return TestClient(app)


# --------------------------------------------------------------------------------------------------------- who reaches a person

def test_reviewable_set_is_exactly_the_escalated_queue(client):
    stored = {p.stem for p in (ROOT / "runs").glob("*.json") if re.match(r"[A-Z]+-\d+", p.stem)}      # not queue / precedents / reviews
    stored |= {p.name.removesuffix(".record.json") for p in COURT.glob("*.record.json")}
    got = {}
    for cid in sorted(stored):
        r = client.get(f"/api/human-review/{cid}")
        assert r.status_code in (200, 409), (cid, r.status_code, r.text)
        if r.status_code == 200:
            got[cid] = r.json()
    assert set(got) == ESCALATED == set(human_review.ops_queue_ids())
    for cid, p in got.items():
        assert p["questions"], cid
        # every question offers options; a run stopped by a check no structured field carries (TH-1 above $50, a TH-3 fraud
        # flag, a GPS hole) gets the trace question, whose options are the case outcomes themselves
        assert all(q["options"] for q in p["questions"]), cid
        assert all(q["kind"] == "decision" for q in p["questions"] if q["id"] == "trace"), cid
    assert {cid for cid, p in got.items() if p["questions"][0]["id"] == "trace"} == {"B-0027", "B-0035"}
    assert {r["case_id"] for r in client.get("/api/human-review").json()} == ESCALATED


@pytest.mark.parametrize("cid", ["B-0009", "B-0042", "B-0004"])     # refund + flag only; no refund + flag; no refund
def test_auto_cleared_cases_get_no_packet(cid, client):
    rec = CaseRecord.load(COURT / f"{cid}.record.json")
    assert human_review.auto_cleared(rec)
    with pytest.raises(NotReviewable):
        packet(cid)
    r = client.get(f"/api/human-review/{cid}")
    assert r.status_code == 409 and "cleared automatically" in r.json()["detail"]
    body = {"outcome": "own_judgment", "checked": True, "findings": {}, "reason": "x" * 20, "cited_facts": ["F1"]}
    assert client.post(f"/api/human-review/{cid}", json=body).status_code == 409
    assert client.post(f"/api/human-review/{cid}/preview", json=body).status_code == 409


def test_unknown_case_is_404_and_demo_run_not_on_the_queue_is_409(client):
    assert client.get("/api/human-review/B-9999").status_code == 404
    assert client.get("/api/human-review/C-0003").status_code == 409          # a demo run that was cleared


# --------------------------------------------------------------------------------------------------------- packets

def test_one_segment_amounts_from_the_engine():
    p = escalated("B-0013", "F3", ground="general_route_consent")
    assert [q.id for q in p.questions] == ["seg:F3"]
    o = opts(p, "seg:F3")
    assert o["exempt"].amount == 0.0 and o["exempt"].ruling == "no_action"          # 5.54 km − 4.97 km exempt ≤ 1 km tolerance
    assert o["counts"].amount == 7.81 and o["counts"].ruling == "refund_partial"
    assert p.evidence_gap is not None and p.evidence_gap.status == "unknown"
    assert p.questions[0].adoptable                                       # unknown is not insufficient: the options stand


def test_other_segment_held_at_its_final_finding():
    p = escalated("B-0015", "F3")
    o = opts(p, "seg:F3")
    assert (o["exempt"].amount, o["counts"].amount) == (6.49, 14.54)
    f4 = next(s for s in p.settled if s.subject == "F4")
    assert (f4.finding, f4.by) == ("counts", "judge")
    assert p.queue == "review_24h" and p.sla_hours == 24 and p.due_at is not None
    assert p.questions[0].sides["rider"].ground == "named_road_tied"
    assert all(e.fact_id in p.facts for e in p.questions[0].evidence) and 3 <= len(p.questions[0].evidence) <= 5
    assert {"F8", "F9"} <= {e.fact_id for e in p.questions[0].evidence if e.quote}
    assert p.links["court"] == "/replay.html?case=B-0015&phase=court" and p.links["receipt"] == "/receipt.html?run=B-0015"


def test_settled_amount_is_the_rd2_amount_of_the_settled_findings():
    """The refund already fixed outside the open question is the RD-2 amount of the whole trip (deviation less the exempt
    km, 1 km tolerance), the same amount the options carry, not a sum of per-segment km × rate."""
    p = packet("B-0012")                                     # one segment, settled "counts" by code; safety question open
    assert {o.amount for o in opts(p, "safety").values()} == {8.15}
    assert p.settled_amount == 8.15
    p = escalated("B-0015", "F3")                            # F4 counts (court), F3 open: with F3 exempt the refund is $6.49
    assert p.settled_amount == opts(p, "seg:F3")["exempt"].amount == 6.49


def test_safety_question_with_the_route_refund_settled():
    p = packet("B-0012")
    assert [q.id for q in p.questions] == ["safety"] and p.queue == "urgent_safety"
    assert next(s for s in p.settled if s.subject == "F3").by == "code"
    q = p.questions[0]
    assert q.vocabulary == "proposed" and all(o.proposed for o in q.options)
    assert {o.id for o in q.options} == {"none", "misconduct", "threat_or_harassment", "unsubstantiated"}
    assert all(o.amount == 8.15 and o.ruling == "refund_partial" for o in q.options)
    threat = opts(p, "safety")["threat_or_harassment"]
    assert threat.flag_account and threat.requires_confirmation


def test_evidence_gap_leaves_no_adoptable_option():
    rec = CaseRecord.load(COURT / "B-0050.record.json")        # harassment complaint, no chat: the record holds no account of it
    rec = rec.model_copy(update={"ruling": rec.ruling.model_copy(update={"evidence_status": "insufficient",
                                                                         "evidence_gap": "no chat or recording of the cabin (F3)"})})
    p = build_packet(rec, bench_case("B-0050"))
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
    packets = [packet(cid) for cid in sorted(ESCALATED)] + [escalated("B-0013", "F3"), escalated("B-0015", "F3"), escalated("B-0006", "F4")]
    for p in packets:
        for q in p.questions:
            assert all(o.lean is None for o in q.options), p.case_id


# --------------------------------------------------------------------------------------------------------- decisions

def test_adopt_recomputes_the_amount_and_carries_segment_findings():
    p = escalated("B-0015", "F3")
    r = apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "exempt"}))
    assert (r.ruling, r.amount, r.escalate) == ("refund_partial", 6.49, False)
    f = {s.fact_id: s for s in r.segment_findings}
    assert f["F3"].finding == "exempt" and f["F3"].ground == "named_road_tied"
    assert f["F4"].finding == "counts" and f["F4"].ground == "consent_after_or_none"     # the court's finding is kept
    r0 = apply_decision(escalated("B-0013", "F3"), HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "exempt"}))
    assert r0.ruling == "no_action" and r0.amount is None


def test_adopt_rejects_a_client_amount_and_unknown_options():
    p = escalated("B-0015", "F3")
    with pytest.raises(DecisionError, match="computed by code"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "counts"}, amount=99.0))
    with pytest.raises(DecisionError, match="unknown option"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "half"}))
    with pytest.raises(DecisionError, match="choose an option"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True))
    with pytest.raises(DecisionError, match="checked"):
        apply_decision(p, HumanDecision(outcome="adopt_option", choices={"seg:F3": "counts"}))


def test_own_judgment_needs_a_reason_and_real_fact_ids():
    p = escalated("B-0015", "F3")
    base = dict(outcome="own_judgment", checked=True, findings={"seg:F3": "counts"}, cited_facts=["F3", "F9"])
    with pytest.raises(DecisionError, match="15 characters"):
        apply_decision(p, HumanDecision(**base, reason="too short"))
    with pytest.raises(DecisionError, match="unknown fact"):
        apply_decision(p, HumanDecision(**{**base, "cited_facts": ["F3", "F99"]}, reason="The reply answered a different road."))
    with pytest.raises(DecisionError, match="at least one fact"):
        apply_decision(p, HumanDecision(**{**base, "cited_facts": []}, reason="The reply answered a different road."))
    r = apply_decision(p, HumanDecision(**base, reason="The reply answered a different road."))
    assert r.amount == 14.54 and r.cited_facts == ["F3", "F9"]


def test_manual_amount_needs_a_second_confirmation_and_keeps_the_formula(tmp_path):
    p = escalated("B-0015", "F3")
    d = dict(outcome="own_judgment", checked=True, findings={"seg:F3": "counts"}, cited_facts=["F3"], reason="Only half of F3 was off the agreed road.")
    with pytest.raises(DecisionError, match="confirm it a second time"):
        apply_decision(p, HumanDecision(**d, amount_override={"amount": 10.0}))
    dec = HumanDecision(**d, amount_override={"amount": 10.0, "confirmed": True})
    r = apply_decision(p, dec)
    assert r.amount == 10.0 and "formula $14.54" in r.recommended_action
    out = human_review.record_decision(p, dec, tmp_path)
    assert out["review"]["formula_amount"] == 14.54 and out["override"]["human_amount"] == 10.0
    with pytest.raises(DecisionError, match="amount_override"):
        apply_decision(p, HumanDecision(**d, amount=10.0))


def test_account_action_needs_a_second_confirmation():
    p = packet("B-0012")
    d = dict(outcome="adopt_option", checked=True, choices={"safety": "threat_or_harassment"})
    with pytest.raises(DecisionError, match="account"):
        apply_decision(p, HumanDecision(**d))
    r = apply_decision(p, HumanDecision(**d, confirm_account_action=True))
    assert (r.ruling, r.amount, r.flag_account, r.safety_concern) == ("refund_partial", 8.15, True, "confirmed")


def test_rd6_flag_follows_a_counted_segment():
    p = escalated("B-0006", "F4", ground="rider_named_stop")    # driver with prior upheld route disputes
    o = opts(p, "seg:F4")
    assert o["counts"].flag_account and not o["exempt"].flag_account
    assert (o["counts"].ruling, o["counts"].amount) == ("refund_partial", 2.85) and o["exempt"].ruling == "no_action"
    r = apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F4": "counts"}))
    assert r.ruling == "refund_partial" and r.amount == 2.85 and r.flag_account and "RD-6" in r.cited_policy


# --------------------------------------------------------------------------------------------------------- trace question

def test_over_limit_refund_is_approved_by_adopting_the_code_amount(tmp_path):
    p = packet("B-0027")                                    # surge refund above the TH-1 limit: the record is complete
    assert [q.id for q in p.questions] == ["trace"]
    q = p.questions[0]
    assert q.kind == "decision" and q.adoptable and not p.evidence_gap
    o = opts(p, "trace")
    assert set(o) == {"refund_partial", "no_action"} and set(o) <= set(p.allowed)
    code = p._cert.amount
    assert o["refund_partial"].amount == code == 63.10 and o["no_action"].amount is None
    assert not any(x.lean for x in q.options)               # nothing pre-selected
    r = apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"trace": "refund_partial"}))
    assert r.ruling == "refund_partial" and r.amount == code and not r.escalate and "SURGE-2" in r.cited_policy
    with pytest.raises(DecisionError, match="computed by code"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"trace": "refund_partial"}, amount=10.0))
    # the precedent store has no features for a surge fare dispute: the decision is still recorded and the queue item resolved
    sla.enqueue("B-0027", sla._route("review_24h", "escalated: human review"), tmp_path)
    out = human_review.record_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"trace": "refund_partial"}), tmp_path)
    assert out["review"]["ruling"]["amount"] == code and out["override"]["human_amount"] == code
    assert human_review.review_status("B-0027", tmp_path) == "decided"
    assert next(i for i in sla.list_queue(tmp_path) if i.case_id == "B-0027").status == "resolved"


def test_over_limit_refund_by_own_judgment():
    p = packet("B-0027")
    own = HumanDecision(outcome="own_judgment", checked=True, findings={"trace": "refund_partial"},
                        reason="The notice gave no revised fare, so the surge part goes back.", cited_facts=["F1"])
    r = apply_decision(p, own)
    assert r.ruling == "refund_partial" and r.amount == p._cert.amount


def test_gps_hole_offers_the_outcomes_but_none_can_be_adopted(tmp_path):
    p = packet("B-0035")                                    # no-show with a hole in the GPS during the wait
    q = p.questions[0]
    assert q.id == "trace" and q.kind == "decision" and not q.adoptable
    assert p.evidence_gap is not None and p.evidence_gap.status == "insufficient"
    o = opts(p, "trace")
    assert set(o) == {"refund_full", "no_action"} and o["refund_full"].amount == p._cert.fee
    with pytest.raises(DecisionError, match="cannot support"):
        apply_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"trace": "refund_full"}))
    own = HumanDecision(outcome="own_judgment", checked=True, findings={"trace": "refund_full"},
                        reason="Presence at the pickup is not shown for the hole, so the fee is voided.", cited_facts=["F1", "F4"])
    r = apply_decision(p, own)
    assert r.ruling == "refund_full" and r.amount == p._cert.fee and not r.escalate
    keep = apply_decision(p, own.model_copy(update={"findings": {"trace": "no_action"}}))
    assert keep.ruling == "no_action" and keep.amount is None
    req = HumanDecision(outcome="request_evidence", checked=True,
                        request={"to": "platform", "items": ["The missing GPS points for 14:09:10-14:12:30"], "due_in_hours": 48, "on_timeout": "decide_on_record"})
    assert human_review.request_evidence(p, req, tmp_path)["status"] == "awaiting_evidence"
    assert human_review.review_status("B-0035", tmp_path) == "awaiting_evidence"


def test_api_decides_the_trace_cases(client, tmp_path):
    adopt = {"outcome": "adopt_option", "checked": True, "choices": {"trace": "refund_partial"}}
    pv = client.post("/api/human-review/B-0027/preview", json=adopt)
    assert pv.status_code == 200 and pv.json()["ruling"]["amount"] == 63.10
    assert client.post("/api/human-review/B-0027", json=adopt).json()["status"] == "decided"
    own = {"outcome": "own_judgment", "checked": True, "findings": {"trace": "refund_full"},
           "reason": "Presence at the pickup is not shown for the hole.", "cited_facts": ["F1"]}
    assert client.post("/api/human-review/B-0035", json={**own, "outcome": "adopt_option", "choices": own["findings"]}).status_code == 422
    assert client.post("/api/human-review/B-0035", json=own).json()["status"] == "decided"


# --------------------------------------------------------------------------------------------------------- evidence request

def test_request_evidence_keeps_the_case_open(tmp_path):
    p = escalated("B-0013", "F3")
    d = HumanDecision(outcome="request_evidence", checked=True,
                      request={"to": "driver", "items": ["Which road did you drive 18:44-18:52?"], "due_in_hours": 48, "on_timeout": "decide_on_record"})
    with pytest.raises(DecisionError):
        apply_decision(p, d)                                # no ruling comes out of a request
    out = human_review.request_evidence(p, d, tmp_path)
    assert out["status"] == "awaiting_evidence"
    item = next(i for i in sla.list_queue(tmp_path) if i.case_id == "B-0013")
    assert item.status == "open" and item.resolved_at is None and item.note.startswith("awaiting_evidence")
    assert abs((item.due_at - now()) - timedelta(hours=48)) < timedelta(minutes=1)
    assert human_review.review_status("B-0013", tmp_path) == "awaiting_evidence"
    assert not (tmp_path / "overrides.json").exists()
    # the person later decides: the item is resolved through the existing override path
    human_review.record_decision(p, HumanDecision(outcome="adopt_option", checked=True, choices={"seg:F3": "counts"}), tmp_path)
    assert human_review.review_status("B-0013", tmp_path) == "decided"
    assert next(i for i in sla.list_queue(tmp_path) if i.case_id == "B-0013").status == "resolved"


def test_evidence_request_shape_is_validated():
    with pytest.raises(ValueError):
        HumanDecision(outcome="request_evidence", request={"to": "police", "items": ["x"], "due_in_hours": 24, "on_timeout": "decide_on_record"})
    with pytest.raises(ValueError):
        HumanDecision(outcome="request_evidence", request={"to": "rider", "items": [" "], "due_in_hours": 24, "on_timeout": "decide_on_record"})
    with pytest.raises(ValueError):
        HumanDecision(outcome="request_evidence", request={"to": "rider", "items": ["x"], "due_in_hours": 24, "on_timeout": "refund"})


# --------------------------------------------------------------------------------------------------------- API

def test_api_preview_decide_and_status(client, tmp_path):
    r = client.get("/api/human-review/B-0012")
    assert r.status_code == 200 and r.json()["status"] == "open"
    body = {"outcome": "adopt_option", "checked": True, "choices": {"safety": "misconduct"}}
    pv = client.post("/api/human-review/B-0012/preview", json=body).json()
    assert pv["ruling"]["amount"] == 8.15 and "$8.15" in pv["notices"]["rider"]
    assert not (tmp_path / "human_reviews.json").exists()                        # a preview stores nothing
    bad = client.post("/api/human-review/B-0012", json={**body, "amount": 1.0})
    assert bad.status_code == 422 and "computed by code" in bad.json()["detail"]
    ok = client.post("/api/human-review/B-0012", json=body)
    assert ok.status_code == 200 and ok.json()["status"] == "decided"
    assert json.loads((tmp_path / "overrides.json").read_text())[-1]["human_amount"] == 8.15
    assert any(e["case_id"] == "B-0012" and e["source"] == "human" for e in json.loads((tmp_path / "precedents.json").read_text()))
    assert client.get("/api/human-review/B-0012").json()["status"] == "decided"
    req = {"outcome": "request_evidence", "checked": True, "request": {"to": "platform", "items": ["GPS log for the last 10 minutes"], "due_in_hours": 24, "on_timeout": "close_no_action"}}
    assert client.post("/api/human-review/B-0011", json=req).json()["status"] == "awaiting_evidence"
    got = client.get("/api/human-review/B-0011").json()
    assert got["status"] == "awaiting_evidence" and got["pending_request"]["request"]["to"] == "platform"


def test_api_uses_the_demo_token(client, monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "s3cret")
    body = {"outcome": "adopt_option", "checked": True, "choices": {"safety": "misconduct"}}
    assert client.post("/api/human-review/B-0012", json=body).status_code == 401
    assert client.post("/api/human-review/B-0012", json=body, headers={"X-Demo-Token": "s3cret"}).status_code == 200
    assert client.post("/api/human-review/B-0012/preview", json=body).status_code == 200    # a dry run writes nothing
