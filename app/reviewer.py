"""Source-linked reviewer workspace and simulated human actions; no court writes."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from core.facts.tools import build_fact_table
from core.policy_engine import evaluate, expected_amount
from core.receipt import policy_hash, verify
from core.llm import describe_model
from core.schemas import Case
from recovery.evidence import SyntheticGpsProvider, digest, recover
from recovery.review import recovery_code_hash


class ReviewerAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    source_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    revision: int = Field(ge=0)
    action: Literal['accept_ai', 'own_decision', 'request_evidence']
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=4000)
    choices: dict[str, Literal['exempt', 'counts', 'undetermined']] = Field(default_factory=dict)
    outcome: Literal['no_action', 'refund_partial', 'refund_full', 'escalate'] | None = None
    amount: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    evidence_kind: Literal['gps', 'chat', 'other'] = 'gps'
    response_mode: Literal['available', 'unavailable', 'conflict'] = 'available'


def workspace(case: Case, record: dict | None, scenario='stored') -> dict:
    table = build_fact_table(case)
    cert = evaluate(case, table)
    facts = {f.id: f.model_dump(mode='json') for f in table.facts}
    record_facts_match = bool(record and record.get('facts') == table.model_dump(mode='json'))
    readings_record = record if record_facts_match else None
    questions = []
    for fid, segment in cert.segments.items():
        if segment['exempt'] is not None:
            continue
        predicates = [p for p in cert.predicates if p.subject == fid and p.status == 'judge']
        evidence_ids = list(dict.fromkeys([fid] + [i for p in predicates for i in p.evidence]))
        readings = []
        for party in ('rider', 'driver'):
            brief = ((readings_record or {}).get('briefs') or {}).get(party) or {}
            rebuttal = ((readings_record or {}).get('rebuttals') or {}).get(party) or {}
            ground = (rebuttal.get('segment_grounds') or {}).get(fid) or (brief.get('segment_grounds') or {}).get(fid)
            claims = [c for c in brief.get('claims', []) if not c.get('void') and fid in c.get('facts', [])]
            readings.append({'party': party, 'ground': ground, 'claims': claims})
        questions.append({'id': fid, 'title': f'Does the recorded agreement cover segment {fid}?',
                          'segment': segment, 'policy': [asdict(p) for p in predicates],
                          'evidence_ids': [i for i in evidence_ids if i in facts],
                          'readings': readings,
                          'options': [
                              {'value': 'exempt', 'label': 'The evidence establishes an applicable exemption',
                               'consequence': 'Exclude this segment from the refund calculation.'},
                              {'value': 'counts', 'label': 'The evidence establishes that this segment is not exempt',
                               'consequence': 'Include this segment in the policy calculation; fixed-fare rules still apply.'},
                              {'value': 'undetermined', 'label': 'The available evidence does not settle this',
                               'consequence': 'Keep the case open and request evidence or further human investigation.'}],
                          'scope': 'Conditional policy branches for human assessment, not AI conclusions'})
    other = [asdict(p) for p in cert.predicates if p.status == 'judge' and p.subject == 'case']
    ruling = (record or {}).get('ruling')
    receipt = verify((record or {}).get('receipt'), case, describe_model()) if record else None
    material = {'case': case.model_dump(mode='json'), 'record': record, 'policy': policy_hash(),
                'recovery': recovery_code_hash(), 'adapter': sha256(Path(__file__).read_bytes()).hexdigest(),
                'scenario': scenario}
    fingerprint = sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'schema_version': 1, 'case_id': case.case_id, 'scenario': scenario,
            'source_fingerprint': fingerprint, 'complaint': case.dispute.model_dump(mode='json'),
            'route': {'pickup': case.trip.pickup.model_dump(mode='json'),
                      'dropoff': case.trip.dropoff.model_dump(mode='json'),
                      'replay_url': f'/replay.html?case={case.case_id}'},
            'facts': list(facts.values()), 'questions': questions, 'other_questions': other,
            'evidence_gap': cert.insufficient,
            'allowed_outcomes': cert.allowed, 'amount_formula': cert.amount_formula,
            'ai_ruling': ruling, 'eligibility': (record or {}).get('eligibility'),
            'court_url': f'/replay.html?case={case.case_id}&phase=court',
            'receipt_url': f'/api/runs/{case.case_id}/receipt' if record else None,
            'receipt_check': receipt, 'record_facts_match': record_facts_match,
            'can_accept_ai': bool(record_facts_match and receipt and receipt['verified'] and ruling and ruling.get('ruling') != 'escalate' and not ruling.get('escalate') and not cert.insufficient),
            'safety': case.dispute.type == 'safety' or bool(ruling and ruling.get('safety_concern') in ('suspected', 'confirmed')),
            'limits': ['Synthetic demonstration; human identity is self-declared, not authenticated.',
                       'Conditional branches are not proof of either reading. Review original evidence.',
                       'Actions are recorded in a separate reviewer ledger, not the live SLA queue.',
                       'No payment, punishment, model call or benchmark modification.']}


def decision_preview(case, packet, action):
    cert = evaluate(case, build_fact_table(case))
    open_ids = {q['id'] for q in packet['questions']}
    if set(action.choices) - open_ids:
        raise ValueError('Choice refers to a segment that is not open in this snapshot')
    if action.action == 'accept_ai':
        if not packet['can_accept_ai'] or packet['safety']:
            raise ValueError('This case has no settled AI decision to accept; record your own assessment or request evidence')
        ruling = packet['ai_ruling']
        return {'ruling': ruling['ruling'], 'amount': ruling.get('amount'),
                'basis': 'Human confirms the displayed stored AI recommendation',
                'account_action': 'human_review_only' if ruling.get('flag_account') else 'none'}
    if action.action != 'own_decision':
        return None
    if not action.outcome:
        raise ValueError('A human outcome is required')
    if action.outcome not in cert.allowed:
        raise ValueError('Selected outcome is outside the current policy constraints; request evidence or keep investigating')
    if action.outcome != 'escalate':
        if packet['safety'] or cert.insufficient:
            raise ValueError('Safety or missing evidence requires further human investigation in this demonstration')
        if set(action.choices) != open_ids or 'undetermined' in action.choices.values():
            raise ValueError('Assess every open segment or keep the case unresolved')
    amount = None
    if action.outcome != 'escalate' and case.dispute.type == 'route_deviation':
        calculated = expected_amount(cert, {k: v == 'exempt' for k, v in action.choices.items()})
        if cert.rate_per_km is not None:
            expected_outcome = 'refund_partial' if calculated and calculated > 0 else 'no_action'
            if action.outcome != expected_outcome:
                raise ValueError('Outcome contradicts the selected segment findings')
            amount = calculated if expected_outcome == 'refund_partial' else None
    elif action.outcome == 'refund_full':
        amount = cert.fee
    if action.amount is not None and (amount is None or abs(action.amount - amount) > .010000001):
        raise ValueError('Entered amount does not match the policy calculation')
    if action.outcome in ('refund_partial', 'refund_full') and amount is None:
        raise ValueError('No supported refund calculation is available')
    return {'ruling': action.outcome, 'amount': amount,
            'basis': 'Human choices with unchanged deterministic policy calculation',
            'account_action': 'human_review_only' if cert.flag_required or cert.flag_conditional else 'none'}


def connect(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'actions.sqlite', timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS actions (request_id TEXT PRIMARY KEY, case_id TEXT, scenario TEXT, revision INTEGER, payload TEXT, result TEXT, UNIQUE(case_id, scenario, revision))')
    return db


def history(case_id, scenario, directory):
    with closing(connect(directory)) as db:
        rows = db.execute('SELECT result FROM actions WHERE case_id=? AND scenario=? ORDER BY revision', (case_id, scenario)).fetchall()
    return [json.loads(row[0]) for row in rows]


def record_action(case, full_case, packet, action: ReviewerAction, directory: Path):
    if not action.reviewer.strip() or len(action.reason.strip()) < 10:
        raise ValueError('Reviewer name and a meaningful reason are required')
    payload = action.model_dump_json()
    db = connect(directory)
    try:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT payload, result FROM actions WHERE request_id=?', (str(action.request_id),)).fetchone()
        if previous:
            saved = json.loads(previous[1])
            if previous[0] != payload or saved['case_id'] != case.case_id or saved['scenario'] != packet['scenario']:
                raise ValueError('Request ID already belongs to a different action')
            return json.loads(previous[1])
        revision = db.execute('SELECT COALESCE(MAX(revision),0) FROM actions WHERE case_id=? AND scenario=?', (case.case_id, packet['scenario'])).fetchone()[0]
        if action.revision != revision or action.source_fingerprint != packet['source_fingerprint']:
            raise ValueError('Workspace changed; reload before recording an action')
        result = {'action_id': uuid4().hex, 'case_id': case.case_id, 'scenario': packet['scenario'],
                  'revision': revision + 1, 'action': action.action, 'reviewer': action.reviewer.strip(),
                  'reason': action.reason.strip(), 'choices': action.choices,
                  'recorded_at': datetime.now(timezone.utc).isoformat(),
                  'source_fingerprint': packet['source_fingerprint'], 'execution': 'simulation_only',
                  'sla_queue_changed': False, 'decision': decision_preview(case, packet, action)}
        if action.action == 'request_evidence':
            result.update(status='awaiting_evidence', evidence_kind=action.evidence_kind)
            if action.evidence_kind == 'gps' and not case.gps and case.case_id in {'C-0001', 'C-0004'}:
                updated, report = recover(case, SyntheticGpsProvider(full_case, action.response_mode))
                result.update(status='evidence_received' if report.get('source') else 'awaiting_evidence',
                              recovery={'evidence': report, 'snapshots': [case.model_dump(mode='json'), updated.model_dump(mode='json')]})
            else:
                result['investigation_task'] = 'Manual evidence retrieval requested: ' + action.reason.strip()
        else:
            result['status'] = 'investigating' if result['decision']['ruling'] == 'escalate' else 'human_decision_recorded'
        db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?)', (str(action.request_id), case.case_id, packet['scenario'], revision + 1, payload, json.dumps(result)))
        db.commit()
        return result
    finally:
        db.close()


def current_evidence(initial, entries):
    """Only reuse validated snapshots from this ledger; never promote rejected GPS."""
    current = initial.model_copy(deep=True)
    for entry in entries:
        recovery = entry.get('recovery')
        if not recovery or not recovery['evidence'].get('source'):
            continue
        before, after = [Case.model_validate(s) for s in recovery['snapshots']]
        report = recovery['evidence']
        if digest(before) != digest(current) or digest(after) != report['after_hash'] or digest(before) != report['before_hash']:
            raise ValueError('Saved evidence snapshot no longer matches the current case')
        current = after
    return current
