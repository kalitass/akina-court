#!/usr/bin/env python3
"""Pre-record the demo runs the landing page links to, so an unattended judge never waits on an LLM.

    .venv/bin/python scripts/prerecord_demos.py            # all
    .venv/bin/python scripts/prerecord_demos.py fake_fact  # one

Each entry runs the court once and stores the CaseRecord under runs/<case>~<name>.json. The replay page loads it with
  /replay.html?case=C-0001&run=C-0001~fake_fact      (fault injection: the case is unchanged, the LLM output is tampered)
  /replay.html?case=C-0005&cf=grace_179              (counterfactual: the case itself is transformed)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.counterfactual import apply  # noqa: E402
from core.orchestrate import run_case  # noqa: E402
from core.schemas import Case  # noqa: E402

DEMOS = {
    "fake_fact": ("C-0001", {"inject": {"fake_fact"}}),
    "fake_clause": ("C-0001", {"inject": {"fake_clause"}}),
    "wrong_amount": ("C-0001", {"inject": {"wrong_amount"}}),
    "flag_text": ("C-0001", {"inject": {"flag_text"}}),
    "grace_179": ("C-0005", {"cf": "grace_179"}),
    "grace_181": ("C-0005", {"cf": "grace_181"}),
    "prompt_injection": ("C-0001", {"cf": "prompt_injection"}),
    "swap_profiles": ("C-0002", {"cf": "swap_profiles"}),
}


async def one(name: str) -> Path:
    cid, spec = DEMOS[name]
    case = Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))
    if spec.get("cf"):
        case = apply(case, spec["cf"]).model_copy(update={"case_id": f"{cid}~{spec['cf']}"})
    rec = await run_case(case, inject=spec.get("inject"))
    rid = f"{cid}~{name}"
    out = ROOT / "runs" / f"{rid}.json"
    out.write_text(rec.model_copy(update={"case_id": rid}).model_dump_json(indent=1), encoding="utf-8")
    r = rec.ruling
    print(f"{rid:28} {r.ruling:15} {('$%.2f' % r.amount) if r.amount else '':>7}  status={rec.status}  -> {out.relative_to(ROOT)}")
    return out


async def main(names):
    for n in names:
        await one(n)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(DEMOS)))
