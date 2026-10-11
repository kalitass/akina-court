"""Summarise saved recovery trials without combining incompatible experiments."""
from collections import defaultdict
import hashlib
import json

from bench.recovery_suite import score, workflow_score


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summarise(documents):
    groups = {}
    skipped = 0
    incompatible = []
    seen = set()
    for source, document in documents:
        if document.get('kind') != 'live_evaluation':
            skipped += 1
            continue
        rid = document.get('review_id')
        if not rid or rid in seen:
            raise ValueError('Missing or duplicate evaluation ID; cannot count a trial twice')
        seen.add(rid)
        conditions = {k: document.get(k) for k in ('suite_version', 'policy_hash', 'code_hash', 'model', 'role_models')}
        if any(conditions[k] is None for k in ('suite_version', 'policy_hash', 'code_hash', 'model')):
            raise ValueError('Live evaluation lacks comparison conditions')
        for item in document['cases']:
            arm = item.get('arm')
            if arm not in {'judge_only', 'court'}:
                raise ValueError('Unknown evaluation arm')
            review = item['review']
            context = review.get('hearing_context') or {}
            if not context:
                incompatible.append({'source':source, 'case':item['id'], 'reason':'Legacy record lacks hearing configuration; excluded from comparison'})
                continue
            if context.get('workflow') != arm:
                raise ValueError('Hearing workflow does not match evaluation arm')
            if review.get('reused_initial'):
                raise ValueError('Paired evaluation cannot include reused hearings')
            experiment = {**conditions, 'hearing_configuration': {k:v for k,v in context.items() if k != 'workflow'}}
            key = signature(experiment)
            group = groups.setdefault(key, {'conditions': experiment, 'arms': {}, 'trials': [], 'paired_cases': []})
            result = workflow_score(review, item)
            totals = group['arms'].setdefault(arm, dict(attempted=0, model_completed=0, failed=0,
                retrieval_handoffs=0, correct_handoffs=0, strict_correct=0,
                correct_automatic=0, wrong_automatic=0, before_correct_automatic=0))
            totals['attempted'] += 1
            if result is None:
                totals['failed'] += 1
            elif result['kind'] == 'retrieval_handoff':
                totals['retrieval_handoffs'] += 1
                totals['correct_handoffs'] += int(result['correct_handoff'])
            else:
                totals['model_completed'] += 1
                totals['strict_correct'] += int(result['strict_match'])
                totals['correct_automatic'] += int(result['automatic_and_correct'])
                totals['wrong_automatic'] += int(result['wrong_automatic'])
                before = score(review['hearings'][0], {'ruling':'escalate','amount':None,'escalate':True,'flag_account':False})
                totals['before_correct_automatic'] += int(before['automatic_and_correct'])
            # Ignore transport/retrieval timestamps, compare actual initial input and GPS.
            input_key = signature({'initial': item['initial'], 'gps': item['updated'].get('gps'),
                                   'expected': item['expected'], 'context': {k:v for k,v in context.items() if k != 'workflow'}})
            group['trials'].append({'case':item['id'], 'arm':arm, 'input_key':input_key,
                'source':source, 'review_id':review['review_id'], 'state':review['state'],
                'score':result, 'duration_s':item.get('duration_s'), 'failure':review.get('failure')})
    for group in groups.values():
        candidates = defaultdict(lambda: defaultdict(list))
        for trial in group['trials']:
            candidates[(trial['case'], trial['input_key'])][trial['arm']].append(trial)
        for (case, _), arms in candidates.items():
            # No best-run picking or pairing trials by arbitrary file order.
            if len(arms['court']) == len(arms['judge_only']) == 1:
                court, judge = arms['court'][0], arms['judge_only'][0]
                if all(t['score'] and t['score']['kind'] == 'model_decision' for t in (court, judge)):
                    group['paired_cases'].append({'case':case,
                        'court_correct_automatic':court['score']['automatic_and_correct'],
                        'judge_correct_automatic':judge['score']['automatic_and_correct'],
                        'court_source':court['source'], 'judge_source':judge['source']})
        for totals in group['arms'].values():
            totals['accuracy_completed'] = {'numerator':totals['strict_correct'], 'denominator':totals['model_completed']}
            totals['correct_automation_attempted'] = {'numerator':totals['correct_automatic'], 'denominator':totals['attempted']}
    return {'groups': [g for g in groups.values() if g['trials']], 'preparation_files_excluded': skipped,
            'incompatible_records': incompatible,
            'limits': 'Draft synthetic references. Failed runs are not correct handoffs; retrieval checks are not model accuracy. Repeated/unmatched trials are not selected for paired comparison. No monetary saving measured.'}


def render(report):
    lines = ['# Recovery evaluation report', '', report['limits'], '',
             f"Preparation files excluded: {report['preparation_files_excluded']}", '']
    for item in report['incompatible_records']:
        lines += [f"Excluded: {item['case']}; {item['reason']}; `{item['source']}`", '']
    if not report['groups']:
        lines += ['No eligible live evaluation results available. No accuracy or automation claim can be made.', '']
    for i, group in enumerate(report['groups'], 1):
        lines += [f'## Condition group {i}', '', '`'+json.dumps(group['conditions'], sort_keys=True)+'`', '',
            '| Arm | Attempts | Model completed | Failed | Correct handoffs | Accuracy / completed | Correct automatic / attempted | Wrong automatic |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        for arm, t in sorted(group['arms'].items()):
            lines += [f"| {arm} | {t['attempted']} | {t['model_completed']} | {t['failed']} | {t['correct_handoffs']}/{t['retrieval_handoffs']} | {t['strict_correct']}/{t['model_completed']} | {t['correct_automatic']}/{t['attempted']} | {t['wrong_automatic']} |"]
        pairs = group['paired_cases']
        lines += ['', f'Comparable completed case pairs: {len(pairs)}.']
        if pairs:
            delta = sum(int(p['court_correct_automatic'])-int(p['judge_correct_automatic']) for p in pairs)
            lines += [f'Court minus judge correct automatic count, paired cases only: {delta:+d}/{len(pairs)}.']
        else:
            lines += ['No matched pair supports a court-versus-judge improvement claim.']
        lines += ['', '### Source trials', '']
        for trial in group['trials']:
            lines += [f"- {trial['case']} / {trial['arm']}: {trial['state']}; `{trial['source']}`" + (f"; failure: {trial['failure']}" if trial['failure'] else '')]
        lines += ['']
    return '\n'.join(lines)
