#!/usr/bin/env python3
"""Prepare the recovery stress suite; --live runs one explicitly selected arm/case."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.recovery_suite import load_suite, prepare_case, score, workflow_score
from recovery.evidence import recover
from core.llm import describe_model
from recovery.config import model_configured
from core.orchestrate import run_case
from core.receipt import code_hash, policy_hash
from recovery.review import review_recovered, save_review


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', help='Manifest ID; required for --live')
    parser.add_argument('--arm', choices=['judge_only', 'court'])
    parser.add_argument('--live', action='store_true', help='Call configured models; cloud calls can cost money')
    args = parser.parse_args()
    suite = load_suite()
    rows = [r for r in suite['cases'] if args.case is None or r['id'] == args.case]
    if not rows:
        parser.error('Unknown recovery case')
    if args.live and (not args.case or not args.arm):
        parser.error('--live requires exactly one --case and --arm')
    # Isolation from production-like precedent/SLA stores and previous experiments.
    for key in tuple(os.environ):
        if key.startswith('STRETCH_'):
            os.environ.pop(key)
    os.environ['LOCAL_BATCH_EVIDENCE'] = '0'
    os.environ['LOCAL_COMPACT_REBUTTAL'] = '0'
    directory = ROOT / 'review_runs/recovery-suite' / uuid4().hex
    output = {'kind': 'live_evaluation' if args.live else 'preparation_only',
              'suite_version': suite['version'], 'policy_hash': policy_hash(), 'code_hash': code_hash(),
              'model': describe_model() if args.live else None,
              'role_models': {role: os.environ.get(f'LLM_MODEL_{role.upper()}')
                              for role in ('judge', 'advocate')},
              'cost': None, 'cost_note': 'Not measured; do not infer a monetary saving.', 'cases': []}
    for row in rows:
        initial, provider = prepare_case(row)
        updated, report = recover(initial, provider)
        item = {'id': row['id'], 'arm': args.arm, 'expected': row['expected'],
                'evidence': report, 'initial': initial.model_dump(mode='json'),
                'updated': updated.model_dump(mode='json'), 'score': None, 'model_called': False}
        if args.live:
            if report['state'] == 'ready_for_court' and not model_configured():
                print('Provider credential missing; no model call or performance score.'); return 2
            async def runner(case, **kwargs):
                return await run_case(case, advocates=args.arm == 'court', **kwargs)
            start = time.monotonic()
            result = await review_recovered(initial, provider, runner=runner, hearing_mode=args.arm)
            item.update(review=result, score=workflow_score(result, row),
                        duration_s=round(time.monotonic() - start, 3),
                        model_called=bool(result['attempts']))
            # Recovery records contain a retrieval timestamp: the preflight
            # snapshot must not be mistaken for this live attempt's snapshot.
            item.update(evidence=result['evidence'], initial=result['snapshots'][0],
                        updated=result['snapshots'][-1])
            item['before_score'] = (score(result['hearings'][0],
                {'ruling': 'escalate', 'amount': None, 'escalate': True, 'flag_account': False})
                if result['state'] == 'reviewed' else None)
            item['baseline'] = row['baseline']
            item['score_scope'] = 'Paired court/model decision or retrieval handoff; never merge their accuracy denominators.'
        else:
            item['preparation_matches'] = report['state'] == row['expected_recovery_state']
        output['cases'].append(item)
    # Exclusive write, nested under ignored review_runs; no benchmark/page updates.
    path = save_review({'review_id': uuid4().hex, **output}, directory)
    print(f"{output['kind']}: {path}")
    if not args.live:
        print(f"Prepared {len(rows)} cases; model calls: 0; performance scores: none")
        return int(not all(i['preparation_matches'] for i in output['cases']))
    return int(any(i['review']['state'] == 'review_failed' for i in output['cases']))


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
