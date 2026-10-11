"""Source fidelity and persisted reviewer workflows, not model or usability scores."""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.reviewer import ReviewerAction, current_evidence, decision_preview, history, record_action, workspace
from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]


def test_integrated_team_queue_loads_every_reviewable_case_without_writes(monkeypatch, tmp_path):
    import app.main as server
    import app.review as review
    import app.review_api as api
    monkeypatch.setattr(api, 'RUNS_DIR', tmp_path)
    before = {p.name: p.read_bytes() for p in (ROOT / 'runs').glob('*.json')}
    with TestClient(server.app) as client:
        response = client.get('/api/review')
        assert response.status_code == 200
        ids = {item['case_id'] for item in response.json()}
        assert ids and ids == set(review.ops_queue_ids())
        for cid in ids:
            packet = client.get('/api/review/' + cid)
            assert packet.status_code == 200
            assert packet.json()['case_id'] == cid and packet.json()['questions']
        assert client.get('/api/review/C-0004').status_code == 409
    assert not list(tmp_path.iterdir())
    assert before == {p.name: p.read_bytes() for p in (ROOT / 'runs').glob('*.json')}


def case(cid='C-0004'):
    return Case.model_validate_json((ROOT / 'data/cases' / (cid + '.json')).read_text())


def test_team_evidence_request_keeps_case_open_and_requires_confirmation(monkeypatch, tmp_path):
    import app.main as server
    import app.review_api as api
    monkeypatch.setattr(api, 'RUNS_DIR', tmp_path)
    monkeypatch.setenv('DEMO_TOKEN', 'test-token')
    headers = {'X-Demo-Token': 'test-token'}
    body = {'outcome': 'request_evidence', 'reviewer': 'Integration test',
            'request': {'to': 'platform', 'items': ['Authoritative road mapping for segment F3'],
                        'due_in_hours': 12, 'on_timeout': 'decide_on_record'}}
    with TestClient(server.app) as client:
        assert client.post('/api/review/B-0054', json=body).status_code == 401
        assert client.post('/api/review/B-0054', headers=headers, json=body).status_code == 422
        assert not list(tmp_path.iterdir())
        body['checked'] = True
        saved = client.post('/api/review/B-0054', headers=headers, json=body)
        assert saved.status_code == 200
        assert saved.json()['status'] == 'awaiting_evidence'
        assert saved.json()['queue_item']['status'] == 'open'
        refreshed = client.get('/api/review/B-0054').json()
        assert refreshed['status'] == 'awaiting_evidence' and refreshed['decision'] is None
        assert refreshed['pending_request']['request']['items'] == body['request']['items']
        assert not (tmp_path / 'overrides.json').exists()


def action(packet, **kw):
    return ReviewerAction(request_id=uuid4(), source_fingerprint=packet['source_fingerprint'],
                          revision=packet.get('revision', 0), reviewer='Reviewer A',
                          reason='Reviewed the original source evidence.', **kw)


def test_route_branches_and_citations_are_from_actual_record():
    c = Case.model_validate_json((ROOT / 'data/bench/cases/B-0054.json').read_text())
    record = json.loads((ROOT / 'bench/results/court/B-0054.record.json').read_text())
    p = workspace(c, record)
    q, = p['questions']
    assert q['id'] == 'F3' and {o['value'] for o in q['options']} == {'exempt', 'counts', 'undetermined'}
    ids = {f['id'] for f in p['facts']}
    assert set(q['evidence_ids']) <= ids
    assert p['complaint'] == c.dispute.model_dump(mode='json')
    for reading in q['readings']:
        brief = record['briefs'][reading['party']]
        assert all(claim in brief['claims'] and not claim.get('void') for claim in reading['claims'])
    assert not p['can_accept_ai']  # This stored court escalated; no invented settled option.


