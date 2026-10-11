"""GPS recovery inside the formal reviewer workflow, isolated synthetic intake.

The same request/decision/SLA stores are used throughout. No court result is
invented, no original case is changed, and receiving telemetry never decides it.
"""
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from app import review
from app.evidence import SyntheticGpsProvider, digest, recover
from core.facts.tools import build_fact_table
from core.schemas import Case, CaseRecord, Ruling
from core.stretch._util import read_json, write_json

LOCK = RLock()


class ReceiveGps(BaseModel):
    requested_at: str
    mode: Literal['available', 'unavailable', 'conflict'] = 'available'


def directory(base: Path, cid: str) -> Path:
    if cid != 'C-0004':
        raise HTTPException(400, 'The formal missing-GPS demonstration supports C-0004 only')
    return base / 'review_recovery_demo' / cid


def snapshot(full: Case, store: Path):
    initial = full.model_copy(deep=True)
    initial.gps = []
    accepted = read_json(store / 'accepted_gps.json', None)
    if accepted and accepted['fixture_hash'] != digest(full):
        raise HTTPException(409, 'Source fixture changed; the saved evidence needs fresh review')
    current = Case.model_validate(accepted['case']) if accepted else initial
    return initial, current, accepted


def packet(full: Case, store: Path):
    initial, current, accepted = snapshot(full, store)
    facts = build_fact_table(current)
    # Intake handoff, explicitly not an AI hearing or archived court ruling.
    intake = Ruling(ruling='escalate', recommended_action='Human assessment required',
                    confidence=0, reasoning='Synthetic missing-GPS intake; no AI rehearing performed',
                    cited_facts=[], cited_policy=[], safety_concern='unscreened',
                    evidence_status='insufficient' if not accepted else 'unknown',
                    evidence_gap='GPS interval is missing' if not accepted else 'Human must review the recovered record and safety context',
                    escalate=True, escalation_reason='Reviewer must assess the record')
    rec = CaseRecord(case_id=full.case_id, dispute=current.dispute, trip_summary={},
                     status='escalated', facts=facts, events=[], ruling=intake,
                     eligibility={'auto': False, 'reasons': [intake.evidence_gap]})
    p = review.build_packet(rec, current)
    p.settled = []  # No inherited court safety findings or historic AI amounts.
    p.settled_amount = None
    cert = p._cert
    ids = [f.id for f in facts.facts]
    ready = bool(accepted and not cert.insufficient and len([a for a in cert.allowed if a != 'escalate']) == 1)
    options = []
    if ready:
        outcome = next(a for a in cert.allowed if a != 'escalate')
        options = [review.ReviewOption(id='none', label='The recovered record supports the fee decision; I found no safety concern',
                   detail='Human assessment of GPS and original complaint/messages. Code computes the fee; this is not an AI recommendation.',
                   ruling=outcome, amount=cert.fee if outcome == 'refund_full' else None,
                   flag_account=bool(cert.flag_required), requires_confirmation=bool(cert.flag_required))]
        p.evidence_gap = None
    p.questions = [review.ReviewQuestion(id='safety', kind='safety', subject='case',
                 title='Review the recovered arrival record and the original complaint' if ready else 'Request the missing GPS interval before deciding the fee',
                 why_ai_stopped=['No new AI hearing has been run. A human must assess these records.' if ready else 'Without GPS, arrival and waiting distance cannot be established.'],
                 evidence=review._items(rec, [f.id for f in facts.facts if f.source in ('gps', 'chat', 'fare')], limit=10), options=options, adoptable=False)]
    p.basis = ids
    p.context = []
    p.sides = {}
    p.links = {'policy': '/policy.html'}
    p.status = review.review_status(full.case_id, store)
    decision, req = review.latest(full.case_id, store)
    satisfied = bool(accepted and req and accepted['requested_at'] == req['requested_at'])
    if p.status == 'awaiting_evidence' and satisfied:
        p.status = 'open'
    p.decision = decision
    p.pending_request = req if p.status == 'awaiting_evidence' else None
    return p, current, {'scope': 'synthetic formal-review demonstration',
                        'before_gps_points': len(initial.gps), 'after_gps_points': len(current.gps),
                        'accepted': bool(accepted), 'report': accepted['report'] if accepted else None,
                        'ai_rehearing_performed': False,
                        'last_attempt': read_json(store / 'gps_attempt.json', None)}


def receive(full: Case, store: Path, body: ReceiveGps):
    with LOCK:
        p, current, _ = packet(full, store)
        if p.status == 'decided' or not p.pending_request:
            raise HTTPException(409, 'An open evidence request is required')
        req = p.pending_request
        if body.requested_at != req['requested_at']:
            raise HTTPException(409, 'This response belongs to an older request; reload the case')
        if req['request']['to'] != 'platform' or not any('gps' in i.lower() for i in req['request']['items']):
            raise HTTPException(422, 'This adapter can only fulfil a platform GPS request')
        if body.mode not in ('available', 'unavailable', 'conflict'):
            raise HTTPException(422, 'Unknown response mode')
        if current.gps:
            raise HTTPException(409, 'GPS is already present; this adapter does not replace existing evidence')
        updated, report = recover(current, SyntheticGpsProvider(full, body.mode))
        attempt = {'requested_at': body.requested_at, 'received_at': datetime.now(timezone.utc).isoformat(), 'report': report}
        write_json(store / 'gps_attempt.json', attempt)
        if any(e['kind'] == 'accepted' for e in report['events']):
            write_json(store / 'accepted_gps.json', {**attempt, 'fixture_hash': digest(full), 'case': updated.model_dump(mode='json')})
        refreshed, _, meta = packet(full, store)
        return {'status': refreshed.status, 'recovery': meta, 'decision_recorded': False}
