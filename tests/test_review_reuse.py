"""Offline tests: reuse eliminates one call, not a model accuracy claim."""
import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient
from recovery.evidence import SyntheticGpsProvider
from core.llm import describe_model
from core.receipt import fingerprint
from recovery.review import review_recovered, save_review
from test_recovered_review import fixture, fake_record


def previous_bundle():
    full, partial = fixture()
    async def runner(case, **kwargs):
        record = fake_record(case)
        record.receipt = fingerprint(case, describe_model())
        return record
    return asyncio.run(review_recovered(partial, SyntheticGpsProvider(full, 'available'), runner=runner))


def test_reuse_runs_only_after_and_preserves_original():
    bundle = previous_bundle(); unchanged = copy.deepcopy(bundle)
    full, partial = fixture(); calls = []
    async def runner(case, **kwargs):
        calls.append(case.model_copy(deep=True))
        return fake_record(case)
    result = asyncio.run(review_recovered(partial, SyntheticGpsProvider(full, 'available'),
                        runner=runner, previous_review=bundle))
    assert result['state'] == 'reviewed'
    assert len(calls) == len(result['attempts']) == 1
    assert calls[0].gps and calls[0].case_id.endswith('-v2')
    assert len(result['hearings']) == 2
    assert result['hearings'][0] == bundle['hearings'][0]
    assert result['reused_initial']['review_id'] == bundle['review_id']
    assert bundle == unchanged


@pytest.mark.parametrize('change', ['snapshot', 'policy', 'code', 'model', 'no_receipt', 'context', 'no_hearing', 'record_id'])
def test_invalid_reuse_never_calls_model(change):
    bundle = previous_bundle()
    if change == 'snapshot': bundle['snapshots'][0]['gps'] = [{'ts':'2026-09-22T08:10:00', 'lat':1.3, 'lng':103.8}]
    elif change in {'policy', 'code', 'model'}:
        key = 'model' if change == 'model' else f'{change}_sha256'
        bundle['hearings'][0]['receipt'][key] = 'changed'
    elif change == 'no_receipt': bundle['hearings'][0]['receipt'] = None
    elif change == 'context': bundle['hearing_context']['workflow'] = 'judge_only'
    elif change == 'no_hearing': bundle['hearings'] = []
    elif change == 'record_id': bundle['hearings'][0]['case_id'] = 'wrong'
    full, partial = fixture()
    async def never(*a, **kw): pytest.fail('Rejected reuse must not spend model calls')
    result = asyncio.run(review_recovered(partial, SyntheticGpsProvider(full, 'available'),
                        runner=never, previous_review=bundle))
    assert result['state'] == 'reuse_rejected'
    assert not result['attempts'] and not result['hearings']


def test_can_retry_after_failed_second_hearing():
    bundle = previous_bundle()
    bundle.update(state='review_failed', failure='after hearing timed out')
    bundle['hearings'] = bundle['hearings'][:1]
    full, partial = fixture()
    async def runner(case, **kw): return fake_record(case)
    result = asyncio.run(review_recovered(partial, SyntheticGpsProvider(full, 'available'), runner=runner, previous_review=bundle))
    assert result['state'] == 'reviewed' and len(result['attempts']) == 1


def test_api_reuse_rejects_missing_stale_and_invalid_ids(tmp_path, monkeypatch):
    import app.main as appmod
    monkeypatch.setattr(appmod, 'ROOT', tmp_path)
    monkeypatch.setattr(appmod, 'LIVE_RUNS', True)
    monkeypatch.setattr(appmod, '_check_token', lambda token: None)
    monkeypatch.setattr(appmod, '_rate_ok', lambda ip: True)
    client = TestClient(appmod.app)
    assert client.post('/api/runs/C-0004', json={'recovery':'available', 'reuse_review_id':'../bad'}).status_code == 400
    assert client.post('/api/runs/C-0004', json={'recovery':'available', 'reuse_review_id':'a'*32}).status_code == 404
    bundle = previous_bundle(); bundle['hearing_context']['workflow'] = 'judge_only'
    save_review(bundle, tmp_path/'review_runs')
    assert client.post('/api/runs/C-0004', json={'recovery':'available', 'reuse_review_id':bundle['review_id']}).status_code == 409


def test_api_reuse_calls_only_one_hearing(tmp_path, monkeypatch):
    import app.main as appmod
    monkeypatch.setattr(appmod, 'ROOT', tmp_path)
    monkeypatch.setattr(appmod, 'LIVE_RUNS', True)
    monkeypatch.setattr(appmod, '_check_token', lambda token: None)
    monkeypatch.setattr(appmod, '_rate_ok', lambda ip: True)
    calls = []
    async def runner(case, **kw):
        calls.append(case.case_id)
        return fake_record(case)
    monkeypatch.setattr(appmod, 'run_case', runner)
    bundle = previous_bundle(); save_review(bundle, tmp_path/'review_runs')
    with TestClient(appmod.app) as client:
        response = client.post('/api/runs/C-0004', json={'recovery':'available', 'reuse_review_id':bundle['review_id']})
        assert response.status_code == 200
        import time
        for _ in range(100):
            state = client.get('/api/recovery-reviews/'+response.json()['run_id']).json()
            if state['done']: break
            time.sleep(0.01)
        assert state['review']['state'] == 'reviewed'
        assert len(calls) == 1


def test_reused_bundle_can_be_reused_again_without_losing_origin():
    original = previous_bundle()
    full, partial = fixture()
    async def runner(case, **kw): return fake_record(case)
    second = asyncio.run(review_recovered(partial, SyntheticGpsProvider(full, 'available'), runner=runner, previous_review=original))
    third = asyncio.run(review_recovered(partial, SyntheticGpsProvider(full, 'available'), runner=runner, previous_review=second))
    assert third['state'] == 'reviewed'
    assert third['reused_initial']['review_id'] == original['review_id']
    assert third['reused_initial']['parent_review_id'] == second['review_id']
    assert len(third['attempts']) == 1


@pytest.fixture(autouse=True)
def enable_recovery_test_option(monkeypatch):
    monkeypatch.setenv('RECOVERY_REVIEW_ENABLED', '1')