def test_stale_receipt_cannot_be_accepted():
    c = case()
    record = json.loads((ROOT / 'runs/C-0004.json').read_text())
    record['receipt']['code_sha256'] = 'changed'
    p = workspace(c, record)
    assert not p['can_accept_ai']
    with pytest.raises(ValueError, match='no settled'):
        decision_preview(c, p, action(p, action='accept_ai'))


@pytest.mark.parametrize('mode', ['available', 'unavailable', 'conflict'])
def test_request_persists_and_only_validated_gps_is_promoted(tmp_path, mode):
    full = case(); initial = full.model_copy(deep=True); initial.gps = []
    p = workspace(initial, None, 'missing_gps')
    a = action(p, action='request_evidence', response_mode=mode)
    result = record_action(initial, full, p, a, tmp_path)
    assert result['sla_queue_changed'] is False and result['execution'] == 'simulation_only'
    entries = history(full.case_id, 'missing_gps', tmp_path)
    restored = current_evidence(initial, entries)
    assert bool(restored.gps) == (mode == 'available')
    assert initial.gps == [] and full.gps
    assert record_action(initial, full, p, a, tmp_path) == result  # Idempotent retry.
    assert len(history(full.case_id, 'missing_gps', tmp_path)) == 1


def test_old_revision_and_changed_request_payload_rejected(tmp_path):
    c = case(); p = workspace(c, None)
    a = action(p, action='request_evidence', evidence_kind='chat')
    record_action(c, c, p, a, tmp_path)
    with pytest.raises(ValueError, match='changed'):
        record_action(c, c, p, action(p, action='request_evidence'), tmp_path)
    with pytest.raises(ValueError, match='Request ID'):
        record_action(c, c, p, a.model_copy(update={'reason': 'Different justification for the same ID.'}), tmp_path)


def test_request_id_is_bound_to_case(tmp_path):
    c = case(); p = workspace(c, None)
    a = action(p, action='request_evidence', evidence_kind='chat')
    record_action(c, c, p, a, tmp_path)
    other = case('C-0001')
    with pytest.raises(ValueError, match='Request ID'):
        record_action(other, other, workspace(other, None), a, tmp_path)


def test_preview_calculates_from_human_findings_without_writes():
    c = case('C-0001'); p = workspace(c, None)
    choices = {q['id']: 'counts' for q in p['questions']}
    result = decision_preview(c, p, action(p, action='own_decision', choices=choices, outcome='refund_partial'))
    assert result['amount'] == 4.05
    with pytest.raises(ValueError, match='contradicts'):
        decision_preview(c, p, action(p, action='own_decision', choices=choices, outcome='no_action'))
    with pytest.raises(ValueError, match='Entered amount'):
        decision_preview(c, p, action(p, action='own_decision', choices=choices, outcome='refund_partial', amount=999))


def test_unsettled_branches_cannot_be_closed_as_refund():
    c = case('C-0001'); p = workspace(c, None)
    with pytest.raises(ValueError, match='every open'):
        decision_preview(c, p, action(p, action='own_decision', outcome='refund_partial'))
    choices = {q['id']: 'undetermined' for q in p['questions']}
    result = decision_preview(c, p, action(p, action='own_decision', outcome='escalate', choices=choices))
    assert result['amount'] is None


def test_missing_evidence_and_safety_do_not_become_settled_human_demo():
    c = case(); c.gps = []; p = workspace(c, None)
    with pytest.raises(ValueError):
        decision_preview(c, p, action(p, action='own_decision', outcome='refund_full'))
    s = case('C-0006'); p = workspace(s, None)
    assert p['safety']
    assert decision_preview(s, p, action(p, action='own_decision', outcome='escalate'))['ruling'] == 'escalate'


def test_tampered_evidence_is_not_reused(tmp_path):
    full = case(); c = full.model_copy(deep=True); c.gps = []
    p = workspace(c, None, 'missing_gps')
    r = record_action(c, full, p, action(p, action='request_evidence'), tmp_path)
    r['recovery']['snapshots'][1]['gps'][0]['lat'] += .01
    with pytest.raises(ValueError, match='no longer matches'):
        current_evidence(c, [r])


