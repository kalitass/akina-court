"""Source-linked recovery handoff. No model judgement or action execution."""
from dataclasses import asdict

from core.facts.tools import build_fact_table
from core.policy_engine import evaluate
from core.schemas import Case


def build_packet(initial: Case, current: Case, report: dict) -> dict:
    tables = [build_fact_table(case) for case in (initial, current)]
    certs = [evaluate(case, table) for case, table in zip((initial, current), tables)]
    snapshots = []
    for version, case, table, cert in zip(('initial', 'current'), (initial, current), tables, certs):
        snapshots.append({
            'version': version, 'gps_points': len(case.gps),
            'facts': [f.model_dump(mode='json') for f in table.facts],
            'conditions': [asdict(p) for p in cert.predicates],
            'evidence_gap': cert.insufficient,
            'permitted_outcomes': cert.allowed,
        })
    # Only whole-case predicates can be paired by identity. Segment fact IDs
    # are local to a snapshot and may shift after recovery; never pair by F-id.
    before = {(p.clause, p.element): p for p in certs[0].predicates if p.subject == 'case'}
    changed = []
    for p in certs[1].predicates:
        old = before.get((p.clause, p.element)) if p.subject == 'case' else None
        introduced = p.subject == 'case' and old is None and p.status in ('pass', 'fail')
        if introduced or (old is not None and (old.status, old.detail) != (p.status, p.detail)):
            changed.append({'clause': p.clause, 'element': p.element,
                            'initial': asdict(old) if old else None, 'current': asdict(p)})
    questions = [asdict(p) for p in certs[1].predicates if p.status == 'judge']
    packet = {
        'case_id': initial.case_id, 'trip_id': initial.trip.trip_id,
        'complaint': initial.dispute.model_dump(mode='json'),
        'status': report['state'], 'source': report.get('source'),
        'request': report.get('request'),
        'fingerprints': {'initial': report['before_hash'], 'current': report['after_hash']},
        'snapshots': snapshots, 'changed_conditions': changed,
        'open_questions': questions, 'investigation_task': report.get('human_task'),
        'next_step': ('Review the remaining interpretation questions against the current facts. '
                      'Validated GPS alone does not approve a ruling.'
                      if report['state'] == 'ready_for_court' else report.get('human_task') or
                      'No supported recovery request. Review the original case.'),
        'limits': ['Synthetic trip-record service; no real Ryde API is connected.',
                   'Fact IDs are local to each snapshot. Use the snapshot label with every reference.',
                   'Permitted outcomes are policy constraints, not a final decision.',
                   'No model call, payment or account action is performed by this packet.'],
    }
    packet['text'] = packet_text(packet)
    return packet


def packet_text(packet: dict) -> str:
    lines = [f"Evidence handoff: {packet['case_id']} / {packet['trip_id']}",
             f"Status: {packet['status']}", f"Source: {packet['source'] or 'No accepted source'}"]
    complaint = packet['complaint']
    lines += [f"Complaint by {complaint['filed_by']} at {complaint['filed_at']}:", complaint['statement']]
    request = packet['request']
    if request:
        lines += [f"Requested interval: {request['start']} to {request['end']}",
                  f"Reason: {request['reason']}"]
    for snapshot in packet['snapshots']:
        label = snapshot['version']
        lines += ['', f"{label.upper()} SNAPSHOT: {snapshot['gps_points']} GPS points",
                  f"Fingerprint: {packet['fingerprints'][label]}",
                  f"Evidence gap: {snapshot['evidence_gap'] or 'No gap detected by the policy assessment'}",
                  'Facts:']
        lines += [f"[{label}:{f['id']}] [{f['source']}] {f['text']}" for f in snapshot['facts']]
    lines += ['', 'CHANGED WHOLE-CASE CONDITIONS']
    for c in packet['changed_conditions']:
        old = c['initial']
        lines += [f"{c['clause']} {c['element']}",
                  f"Initial: {old['status']} — {old['detail']}" if old else
                  'Initial: not assessed as this condition in the initial certificate.',
                  f"Current: {c['current']['status']} — {c['current']['detail']}"]
    if not packet['changed_conditions']:
        lines.append('No paired whole-case condition changed. Segment conditions remain snapshot-specific.')
    lines += ['', 'OPEN INTERPRETATION QUESTIONS']
    for p in packet['open_questions']:
        lines.append(f"{p['clause']} {p['element']} [{p['subject']}]: {p['detail']} "
                     f"(current facts: {', '.join(p['evidence']) or 'No cited fact'})")
    if not packet['open_questions']:
        lines.append('No open interpretation predicate; this packet still contains no final ruling.')
    lines += ['', 'NEXT STEP', packet['next_step'], '', 'LIMITS', *packet['limits']]
    return '\n'.join(lines)
