#!/usr/bin/env python3
"""Live synthetic recovery review, saved separately from demo and benchmark records.

Set a model provider in the environment. Two hearings use credits on cloud providers;
the optional Ollama backend uses local inference without paid API calls.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Demonstration review must not read/write stretch stores or influence later cases.
import os
from core.schemas import Case
from core.evidence import SyntheticGpsProvider
from core.review import review_recovered, save_review
from core.evidence import recover
from core.orchestrate import run_case
from core.llm import describe_model, model_configured

def score_decision(hearing, expected):
    ruling = hearing['ruling']
    correct = (ruling['ruling'] == expected['ruling']
               and abs(round(float(ruling.get('amount') or 0) * 100) - round(float(expected.get('amount') or 0) * 100)) <= 1
               and bool(ruling.get('escalate') or ruling['ruling'] == 'escalate') == bool(expected.get('escalate')))
    auto = bool((hearing.get('eligibility') or {}).get('auto'))
    return {'strict_match': correct, 'automatic_and_correct': auto and correct,
            'wrong_automatic': auto and not correct, 'automatic': auto}


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['C-0001','C-0004'],default='C-0004')
    parser.add_argument('--mode',choices=['available','unavailable','conflict'],default='available')
    parser.add_argument('--out',type=Path,default=ROOT/'review_runs')
    parser.add_argument('--arm',choices=['judge_only','court'],default='court')
    parser.add_argument('--batch-evidence',action='store_true',help='Ollama-only experiment: advocates read all evidence slices in one tool call')
    parser.add_argument('--compact-rebuttal',action='store_true',help='Ollama-only experiment: replace tool-call history with verified brief and previously read facts')
    parser.add_argument('--dry-run',action='store_true',help='Prepare snapshots only; no model calls or performance scores')
    args=parser.parse_args()
    if args.batch_evidence and os.environ.get('LLM_PROVIDER', 'deepseek').lower() != 'ollama':
        parser.error('--batch-evidence is only supported for the local Ollama experiment')
    if args.compact_rebuttal and os.environ.get('LLM_PROVIDER', 'deepseek').lower() != 'ollama':
        parser.error('--compact-rebuttal is only supported for the local Ollama experiment')
    os.environ['LOCAL_BATCH_EVIDENCE'] = '1' if args.batch_evidence else '0'
    os.environ['LOCAL_COMPACT_REBUTTAL'] = '1' if args.compact_rebuttal else '0'
    for key in tuple(os.environ):
        if key.startswith('STRETCH_'):
            os.environ.pop(key)
    full=Case.model_validate_json((ROOT/'data/cases'/f'{args.case}.json').read_text())
    partial=full.model_copy(deep=True);partial.gps=[]
    if args.dry_run:
        updated, report = recover(partial,SyntheticGpsProvider(full,args.mode))
        args.out.mkdir(parents=True,exist_ok=True)
        path=args.out/f'{args.case}-{args.mode}-{args.arm}-prepared.json'
        with path.open('x') as f:
            json.dump({'kind':'preparation_only','model_called':False,'arm':args.arm,
                       'evidence':report,'initial':partial.model_dump(mode='json'),
                       'updated':updated.model_dump(mode='json')},f,indent=2)
        print(f'Prepared only (no model evaluation): {path}')
        return 0
    if args.mode == 'available' and not model_configured():
        print('Model credential missing; no model evaluation was run. Configure the provider in the local environment.')
        return 2
    async def runner(case, **kwargs):
        return await run_case(case, advocates=args.arm=='court', **kwargs)
    start=time.perf_counter()
    result=await review_recovered(partial,SyntheticGpsProvider(full,args.mode),runner=runner)
    result['experiment']={'arm':args.arm,'model':describe_model(), 'duration_s':time.perf_counter()-start,
                          'evidence_fetch': 'batched' if args.batch_evidence else 'original',
                          'rebuttal_context': 'compact' if args.compact_rebuttal else 'original',
                          'judge_model_override':os.environ.get('LLM_MODEL_JUDGE'),
                          'advocate_model_override':os.environ.get('LLM_MODEL_ADVOCATE'),
                          'reference':'data/expected/'+args.case+'.json','scores':None}
    if result['state']=='reviewed':
        expected=json.loads((ROOT/'data/expected'/f'{args.case}.json').read_text())
        result['experiment']['scores']={
            'before':score_decision(result['hearings'][0],{'ruling':'escalate','amount':None,'escalate':True}),
            'after':score_decision(result['hearings'][1],expected)}
    path=save_review(result,args.out)
    print(f"{result['state']}: {path}")
    if result['failure']:
        print(result['failure']); return 1
    return 0

if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
