"""Reviewer integration integrity; no model-quality or operational savings claims."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.evidence import SyntheticGpsProvider, recover
from core.recovery_handoffs import list_handoffs
from core.review import save_review
from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]


def bundle(mode='available', cid='C-0004', rid='a' * 32):
    full = Case.model_validate_json((ROOT / 'data/cases' / f'{cid}.json').read_text())
    initial = full.model_copy(deep=True); initial.gps = []
    current, evidence = recover(initial, SyntheticGpsProvider(full, mode))
    snapshots = [initial.model_dump(mode='json')]
    if evidence['state'] == 'ready_for_court':
        snapshots.append(current.model_dump(mode='json'))
    return {'review_id': rid, 'source_case_id': cid, 'state': evidence['state'],
            'snapshots': snapshots, 'evidence': evidence, 'failure': None}


@pytest.mark.parametrize('mode', ['available', 'unavailable', 'conflict'])
def test_packet_bridge_preserves_source_and_blocked_tasks(tmp_path, mode):
    original = bundle(mode)
    path = save_review(original, tmp_path)
    content = path.read_bytes()
    response = list_handoffs('C-0004', tmp_path)
    item, = response['items']
    assert item['packet'] == original['evidence']['reviewer_packet']
    assert item['queue_resolution'] == 'unchanged'
    assert path.read_bytes() == content
    if mode != 'available':
        assert item['packet']['source'] is None
        assert item['packet']['investigation_task']


def test_failed_court_does_not_hide_packet_or_look_successful(tmp_path):
    record = bundle(); record.update(state='review_failed', failure='Driver unavailable')
    save_review(record, tmp_path)
    item, = list_handoffs('C-0004', tmp_path)['items']
    assert item['review_state'] == 'review_failed'
    assert item['evidence_state'] == 'ready_for_court'
    assert item['packet']['snapshots'][1]['gps_points'] > 0
    assert item['next_step'].startswith('The AI review failed.')


@pytest.mark.parametrize('damage', ['hash', 'packet', 'identity'])
def test_invalid_record_is_omitted_not_presented_as_verified(tmp_path, damage):
    record = bundle()
    if damage == 'hash':
        record['evidence']['after_hash'] = 'wrong'
    elif damage == 'packet':
        record['evidence']['reviewer_packet']['next_step'] = 'Execute a refund now'
    else:
        record['snapshots'][1]['case_id'] = 'C-0001'
    save_review(record, tmp_path)
    response = list_handoffs('C-0004', tmp_path)
    assert response['items'] == [] and response['skipped_records'] == 1


def test_case_isolation_and_corrupt_files(tmp_path):
    save_review(bundle(cid='C-0001'), tmp_path)
    (tmp_path / ('b' * 32 + '.json')).write_text('{')
    (tmp_path / ('c' * 32 + '.json')).write_text('[]')
    result = list_handoffs('C-0004', tmp_path)
    assert result['items'] == [] and result['skipped_records'] == 2


def test_api_requires_token_and_does_not_modify_queue(monkeypatch, tmp_path):
    import app.main as server
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    monkeypatch.setenv('DEMO_TOKEN', 'test-only-token')
    save_review(bundle('conflict'), tmp_path / 'review_runs')
    runs = tmp_path / 'runs'; runs.mkdir()
    queue = runs / 'queue.json'; queue.write_text('[]')
    with TestClient(server.app) as client:
        url = '/api/queue/C-0004/evidence-handoffs'
        assert client.get(url).status_code == 401
        response = client.get(url, headers={'X-Demo-Token': 'test-only-token'})
        assert response.status_code == 200 and len(response.json()['items']) == 1
        assert client.get('/api/queue/C-0006/evidence-handoffs',
                          headers={'X-Demo-Token': 'test-only-token'}).status_code == 400
    assert queue.read_text() == '[]'
