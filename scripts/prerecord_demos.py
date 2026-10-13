#!/usr/bin/env python3
"""Pre-record the demo runs the landing page links to, so an unattended judge never waits on an LLM.

    .venv/bin/python scripts/prerecord_demos.py            # all
    .venv/bin/python scripts/prerecord_demos.py fake_fact  # one

Each entry runs the court once and stores the CaseRecord under runs/<case>~<name>.json. The replay page loads it with
  /replay.html?case=C-0001&run=C-0001~fake_fact      (fault injection: the case is unchanged, the LLM output is tampered)
  /replay.html?case=C-0005&cf=grace_179              (counterfactual: the case itself is transformed)
  /replay.html?case=C-0004&run=C-0004~stretch        (stretch module on: the bad-faith screen adds signal facts the court can cite)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# The benchmark and the stored demo runs are the bare court: no precedent store feeding earlier rulings into later
# prompts, no SLA queue or bad-faith signals writing extra facts or repo files. Whatever the shell exports is ignored.
for _k in [k for k in os.environ if k.startswith("STRETCH_")]:
    os.environ.pop(_k)
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.counterfactual import apply  # noqa: E402
from core.orchestrate import model_outage, run_case  # noqa: E402
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
    "no_call": ("DISP-002", {"cf": "no_call"}),                # v3 NS-1 (iii): the driver messaged but never called → the fee is refunded
    "stretch": ("C-0004", {"flags": ("STRETCH_FRAUD",)}),      # the one stored hearing with a stretch module on; a ~ run id never writes the stores
}


async def one(name: str) -> Path:
    cid, spec = DEMOS[name]
    case = Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))
    if spec.get("cf"):
        case = apply(case, spec["cf"]).model_copy(update={"case_id": f"{cid}~{spec['cf']}"})
    for flag in spec.get("flags", ()):
        os.environ[flag] = "1"
    try:
        rec = await run_case(case, inject=spec.get("inject"))
    finally:
        for flag in spec.get("flags", ()):
            os.environ.pop(flag, None)
    rid = f"{cid}~{name}"
    if model_outage(rec):
        raise SystemExit(f"{rid}: a model stage failed ({'; '.join(model_outage(rec))}) — not stored; run this one again")
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
