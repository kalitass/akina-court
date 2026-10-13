from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.evidence import EvidenceResponse, SyntheticGpsProvider, digest, plan, recover
from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]


def fixture(cid='C-0004'):
    return Case.model_validate_json((ROOT / 'data/cases' / f'{cid}.json').read_text())


@pytest.mark.parametrize('cid', ['C-0004', 'C-0001'])
def test_recovery_recomputes_policy_without_mutating_case(cid):
    full = fixture(cid)
    partial = full.model_copy(deep=True); partial.gps = []
    original = digest(partial)
    updated, result = recover(partial, SyntheticGpsProvider(full, 'available'))
    assert result['state'] == 'ready_for_court'
    assert result['version'] == 2
    assert updated.gps and 'escalate' in result['allowed_after']
    assert digest(partial) == original and not partial.gps
    assert result['before_hash'] != result['after_hash']
    assert updated.provenance['recovered_gps'].startswith('synthetic')


@pytest.mark.parametrize('mode', ['unavailable', 'conflict'])
def test_failed_retrieval_preserves_snapshot_and_provides_task(mode):
    full = fixture(); partial = full.model_copy(deep=True); partial.gps = []
    updated, result = recover(partial, SyntheticGpsProvider(full, mode))
    assert result['state'] == 'human_review' and result['human_task']
    assert digest(updated) == digest(partial)
    assert result['version'] == 1


def test_wrong_trip_never_becomes_evidence():
    full = fixture(); partial = full.model_copy(deep=True); partial.gps = []
    class WrongTrip:
        def fetch(self, request):
            return EvidenceResponse(request_id=request.request_id, trip_id='other-trip', source='fixture',
                                    status='available', points=full.gps)
    updated, result = recover(partial, WrongTrip())
    assert result['state'] == 'human_review' and not updated.gps
    assert 'different' in result['human_task']


@pytest.mark.parametrize('change', ['truncate', 'reverse', 'invalid_coordinate', 'no_source'])
def test_invalid_telemetry_is_blocked(change):
    full = fixture(); partial = full.model_copy(deep=True); partial.gps = []
    class Invalid:
        def fetch(self, request):
            points = [p.model_copy(deep=True) for p in full.gps]
            source = 'fixture'
            if change == 'truncate': points = points[2:]
            if change == 'reverse': points.reverse()
            if change == 'invalid_coordinate': points[0].lat = 100
            if change == 'no_source': source = ''
            return EvidenceResponse(request_id=request.request_id, trip_id=request.trip_id,
                                    source=source,status='available',points=points)
    updated, result = recover(partial, Invalid())
    assert result['state'] == 'human_review' and not updated.gps


def test_no_request_for_complete_or_safety_case():
    assert plan(fixture()) is None
    safety = fixture('C-0006'); safety.gps = []
    assert plan(safety) is None


def test_service_failure_gives_human_task():
    partial = fixture(); partial.gps = []
    class Broken:
        def fetch(self, request): raise RuntimeError('service unavailable')
    _, result = recover(partial, Broken())
    assert result['state'] == 'human_review' and 'service failed' in result['human_task']


def test_api_marks_synthetic_preview_and_rejects_unsupported_inputs():
    client = TestClient(app)
    r = client.get('/api/evidence-demo/C-0004')
    assert r.status_code == 200
    assert r.json()['synthetic'] and not r.json()['model_called']
    assert r.json()['report']['state'] == 'ready_for_court'
    assert client.get('/api/evidence-demo/DISP-002').status_code == 400
    assert client.get('/api/evidence-demo/C-0004?mode=unknown').status_code == 400

BENCH_CASES = sorted((ROOT / 'data/bench/cases').glob('B-*.json'))


@pytest.mark.parametrize('path', BENCH_CASES, ids=lambda p: p.stem)
def test_existing_benchmark_is_unchanged_and_does_not_fetch(path):
    from core.facts.tools import build_fact_table
    from core.policy_engine import evaluate
    case = Case.model_validate_json(path.read_text())
    before = digest(case)
    facts_before = build_fact_table(case).model_dump(mode='json')
    cert_before = evaluate(case, build_fact_table(case)).lines()
    class MustNotFetch:
        def fetch(self, request):
            pytest.fail('Existing complete benchmark must not trigger recovery')
    updated, report = recover(case, MustNotFetch())
    assert report['state'] == 'no_supported_request'
    assert digest(case) == digest(updated) == before
    assert build_fact_table(updated).model_dump(mode='json') == facts_before
    assert evaluate(updated, build_fact_table(updated)).lines() == cert_before


def test_current_sample_and_benchmark_replays_remain_available():
    client = TestClient(app)
    assert client.get('/api/runs/DISP-002').status_code == 200
    from app.main import stored_run_path, BENCH_RUNS_DIR
    paths = sorted(BENCH_RUNS_DIR.glob('*.record.json'))
    assert paths
    assert stored_run_path(paths[0].name.removesuffix('.record.json')) == paths[0]
