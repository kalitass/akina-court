"""Handoff integrity, not model accuracy or measured reviewer time savings."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from recovery.evidence import SyntheticGpsProvider, digest, recover
from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('cid', ['C-0001', 'C-0004'])
def test_packet_citations_resolve_within_each_snapshot(cid):
    full = Case.model_validate_json((ROOT / 'data/cases' / f'{cid}.json').read_text())
    partial = full.model_copy(deep=True)
    partial.gps = []
    original = digest(partial)
    updated, report = recover(partial, SyntheticGpsProvider(full, 'available'))
    packet = report['reviewer_packet']
    assert digest(partial) == original and digest(updated) == packet['fingerprints']['current']
    assert packet['fingerprints']['initial'] == original
    for snapshot in packet['snapshots']:
        ids = {f['id'] for f in snapshot['facts']}
        for p in snapshot['conditions']:
            assert set(p['evidence']) <= ids
        for fact in snapshot['facts']:
            assert f"[{snapshot['version']}:{fact['id']}]" in packet['text']
    assert packet['snapshots'][0]['gps_points'] == 0
    assert packet['complaint'] == partial.dispute.model_dump(mode='json')
    assert partial.dispute.statement in packet['text']
    assert packet['snapshots'][1]['gps_points'] > 0
    assert packet['open_questions']  # Recovery must not erase safety/consent interpretation.
    assert all(p['status'] == 'judge' for p in packet['open_questions'])
    assert all(c['current']['subject'] == 'case' and
               (c['initial'] is None or c['initial']['subject'] == 'case')
               for c in packet['changed_conditions'])
    assert 'ruling' not in packet and 'actions' not in packet
    if cid == 'C-0004':
        arrival = next(c for c in packet['changed_conditions']
                       if c['clause'] == 'NS-1' and '(ii)' in c['element'])
        assert arrival['initial'] is None and arrival['current']['status'] == 'fail'
        assert '613 m' in arrival['current']['detail']


@pytest.mark.parametrize('mode', ['unavailable', 'conflict'])
def test_blocked_packet_does_not_promote_rejected_evidence(mode):
    full = Case.model_validate_json((ROOT / 'data/cases/C-0004.json').read_text())
    partial = full.model_copy(deep=True); partial.gps = []
    _, report = recover(partial, SyntheticGpsProvider(full, mode))
    packet = report['reviewer_packet']
    assert packet['status'] == 'human_review'
    assert packet['source'] is None
    assert packet['fingerprints']['initial'] == packet['fingerprints']['current']
    assert packet['changed_conditions'] == []
    assert packet['investigation_task'] == packet['next_step'] == report['human_task']
    assert all(s['gps_points'] == 0 for s in packet['snapshots'])


def test_api_handoff_is_available_without_model_calls():
    response = TestClient(app).get('/api/evidence-demo/C-0004')
    assert response.status_code == 200
    data = response.json()
    assert data['model_called'] is False
    packet = data['report']['reviewer_packet']
    assert packet['case_id'] == 'C-0004' and 'Synthetic' in packet['limits'][0]
    assert 'No model call' in packet['text']
