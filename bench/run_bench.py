#!/usr/bin/env python3
"""Run the benchmark arms over data/bench/ and save one JSON per (arm, case, repeat). Resumable.

    export DEEPSEEK_API_KEY=... in the shell (no script reads .env); export LLM_PROVIDER=deepseek
    .venv/bin/python bench/run_bench.py --arms raw,facts_only,court --limit 2        # smoke test
    .venv/bin/python bench/run_bench.py --arms court --repeats 3                     # consistency (pass^N)
    .venv/bin/python bench/run_bench.py --arms raw,facts_only,court --swap           # identity-swap invariance
    .venv/bin/python bench/run_bench.py --cases B-0003,B-0017 --arms court --force   # re-run two cases
    .venv/bin/python bench/report.py                                                 # metrics -> bench/results/summary.md

Arms: raw / facts_only (bench.baseline, one LLM call) and court (core.orchestrate.run_case: fact table -> two
advocates -> rebuttal -> judge -> code verification). Results go to bench/results/<arm>/<case>[.r<k>].json plus
bench/results/results.jsonl (append-only log). Existing successful results are skipped unless --force.
Token usage of every pydantic-ai Agent.run inside a case is summed through a context variable, so the court arm's
tokens cover advocates + rebuttal + judge + notices without touching core/.
"""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os

# The benchmark and the stored demo runs are the bare court: no precedent store feeding earlier rulings into later
# prompts, no SLA queue or bad-faith signals writing extra facts or repo files. Whatever the shell exports is ignored.
for _k in [k for k in os.environ if k.startswith("STRETCH_")]:
    os.environ.pop(_k)
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent  # noqa: E402

from bench.baseline import run_baseline, usage_of  # noqa: E402
from core.case_format import read_case  # noqa: E402
from core.llm import describe_model  # noqa: E402
from core.orchestrate import model_outage, run_case  # noqa: E402
from core.schemas import Case  # noqa: E402

BENCH = ROOT / "data" / "bench"
RESULTS = ROOT / "bench" / "results"
ARMS = ("raw", "facts_only", "judge_only", "court")
SCHEMA = 2   # 2 = the ruling dict carries every Ruling field (safety_concern, evidence_status ...); files without it are from before 2026-10-10
# every field of the model's ruling is kept as the model wrote it: the gate ablation re-validates these dicts, and a
# missing safety_concern / evidence_status would otherwise be filled in as "none" / "sufficient" by the legacy loader
RULING_KEYS = ("ruling", "amount", "recommended_action", "confidence", "reasoning", "cited_facts", "cited_policy", "escalate",
               "escalation_reason", "segment_findings", "element_findings", "rejected_claims", "flag_account", "goodwill_credit",
               "safety_concern", "safety_basis", "evidence_status", "evidence_gap")

# ---- token accounting: every Agent.run inside a case appends its usage to the case's accumulator ----
_usage_acc: contextvars.ContextVar = contextvars.ContextVar("bench_usage", default=None)
_orig_run = Agent.run


async def _counting_run(self, *args, **kwargs):
    res = await _orig_run(self, *args, **kwargs)
    acc = _usage_acc.get()
    if acc is not None:
        acc.append(usage_of(res))
    return res


Agent.run = _counting_run  # type: ignore[method-assign]


def sum_usage(acc) -> dict:
    return {"input_tokens": sum(u.input_tokens or 0 for u in acc), "output_tokens": sum(u.output_tokens or 0 for u in acc),
            "requests": sum(u.requests or 0 for u in acc), "llm_calls": len(acc)}


# ---- cases ----

def case_ids(args) -> list[str]:
    ids = sorted(p.stem for p in (BENCH / "cases").glob("*.json"))
    if args.cases:
        want = [c.strip() for c in args.cases.split(",") if c.strip()]
        ids = [c for c in ids if c in want]
    if args.limit:
        ids = ids[: args.limit]
    return ids


def load_case(cid: str, swap: bool) -> Case:
    d = read_case(BENCH / "cases" / f"{cid}.json")
    if swap:
        r, dr = d["profiles"]["rider"], d["profiles"]["driver"]
        shared = [k for k in r if k in dr and k != "trips_90d"]
        for k in shared:
            r[k], dr[k] = dr[k], r[k]
    return Case.model_validate(d)


def result_path(arm: str, cid: str, repeat: int, swap: bool) -> Path:
    name = f"{arm}_swap" if swap else arm
    return RESULTS / name / (f"{cid}.json" if repeat == 0 else f"{cid}.r{repeat}.json")


def ruling_dict(r) -> dict:
    d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
    return {k: d.get(k) for k in RULING_KEYS}


# ---- one run ----

class _Outage(Exception):
    """A court run completed only because a model stage failed and the orchestrator handed the case to a person."""


