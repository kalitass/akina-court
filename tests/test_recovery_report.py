"""Reports preserve denominators, failures and comparable experimental conditions."""
import copy
import pytest
from bench.recovery_report import render, summarise
from bench.recovery_suite import load_suite


def document(arm='court', state='reviewed', model='test:model'):
    expected = load_suite()['cases'][0]['expected']
    hearing = {'ruling': dict(expected), 'eligibility': {'auto':True}}
    before = {'ruling': {'ruling':'escalate','amount':None,'escalate':True,'flag_account':False}, 'eligibility':{'auto':False}}
    return {'review_id':arm+state+model, 'kind':'live_evaluation', 'suite_version':'test',
        'policy_hash':'p', 'code_hash':'c', 'model':model, 'role_models':{},
        'cases':[{'id':'R-001', 'arm':arm, 'expected':expected, 'initial':{'case_id':'C-0004'},
            'updated':{'gps':[{'lat':1.0}]}, 'review':{'review_id':'trial', 'state':state,
            'hearing_context':{'workflow':arm,'model':model}, 'hearings':[before, hearing]}}]}


def test_completed_pair_and_failed_run_have_distinct_denominators():
    report = summarise([('court',document()), ('judge',document('judge_only')), ('failure',document(state='review_failed'))])
    group = report['groups'][0]
    assert group['arms']['court']['accuracy_completed'] == {'numerator':1,'denominator':1}
    assert group['arms']['court']['correct_automation_attempted'] == {'numerator':1,'denominator':2}
    assert group['arms']['court']['failed'] == 1
    assert not group['paired_cases']  # Repeated attempts are not cherry-picked.


def test_matching_pair_is_counted_but_different_models_are_separate():
    pair = summarise([('court',document()), ('judge',document('judge_only'))])
    assert len(pair['groups'][0]['paired_cases']) == 1
    separate = summarise([('court',document()), ('judge',document('judge_only',model='other:model'))])
    assert len(separate['groups']) == 2
    assert all(not g['paired_cases'] for g in separate['groups'])


def test_different_inputs_cannot_be_compared():
    judge = document('judge_only'); judge['cases'][0]['updated']['gps'] = []
    report = summarise([('court',document()), ('judge',judge)])
    assert not report['groups'][0]['paired_cases']


def test_handoffs_not_counted_as_model_accuracy():
    doc = document(state='human_review')
    doc['cases'][0]['expected']['ruling'] = 'escalate'
    report = summarise([('handoff',doc)])
    totals = report['groups'][0]['arms']['court']
    assert totals['correct_handoffs'] == 1 and totals['model_completed'] == 0
    assert totals['correct_automatic'] == 0


def test_preparation_and_legacy_records_have_no_performance_claim():
    legacy = document(); legacy['cases'][0]['review'].pop('hearing_context')
    report = summarise([('prep',{'kind':'preparation_only'}),('legacy',legacy)])
    assert report['preparation_files_excluded'] == 1
    assert len(report['incompatible_records']) == 1 and not report['groups']
    assert 'No accuracy or automation claim' in render(report)


def test_duplicate_record_rejected_and_scores_recomputed():
    doc = document()
    with pytest.raises(ValueError, match='duplicate'):
        summarise([('a',doc),('b',copy.deepcopy(doc))])
    doc['cases'][0]['review']['hearings'][1]['ruling']['amount'] = None
    doc['cases'][0]['score'] = {'strict_match':True}  # Stored claim cannot override source.
    report = summarise([('source',doc)])
    assert report['groups'][0]['arms']['court']['wrong_automatic'] == 1


def test_workflow_or_reused_trial_rejected():
    doc = document(); doc['cases'][0]['review']['hearing_context']['workflow'] = 'judge_only'
    with pytest.raises(ValueError, match='workflow'): summarise([('bad',doc)])
    doc = document(); doc['cases'][0]['review']['reused_initial'] = {'review_id':'old'}
    with pytest.raises(ValueError, match='reused'): summarise([('bad',doc)])


def test_local_experiment_flags_are_separate_conditions():
    court = document(); judge = document('judge_only')
    judge['cases'][0]['review']['hearing_context']['local_compact_rebuttal'] = '1'
    report = summarise([('court',court),('judge',judge)])
    assert len(report['groups']) == 2
    assert all(not g['paired_cases'] for g in report['groups'])