@pytest.mark.parametrize('amount', [float('nan'), float('inf'), -1])
def test_invalid_amount_rejected(amount):
    with pytest.raises(ValidationError):
        action(workspace(case(), None), action='own_decision', outcome='refund_full', amount=amount)


def test_api_end_to_end_recovery_then_human_assessment(monkeypatch, tmp_path):
    import app.main as server
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    monkeypatch.setenv('DEMO_TOKEN', 'test-token')
    original = (ROOT / 'runs/C-0004.json').read_bytes()
    headers = {'X-Demo-Token': 'test-token'}
    url = '/api/reviewer/C-0004?scenario=missing_gps'
    with TestClient(server.app) as client:
        assert client.get(url).status_code == 401
        initial = client.get(url, headers=headers).json()
        assert initial['comparison']['before']['gps_samples'] == 0
        assert initial['comparison']['before']['allowed_outcomes'] == ['escalate']
        assert not initial['comparison']['evidence_changed']
        req = action(initial, action='request_evidence').model_dump(mode='json')
        saved = client.post('/api/reviewer/C-0004/actions?scenario=missing_gps', headers=headers, json=req)
        assert saved.status_code == 200
        current = client.get(url, headers=headers).json()
        assert current['evidence_recovered'] and current['revision'] == 1 and not current['evidence_gap']
        comparison = current['comparison']
        assert comparison['evidence_changed'] and comparison['accepted_source']
        assert comparison['after']['gps_samples'] > 0 and comparison['after']['location_facts']
        assert comparison['before']['snapshot_hash'] != comparison['after']['snapshot_hash']
        assert not comparison['ai_rehearing_performed'] and comparison['human_assessment'] is None
        # A browser retry after GPS promotion is idempotent.
        assert client.post('/api/reviewer/C-0004/actions?scenario=missing_gps', headers=headers, json=req).json() == saved.json()
        own = action(current, action='own_decision', outcome='refund_full').model_dump(mode='json')
        preview = client.post('/api/reviewer/C-0004/preview?scenario=missing_gps', headers=headers, json=own)
        assert preview.json()['decision']['amount'] == 6.61 and not preview.json()['saved']
        result = client.post('/api/reviewer/C-0004/actions?scenario=missing_gps', headers=headers, json=own)
        assert result.status_code == 200 and result.json()['status'] == 'human_decision_recorded'
        reloaded = client.get(url, headers=headers).json()
        assert reloaded['revision'] == 2 and reloaded['history'][-1]['decision']['amount'] == 6.61
        assert reloaded['comparison']['human_assessment']['decision']['amount'] == 6.61
        assert not result.json()['sla_queue_changed']
    assert (ROOT / 'runs/C-0004.json').read_bytes() == original


def test_api_rejects_cross_case_scenario_and_stale_source(monkeypatch, tmp_path):
    import app.main as server
    monkeypatch.setattr(server, 'ROOT', tmp_path); monkeypatch.setenv('DEMO_TOKEN', 'test-token')
    headers = {'X-Demo-Token': 'test-token'}
    with TestClient(server.app) as client:
        assert client.get('/api/reviewer/B-0054?scenario=missing_gps', headers=headers).status_code == 400
        p = client.get('/api/reviewer/C-0004', headers=headers).json()
        req = action(p, action='request_evidence').model_dump(mode='json'); req['source_fingerprint'] = '0' * 64
        assert client.post('/api/reviewer/C-0004/actions', headers=headers, json=req).status_code == 409


def test_changed_fact_ids_do_not_borrow_old_advocate_readings():
    c = case('C-0001')
    record = json.loads((ROOT / 'runs/C-0001.json').read_text())
    record['facts']['facts'][0]['text'] = 'Edited source fact'
    p = workspace(c, record)
    assert not p['record_facts_match'] and not p['can_accept_ai']
    assert all(not r['claims'] and r['ground'] is None for q in p['questions'] for r in q['readings'])
