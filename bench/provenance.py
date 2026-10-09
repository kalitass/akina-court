#!/usr/bin/env python3
"""Benchmark provenance: recompute, from the raw per-run files only, what the pages claim.

Prints per arm: file count, model id(s) recorded by the client, time span, model calls, tokens, and an INDEPENDENT
exact-match count against data/bench/manifest.json (outcome + amount to the cent + escalation), so a reviewer can
check the headline numbers without trusting bench/report.py. Also prints sha256 of every result file.
    .venv/bin/python bench/provenance.py            # table
    .venv/bin/python bench/provenance.py --hashes   # + one sha256 line per file
"""
import collections, glob, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "bench" / "results"
truth = {c["case_id"]: c["truth"] for c in json.load(open(ROOT / "data" / "bench" / "manifest.json"))["cases"]}

def exact(rul, t):
    if rul.get("escalate") != t["escalate"]:
        return False
    if t["escalate"]:
        return True
    if rul.get("ruling") != t["ruling"]:
        return False
    a, b = float(rul.get("amount") or 0), float(t.get("amount") or 0)   # None and 0 are the same "no money" (as in bench/report.py)
    return abs(a - b) <= 0.01

rows, allfiles = [], []
for arm in ["raw", "facts_only", "judge_only", "court", "raw_swap", "facts_only_swap", "court_swap"]:
    fs = sorted(f for f in glob.glob(str(RES / arm / "*.json")) if not f.endswith(".record.json"))
    if not fs:
        continue
    ds = [json.load(open(f)) for f in fs]
    allfiles += fs
    prim = [d for d in ds if d.get("repeat", 0) == 0]
    ex = sum(1 for d in prim if d.get("ok") and exact(d["ruling"], truth[d["case_id"]]))
    ts = sorted(d["ts"] for d in ds if d.get("ts"))
    rows.append((arm, len(fs), ",".join(sorted({d.get("model", "?") for d in ds})), ts[0][:16].replace("T", " "), ts[-1][:16].replace("T", " "),
                 sum(d.get("llm_calls", 0) for d in ds), sum(d.get("input_tokens", 0) for d in ds), sum(d.get("output_tokens", 0) for d in ds),
                 f"{ex}/{len(prim)}" if not arm.endswith("_swap") else "-", len(prim)))
print("| arm | run files | model id recorded | first run (UTC) | last run (UTC) | model calls | input tokens | output tokens | exact core decision (repeat 0, recomputed here) |")
print("|---|---|---|---|---|---|---|---|---|")
for r in rows:
    print(f"| {r[0]} | {r[1]} | `{r[2]}` | {r[3]} | {r[4]} | {r[5]} | {r[6]:,} | {r[7]:,} | {r[8]} |")
print(f"\ntotal run files {len(allfiles)} · total model calls {sum(r[5] for r in rows)} · total input tokens {sum(r[6] for r in rows):,} · output {sum(r[7] for r in rows):,}")
jl = RES / "results.jsonl"
print(f"append-only log bench/results/results.jsonl: {sum(1 for _ in open(jl))} lines (includes retries/superseded runs)")
if "--hashes" in sys.argv:
    for f in allfiles:
        print(hashlib.sha256(open(f, "rb").read()).hexdigest()[:16], Path(f).relative_to(ROOT))
