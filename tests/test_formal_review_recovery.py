"""End-to-end request → validated evidence → human decision in one review case."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app import review_api
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
URL = '/api/review/C-0004?scenario=missing_gps'
HEADERS = {'X-Demo-Token': 'test-token'}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(review_api, 'RUNS_DIR', tmp_path)
    monkeypatch.setenv('DEMO_TOKEN', 'test-token')
    with TestClient(app) as c:
        yield c


def request(client):
    r = client.post(URL, headers=HEADERS, json={'outcome':'request_evidence', 'checked':True,
        'reviewer':'Test reviewer', 'request':{'to':'platform', 'items':['GPS interval with source and timestamps'],
        'due_in_hours':24, 'on_timeout':'decide_on_record'}})
    assert r.status_code == 200, r.text
    assert r.json()['queue_item']['status'] == 'open'
    return r.json()['request']['requested_at']


def receive(client, stamp, mode='available'):
    return client.post('/api/review/C-0004/receive-gps?scenario=missing_gps', headers=HEADERS,
                       json={'requested_at':stamp, 'mode':mode})


def test_same_formal_case_entire_cycle(client, tmp_path):
    originals = {p: p.read_bytes() for folder in ('data/cases', 'runs', 'bench/results/court')
                 for p in (ROOT/folder).glob('*.json')}
    initial = client.get(URL).json()
    assert initial['current_case']['gps'] == []
    assert initial['allowed'] == ['escalate']
    own = {'outcome':'own_judgment', 'checked':True, 'reviewer':'Test reviewer',
           'reason':'I reviewed the original GPS and quoted messages.', 'findings':{'safety':'none'},
           'cited_facts':[initial['basis'][0]], 'confirm_account_action':True}
    assert client.post('/api/review/C-0004/preview?scenario=missing_gps', json=own).status_code == 422
    stamp = request(client)
    assert client.get(URL).json()['status'] == 'awaiting_evidence'
    accepted = receive(client, stamp)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['status'] == 'open' and not accepted.json()['decision_recorded']
    p = client.get(URL).json()
    assert p['case_id'] == initial['case_id']
    assert p['recovery']['after_gps_points'] > 0 and not p['recovery']['ai_rehearing_performed']
    assert p['decision'] is None and p['pending_request'] is None
    assert p['questions'][0]['options'][0]['amount'] == 6.61
    own['cited_facts'] = p['basis']
    preview = client.post('/api/review/C-0004/preview?scenario=missing_gps', json=own)
    assert preview.status_code == 200, preview.text
    assert preview.json()['ruling']['ruling'] == 'refund_full'
    assert preview.json()['formula_amount'] == 6.61
    saved = client.post(URL, headers=HEADERS, json=own)
    assert saved.status_code == 200, saved.text
    assert saved.json()['status'] == 'decided'
    assert client.get(URL).json()['decision']['ruling']['amount'] == 6.61
    from core.stretch.sla import list_queue
    assert list_queue(tmp_path/'review_recovery_demo/C-0004')[0].status == 'resolved'
    assert receive(client, stamp).status_code == 409
    assert all(p.read_bytes() == b for p,b in originals.items())
    assert not (tmp_path/'reviews.json').exists()  # Formal queue's original cases are isolated.


@pytest.mark.parametrize('mode', ['unavailable','conflict'])
def test_failed_response_keeps_same_request_open_and_can_retry(client, mode):
    stamp = request(client)
    r = receive(client, stamp, mode)
    assert r.status_code == 200
    assert r.json()['status'] == 'awaiting_evidence'
    p = client.get(URL).json()
    assert p['current_case']['gps'] == [] and p['decision'] is None
    assert p['pending_request']['requested_at'] == stamp
    assert p['recovery']['last_attempt']['report']['human_task']
    assert receive(client, stamp).json()['status'] == 'open'


def test_wrong_request_auth_and_scope_are_rejected(client):
    assert receive(client, 'no-request').status_code == 409
    stamp = request(client)
    assert receive(client, 'old-request').status_code == 409
    assert client.post('/api/review/C-0004/receive-gps?scenario=missing_gps',json={'requested_at':stamp}).status_code == 401
    assert client.get('/api/review/B-0054?scenario=missing_gps').status_code == 400
    assert client.post('/api/review/B-0054/receive-gps',headers=HEADERS,json={'requested_at':stamp}).status_code == 422
    assert client.get('/api/review/C-0004').status_code == 409


def test_fixture_change_invalidates_saved_recovery(client, monkeypatch):
    stamp = request(client)
    assert receive(client, stamp).status_code == 200
    from app import main
    original = main.load_case
    def changed(cid):
        c = original(cid).model_copy(deep=True)
        c.dispute.statement += ' changed'
        return c
    monkeypatch.setattr(main, 'load_case', changed)
    assert client.get(URL).status_code == 409