async def run_one(arm: str, cid: str, repeat: int, swap: bool, timeout: float, rebuttal: bool) -> dict:
    case = load_case(cid, swap)
    rec = {"arm": arm, "case_id": cid, "repeat": repeat, "swap": swap, "model": describe_model(),
           "ts": datetime.now(timezone.utc).isoformat(), "ok": False,
           "ruling_schema": SCHEMA}
    acc: list = []
    _usage_acc.set(acc)
    t0 = time.monotonic()
    try:
        if arm in ("court", "judge_only"):
            result_path(arm, cid, repeat, swap).with_suffix(".record.json").unlink(missing_ok=True)   # a failed re-run must not leave the old record behind
            record = await asyncio.wait_for(run_case(case, rebuttal=rebuttal and arm == "court", advocates=arm == "court"), timeout)
            rec["ruling"] = ruling_dict(record.ruling)
            outage = model_outage(record)
            if outage:
                # the judge never answered, or an advocate stage failed: the court produced a hand-off by default, not a
                # decision. Saved for inspection but marked failed, so the resume logic re-runs it and no reader scores it.
                rec["error"] = "model outage inside the run: " + "; ".join(outage)
                rec["status"] = record.status
                rec["events"] = len(record.events)
                rec["record_path"] = str(save_court_record(record, cid, repeat, swap, arm).relative_to(ROOT))
                raise _Outage()
            judge_raw = next((e.ruling for e in record.events if e.kind == "ruling" and e.ruling is not None), None)
            rec["pre_verify_ruling"] = ruling_dict(judge_raw) if judge_raw else None
            rec["status"] = record.status
            rec["events"] = len(record.events)
            rec["void_claims"] = sum(1 for e in record.events if e.kind in ("brief", "rebuttal") and e.brief for c in e.brief.claims if c.void)
            rec["verify_lines"] = [e.body for e in record.events if e.kind == "check" and e.title.startswith("Ruling verification")]
            rec["record_path"] = str(save_court_record(record, cid, repeat, swap, arm).relative_to(ROOT))
        else:
            out = await asyncio.wait_for(run_baseline(case, arm), timeout)
            rec["ruling"] = ruling_dict(out["ruling"])
        rec["ok"] = True
    except _Outage:
        pass
    except asyncio.TimeoutError:
        rec["error"] = f"timeout after {timeout:.0f} s"
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["latency_s"] = round(time.monotonic() - t0, 2)
    rec.update(sum_usage(acc))
    return rec


def save_court_record(record, cid: str, repeat: int, swap: bool, arm: str = "court") -> Path:
    p = result_path(arm, cid, repeat, swap).with_suffix(".record.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(record.model_dump_json(indent=1), encoding="utf-8")
    return p


async def main_async(args) -> int:
    global BENCH, RESULTS
    if getattr(args, "set", "main") != "main":            # trial cases, kept apart from the 50 until they prove themselves
        BENCH, RESULTS = ROOT / "data" / "bench" / args.set, ROOT / "bench" / "results" / args.set
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    bad = [a for a in arms if a not in ARMS]
    if bad:
        print(f"unknown arm(s) {bad}; choose from {ARMS}")
        return 2
    ids = case_ids(args)
    if not ids:
        print("no cases selected")
        return 2
    jobs = [(arm, cid, k, args.swap) for arm in arms for cid in ids for k in range(args.repeats)]
    todo = []
    for job in jobs:
        p = result_path(*job)
        if p.exists() and not args.force:
            try:
                done = json.loads(p.read_text())
                if done.get("ok") and done.get("ruling_schema") == SCHEMA:   # a file from an older runner is never "done"
                    continue
            except json.JSONDecodeError:
                pass
        todo.append(job)
    print(f"model {describe_model()} · arms {arms} · {len(ids)} case(s) × {args.repeats} repeat(s){' · identity swap' if args.swap else ''} "
          f"· {len(jobs) - len(todo)} done, {len(todo)} to run · concurrency {args.concurrency} · timeout {args.timeout:.0f} s")
    sem = asyncio.Semaphore(args.concurrency)
    log = RESULTS / "results.jsonl"
    RESULTS.mkdir(parents=True, exist_ok=True)
    failures = 0

    async def worker(job):
        nonlocal failures
        async with sem:
            rec = await run_one(*job, timeout=args.timeout, rebuttal=not args.no_rebuttal)
        p = result_path(*job)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in rec.items() if k not in ("traceback", "verify_lines")}, ensure_ascii=False) + "\n")
        r = rec.get("ruling") or {}
        if rec["ok"]:
            print(f"  {job[0]:10} {job[1]} r{job[2]}  {r.get('ruling'):14} {r.get('amount') if r.get('amount') is not None else '':>6}  "
                  f"{rec['latency_s']:6.1f}s  in {rec['input_tokens']:>6} out {rec['output_tokens']:>5}  [{' '.join(r.get('cited_policy') or [])}]")
        else:
            failures += 1
            print(f"  {job[0]:10} {job[1]} r{job[2]}  FAILED {rec.get('error')}")

    await asyncio.gather(*(worker(j) for j in todo))
    print(f"done: {len(todo) - failures} ok, {failures} failed → {RESULTS}")
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", default="raw,facts_only,court", help="comma list of raw, facts_only, court")
    ap.add_argument("--cases", default="", help="comma list of case ids (default: all of data/bench/cases)")
    ap.add_argument("--limit", type=int, default=0, help="first N cases only")
    ap.add_argument("--repeats", type=int, default=1, help="runs per case (consistency); repeat k>0 saved as <case>.r<k>.json")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=420.0, help="seconds per case")
    ap.add_argument("--swap", action="store_true", help="identity swap: exchange rider/driver profile blocks, results under <arm>_swap/")
    ap.add_argument("--force", action="store_true", help="re-run even if a successful result exists")
    ap.add_argument("--no-rebuttal", action="store_true", help="court arm without the rebuttal round")
    ap.add_argument("--set", default="main", help="main = data/bench; any other name = data/bench/<name> (trial cases, results under bench/results/<name>)")
    args = ap.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("LLM_PROVIDER", "deepseek") == "deepseek":
        print("DEEPSEEK_API_KEY not set: export it in the shell first")
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
