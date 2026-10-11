#!/usr/bin/env python3
"""Live synthetic recovery review, saved separately from demo and benchmark records.

Set model credentials in the environment. This makes two full court calls and consumes model credits.
"""
import argparse
import asyncio
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Demonstration review must not read/write stretch stores or influence later cases.
import os
for key in tuple(os.environ):
    if key.startswith('STRETCH_'):
        os.environ.pop(key)
from core.schemas import Case
from core.evidence import SyntheticGpsProvider
from core.review import review_recovered, save_review

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['C-0001','C-0004'],default='C-0004')
    parser.add_argument('--mode',choices=['available','unavailable','conflict'],default='available')
    parser.add_argument('--out',type=Path,default=ROOT/'review_runs')
    args=parser.parse_args()
    full=Case.model_validate_json((ROOT/'data/cases'/f'{args.case}.json').read_text())
    partial=full.model_copy(deep=True);partial.gps=[]
    result=await review_recovered(partial,SyntheticGpsProvider(full,args.mode))
    path=save_review(result,args.out)
    print(f"{result['state']}: {path}")
    if result['failure']:
        print(result['failure']); return 1
    return 0

if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
