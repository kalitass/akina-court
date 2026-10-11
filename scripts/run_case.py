#!/usr/bin/env python3
"""Run the three-agent court on one or more cases and compare with data/expected.

    .venv/bin/python scripts/run_case.py C-0001            # one case, prints the event log
    .venv/bin/python scripts/run_case.py all               # every demo case, summary table
    .venv/bin/python scripts/run_case.py C-0001 --no-rebuttal

Needs an LLM key in the environment (see core/llm.py). Writes runs/<case>.json (CaseRecord).
"""
from __future__ import annotations

import asyncio
import json
import os

# The benchmark and the stored demo runs are the bare court: no precedent store feeding earlier rulings into later
# prompts, no SLA queue or bad-faith signals writing extra facts or repo files. Whatever the shell exports is ignored.
for _k in [k for k in os.environ if k.startswith("STRETCH_")]:
    os.environ.pop(_k)
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.llm import describe_model          # noqa: E402
from core.orchestrate import model_outage, run_case, save_record   # noqa: E402
from core.schemas import Case                # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def load(cid: str) -> Case:
    return Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))


def expected(cid: str) -> dict:
    return json.loads((ROOT / "data" / "expected" / f"{cid}.json").read_text())


def compare(cid: str, rec) -> dict:
    e = expected(cid); r = rec.ruling
    amt_ok = (e.get("amount") is None and r.amount is None) or (e.get("amount") is not None and r.amount is not None and abs(e["amount"] - r.amount) <= 0.5)
    cited_ok = set(e["cited_policy"]) <= set(r.cited_policy)
    return {"ruling": r.ruling == e["ruling"], "amount": amt_ok, "escalate": r.escalate == e["escalate"], "policy⊇": cited_ok,
            "got": f"{r.ruling} {r.amount if r.amount is not None else ''} conf {r.confidence:.2f} [{' '.join(r.cited_policy)}]",
            "want": f"{e['ruling']} {e.get('amount') if e.get('amount') is not None else ''} [{' '.join(e['cited_policy'])}]"}


async def one(cid: str, verbose: bool, rebuttal: bool):
    case = load(cid)
    t = time.time()

    def show(ev):
        if verbose:
            head = f"[{ev.elapsed}] {ev.actor:>6} {ev.kind:<8} {ev.title}"
            print(head)
            if ev.kind in ("brief", "rebuttal", "ruling", "check", "escalate", "notify", "summary"):
                for line in ev.body.splitlines():
                    print("         " + line)
    rec = await run_case(case, on_event=show, rebuttal=rebuttal)
    if model_outage(rec):
        raise SystemExit(f"{cid}: a model stage failed ({'; '.join(model_outage(rec))}) — not stored; run this case again")
    p = save_record(rec, ROOT / "runs")
    c = compare(cid, rec)
    print(f"\n{cid}  {time.time() - t:5.1f}s  ruling={'✓' if c['ruling'] else '✗'} amount={'✓' if c['amount'] else '✗'} "
          f"escalate={'✓' if c['escalate'] else '✗'} policy⊇={'✓' if c['policy⊇'] else '✗'}\n   got:  {c['got']}\n   want: {c['want']}\n   saved {p}")
    return c


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rebuttal = "--no-rebuttal" not in sys.argv
    ids = sorted(p.stem for p in (ROOT / "data" / "cases").glob("C-*.json")) if (not args or args[0] == "all") else args
    print(f"model: {describe_model()}  rebuttal: {rebuttal}")
    out = {}
    for cid in ids:
        out[cid] = await one(cid, verbose=len(ids) == 1, rebuttal=rebuttal)
    if len(ids) > 1:
        print("\n" + "=" * 70)
        for cid, c in out.items():
            print(f"{cid}  ruling {'✓' if c['ruling'] else '✗'}  amount {'✓' if c['amount'] else '✗'}  escalate {'✓' if c['escalate'] else '✗'}  policy⊇ {'✓' if c['policy⊇'] else '✗'}   got: {c['got']}")


if __name__ == "__main__":
    asyncio.run(main())
