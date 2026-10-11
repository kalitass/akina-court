"""Stress-fixture preparation and honest scoring, not AI performance tests."""
import copy

import pytest

from bench.recovery_suite import load_suite, prepare_case, score, workflow_score
from recovery.evidence import digest, recover


@pytest.mark.parametrize('row', load_suite()['cases'], ids=lambda r: r['id'])
def test_stress_path_is_frozen_and_does_not_change_source(row):
    initial, provider = prepare_case(row)
    original = digest(initial)
    updated, evidence = recover(initial, provider)
    assert digest(initial) == original and initial.gps == []
    assert evidence['state'] == row['expected_recovery_state']
    assert evidence['reviewer_packet']['fingerprints']['current'] == digest(updated)
    if row['response'] != 'available':
        assert not updated.gps and evidence.get('source') is None
        assert evidence['human_task']
    if row['id'] == 'R-007':
        assert 'gap over' in evidence['human_task']  # Not merely missing an endpoint.
    if row['id'] == 'R-009':
        assert all(m.ts is None for m in updated.chat if m.sender == 'rider')
        assert evidence['reviewer_packet']['open_questions']
    if row['id'] == 'R-010':
        assert updated.gps and evidence['source']
        assert 'amount cannot be computed' in evidence['human_task']


def test_score_checks_account_flag_and_does_not_coerce_absent_refund_amount():
    expected = load_suite()['cases'][0]['expected']
    hearing = {'ruling': dict(expected), 'eligibility': {'auto': True}}
    assert score(hearing, expected)['automatic_and_correct']
    hearing['ruling']['flag_account'] = False
    assert score(hearing, expected)['wrong_automatic']
    hearing['ruling'] = dict(expected, amount=None)
    assert not score(hearing, expected)['strict_match']


@pytest.mark.parametrize('amount', [float('nan'), float('inf'), True])
def test_non_numeric_or_non_finite_amount_never_passes(amount):
    expected = load_suite()['cases'][0]['expected']
    assert not score({'ruling': dict(expected, amount=amount)}, expected)['strict_match']


def test_workflow_handoff_and_model_failure_have_distinct_scoring():
    rows = load_suite()['cases']
    blocked = next(r for r in rows if r['id'] == 'R-004')
    result = workflow_score({'state': 'human_review'}, blocked)
    assert result['kind'] == 'retrieval_handoff' and result['correct_handoff']
    assert not result['automatic_and_correct']
    assert workflow_score({'state': 'review_failed'}, blocked) is None
    assert not workflow_score({'state': 'human_review'}, rows[0])['correct_handoff']


def test_changed_fixture_reference_is_rejected_before_preparation():
    row = copy.deepcopy(load_suite()['cases'][0]); row['base_hash'] = 'wrong'
    with pytest.raises(ValueError, match='fingerprint'):
        prepare_case(row)
