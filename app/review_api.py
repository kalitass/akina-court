"""Reviewer page API (web/review.html). Only cases on the human-review queue (web/ops.html "Needs a human") have a packet.

    GET  /api/review                 the reviewable cases: queue, SLA, status, question kind and title
    GET  /api/review/{id}            ReviewPacket (404 no stored run; 409 cleared automatically / not on the queue)
    POST /api/review/{id}/preview    dry run of a HumanDecision: the ruling and amounts code computes, both notices; nothing saved
    POST /api/review/{id}            record a HumanDecision (X-Demo-Token, as /api/override): adopt_option / own_judgment go
                                     through feedback.record_override; request_evidence keeps the case open (awaiting_evidence)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app import review
from app.review import DecisionError, HumanDecision, NotReviewable
from core.schemas import CaseRecord

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"                     # decisions, overrides, precedents and the queue file (tests point this at tmp_path)
router = APIRouter()


def _store(cid: str, scenario: str):
    if scenario == 'stored':
        return RUNS_DIR
    if scenario != 'missing_gps':
        raise HTTPException(400, 'Unknown review scenario')
    from app.review_recovery import directory
    return directory(RUNS_DIR, cid)


def _packet(cid: str, scenario: str = 'stored') -> review.ReviewPacket:
    from app.main import load_case, stored_run_path      # lazy: app.main includes this router
    if scenario != 'stored':
        from app.review_recovery import packet
        return packet(load_case(cid), _store(cid, scenario))[0]
    p = review.OPS_QUEUE_DIR / f"{cid}.record.json"
    if cid not in set(review.ops_queue_ids()):
        any_run = stored_run_path(cid) or (p if p.exists() else None)
        if any_run is None:
            raise HTTPException(404, f"no stored run for {cid}")
        rec = CaseRecord.load(any_run)
        if review.auto_cleared(rec):
            raise HTTPException(409, f"{cid} was cleared automatically; no human review")
        raise HTTPException(409, f"{cid} is not on the human-review queue (web/ops.html lists the escalated benchmark runs)")
    try:
        packet = review.build_packet(CaseRecord.load(p), load_case(cid))
    except NotReviewable as e:
        raise HTTPException(409, str(e))
    packet.status = review.review_status(cid, RUNS_DIR)
    decision, req = review.latest(cid, RUNS_DIR)
    packet.decision, packet.pending_request = decision, (req if packet.status == "awaiting_evidence" else None)
    return packet


def _queue_due(cid: str, scenario: str = 'stored'):
    from core.stretch import sla
    hit = next((i for i in sla.list_queue(_store(cid, scenario)) if i.case_id == cid), None)
    return hit.due_at if hit else None


@router.get("/api/review")
def review_queue():
    out = []
    for cid in review.ops_queue_ids():
        p = _packet(cid)
        q = p.questions[0]
        out.append({"case_id": cid, "dispute_type": p.dispute_type, "queue": p.queue, "sla_hours": p.sla_hours,
                    "due_at": (_queue_due(cid) or p.due_at), "status": p.status, "safety_concern": p.safety_concern,
                    "question_kind": q.kind, "title": q.title, "questions": len(p.questions), "statement": p.statement})
    order = {"urgent_safety": 0, "review_24h": 1}
    return sorted(out, key=lambda r: (r["status"] == "decided", order.get(r["queue"], 2), str(r["due_at"])))


@router.get("/api/review/{cid}")
def review_packet(cid: str, scenario: str = 'stored'):
    p = _packet(cid, scenario)
    due = _queue_due(cid, scenario)
    out = p.model_dump(mode="json")
    if due is not None:
        out["due_at"] = due.isoformat()
    if scenario == 'missing_gps':
        from app.main import load_case
        from app.review_recovery import packet
        _, current, recovery = packet(load_case(cid), _store(cid, scenario))
        from core.facts.tools import build_fact_table
        out.update(current_case=current.model_dump(mode='json'), current_facts=build_fact_table(current).model_dump(mode='json'), recovery=recovery)
    return out


@router.post("/api/review/{cid}/preview")
def review_preview(cid: str, decision: HumanDecision, scenario: str = 'stored'):
    p = _packet(cid, scenario)
    try:
        if decision.outcome == "request_evidence":
            return {"outcome": decision.outcome, "notices": review.notice_preview(p, decision)}
        ruling = review.apply_decision(p, decision)
        return {"outcome": decision.outcome, "ruling": ruling.model_dump(mode="json"), "formula_amount": review.formula_amount(p, decision),
                "notices": review.notice_preview(p, decision, ruling)}
    except DecisionError as e:
        raise HTTPException(422, str(e))


@router.post("/api/review/{cid}")
def review_decide(cid: str, decision: HumanDecision, x_demo_token: Optional[str] = Header(default=None), scenario: str = 'stored'):
    from app.main import _check_token                     # the same demo-token rule as /api/override
    _check_token(x_demo_token)
    p = _packet(cid, scenario)
    try:
        if decision.outcome == "request_evidence":
            return review.request_evidence(p, decision, _store(cid, scenario))
        return review.record_decision(p, decision, _store(cid, scenario))
    except DecisionError as e:
        raise HTTPException(422, str(e))


from app.review_recovery import ReceiveGps


@router.post('/api/review/{cid}/receive-gps')
def receive_review_gps(cid: str, body: ReceiveGps, scenario: str = 'stored', x_demo_token: Optional[str] = Header(default=None)):
    from app.main import _check_token, load_case
    _check_token(x_demo_token)
    if scenario != 'missing_gps':
        raise HTTPException(422, 'Synthetic GPS provider cannot fulfil this live queue case; obtain the requested authoritative record')
    from app.review_recovery import receive
    return receive(load_case(cid), _store(cid, scenario), body)
