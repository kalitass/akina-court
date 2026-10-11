"""Offline orchestration tests with an explicitly fake court, not model performance tests."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from core.evidence import SyntheticGpsProvider, digest
from core.review import review_recovered, save_review
from core.schemas import Case, CaseRecord

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    full = Case.model_validate_json((ROOT / 'data/cases/C-0004.json').read_text())
    partial = full.model_copy(deep=True); partial.gps = []
    return full, partial


def fake_record(case):
    rec = CaseRecord.load(ROOT / 'runs/C-0004.json').model_copy(deep=True)
    rec.case_id = case.case_id
    if not case.gps:
        rec.ruling = rec.ruling.model_copy(update={'ruling':'escalate','amount':None,'escalate':True,
                         'evidence_status':'insufficient','reasoning':'Missing GPS; human review', 'safety_concern':'none'})
        rec.eligibility = {'auto':False, 'actions':[]}
    else:
        rec.ruling = rec.ruling.model_copy(update={'safety_concern':'none'})
    return rec


def test_two_independent_hearings_and_auditable_comparison(tmp_path):
    full, partial = fixture(); original = digest(partial); seen=[]
    async def runner(case, **kw):
        seen.append(case.model_copy(deep=True)); return fake_record(case)
    result=asyncio.run(review_recovered(partial,SyntheticGpsProvider(full,'available'),runner=runner))
    assert result['state']=='reviewed' and len(result['snapshots'])==len(result['hearings'])==2
    assert not seen[0].gps and seen[1].gps and seen[0].case_id != seen[1].case_id
    assert all('~recovery-' in c.case_id for c in seen)
    assert result['comparison']['changes']['ruling']['before']=='escalate'
    assert result['comparison']['after_reasoning']==result['hearings'][1]['ruling']['reasoning']
    assert digest(partial)==original and not partial.gps
    path=save_review(result,tmp_path)
    assert json.loads(path.read_text())==result
    with pytest.raises(FileExistsError): save_review(result,tmp_path)


@pytest.mark.parametrize('mode',['unavailable','conflict'])
def test_rejected_evidence_never_calls_models(mode):
    full, partial=fixture()
    async def never(*args,**kw): pytest.fail('Must not call court on rejected evidence')
    result=asyncio.run(review_recovered(partial,SyntheticGpsProvider(full,mode),runner=never))
    assert result['state']=='human_review' and not result['hearings']
    assert len(result['snapshots'])==1


@pytest.mark.parametrize('stage',[1,2])
def test_model_failure_is_not_reported_as_a_completed_review(stage):
    full, partial=fixture(); calls=[]
    async def runner(case, **kw):
        calls.append(case)
        if len(calls)==stage: raise RuntimeError('mock model offline')
        return fake_record(case)
    result=asyncio.run(review_recovered(partial,SyntheticGpsProvider(full,'available'),runner=runner))
    assert result['state']=='review_failed' and result['comparison'] is None
    assert len(result['hearings'])==stage-1 and 'offline' in result['failure']


def test_default_unscreened_judge_is_failure():
    full, partial=fixture()
    async def runner(case,**kw):
        r=fake_record(case); r.ruling.safety_concern='unscreened'; return r
    result=asyncio.run(review_recovered(partial,SyntheticGpsProvider(full,'available'),runner=runner))
    assert result['state']=='review_failed' and not result['hearings']


def test_wrong_case_record_rejected():
    full, partial=fixture()
    async def runner(case,**kw):
        r=fake_record(case); r.case_id='wrong'; return r
    result=asyncio.run(review_recovered(partial,SyntheticGpsProvider(full,'available'),runner=runner))
    assert result['state']=='review_failed' and 'does not match' in result['failure']


def test_mutated_input_rejected():
    full, partial=fixture()
    async def runner(case,**kw):
        case.provenance['bad']='mutation'; return fake_record(case)
    result=asyncio.run(review_recovered(partial,SyntheticGpsProvider(full,'available'),runner=runner))
    assert result['state']=='review_failed' and 'mutated' in result['failure']


def test_api_recovery_preserves_original_and_persists_separate_bundle(monkeypatch,tmp_path):
    import app.main as server
    monkeypatch.setattr(server,'LIVE_RUNS',True)
    monkeypatch.setattr(server,'_check_token',lambda token:None)
    monkeypatch.setattr(server,'_rate_ok',lambda ip:True)
    monkeypatch.setattr(server,'ROOT',tmp_path)
    async def runner(case,**kw): return fake_record(case)
    monkeypatch.setattr(server,'run_case',runner)
    original=(ROOT/'runs/C-0004.json').read_bytes()
    with TestClient(server.app) as client:
        res=client.post('/api/runs/C-0004',json={'recovery':'available'})
        assert res.status_code==200
        rid=res.json()['run_id']
        for _ in range(30):
            state=client.get('/api/recovery-reviews/'+rid).json()
            if state['done']: break
        assert state['done'] and state['review']['state']=='reviewed'
        server.RUNS.pop(rid, None)
        assert client.get('/api/recovery-reviews/'+rid).json() == state
        assert client.post('/api/runs/DISP-002',json={'recovery':'available'}).status_code==400
        assert client.post('/api/runs/C-0004',json={'recovery':'available','inject':['fake_fact']}).status_code==400
    assert list((tmp_path/'review_runs').glob('*.json'))
    assert (ROOT/'runs/C-0004.json').read_bytes()==original
    server.RUNS.pop(rid,None)


def test_recovery_obeys_live_switch(monkeypatch):
    import app.main as server
    monkeypatch.setattr(server,'LIVE_RUNS',False)
    monkeypatch.setattr(server,'_check_token',lambda token:None)
    with TestClient(server.app) as client:
        assert client.post('/api/runs/C-0004',json={'recovery':'available'}).status_code==403


def test_recovery_obeys_token_and_rate_limit(monkeypatch):
    import app.main as server
    monkeypatch.setattr(server,'LIVE_RUNS',True)
    monkeypatch.setenv('DEMO_TOKEN','test-only-token')
    with TestClient(server.app) as client:
        assert client.post('/api/runs/C-0004',json={'recovery':'available'}).status_code==401
        monkeypatch.setattr(server,'_rate_ok',lambda ip:False)
        assert client.post('/api/runs/C-0004',json={'recovery':'available'},headers={'X-Demo-Token':'test-only-token'}).status_code==429


def test_recovery_controls_do_not_claim_model_readiness_without_key(monkeypatch):
    import app.main as server
    monkeypatch.setenv('LLM_PROVIDER','deepseek')
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    with TestClient(server.app) as client:
        assert not client.get('/api/demo-controls').json()['recovery_model_ready']


def test_experiment_does_not_count_handoff_as_automatic_success():
    from scripts.review_recovery import score_decision
    result=score_decision({'ruling':{'ruling':'escalate','amount':None,'escalate':True},'eligibility':{'auto':False}},
                         {'ruling':'escalate','amount':None,'escalate':True})
    assert result['strict_match'] and not result['automatic_and_correct']


def test_experiment_counts_incorrect_automatic_decision():
    from scripts.review_recovery import score_decision
    result=score_decision({'ruling':{'ruling':'refund_full','amount':6.61,'escalate':False},'eligibility':{'auto':True}},
                         {'ruling':'no_action','amount':None,'escalate':False})
    assert result['wrong_automatic'] and not result['automatic_and_correct']
