#!/usr/bin/env python3
"""Offline ablation: apply the policy-certificate gate (core/verify.verify_ruling with the certificate) to the rulings
the single-call arms produced, with zero extra LLM calls, and compare with the full court.

    .venv/bin/python bench/gate_ablation.py        # -> bench/results/gate_ablation.json (+ per-case reasons)

Definitions (these are the ones the dashboard and docs quote):
  core decision      = outcome label + amount (±$0.01) + escalation flag; account flags and citations are NOT part of it
  model escalated    = the arm's own ruling already said "escalate" (goes to a human regardless of any gate)
  blocked by gate    = the certificate/verifier turned a non-escalated ruling into human review
  human flow         = model escalated + blocked by gate   (what an ops team would actually receive)
  auto               = cleared for automatic execution of the core action
  wrong & executed   = auto AND core decision wrong — the number that matters
Caveat printed into the JSON: the raw arm never sees fact ids (its prompt gets the raw case JSON), so the verifier's
"citations must resolve to facts" rule blocks every raw ruling that is not an escalation. That row shows the gate's
interface requirement, not its discriminative power; facts_only + gate is the fair single-call comparison.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.facts.tools import build_fact_table  # noqa: E402
from core.policy import citable_ids  # noqa: E402
from core.policy_engine import evaluate  # noqa: E402
from core.schemas import Case, Ruling  # noqa: E402
from core.verify import verify_ruling  # noqa: E402

RESULTS = ROOT / "bench" / "results"
EXPECTED = {Path(p).stem: json.load(open(p)) for p in glob.glob(str(ROOT / "data" / "bench" / "expected" / "B-*.json"))}


def core_ok(ruling: str, amount, escalate: bool, exp: dict) -> bool:
    return ruling == exp["ruling"] and abs(float(amount or 0) - float(exp.get("amount") or 0)) <= 0.0105 and bool(escalate) == bool(exp.get("escalate"))


def gate_arm(arm: str) -> dict:
    clause_ids = citable_ids()
    rows = []
    for p in sorted(glob.glob(str(RESULTS / arm / "B-00??.json"))):
        rec = json.load(open(p))
        cid = rec["case_id"]
        exp = EXPECTED[cid]
        d = dict(rec["ruling"])
        for k, v in (("reasoning", ""), ("cited_facts", []), ("cited_policy", []), ("recommended_action", ""), ("confidence", 0.5)):
            d.setdefault(k, v)
        case = Case.model_validate(json.load(open(ROOT / "data" / "bench" / "cases" / f"{cid}.json")))
        table = build_fact_table(case)
        cert = evaluate(case, table)
        before = Ruling.model_validate(d)
        after, lines = verify_ruling(before, table, clause_ids, (), certificate=cert)
        model_escalated = bool(before.escalate) or before.ruling == "escalate"
        blocked = (not model_escalated) and bool(after.escalate)
        auto = not model_escalated and not blocked
        wrong = not core_ok(before.ruling, before.amount, before.escalate, exp)
        rows.append({"case_id": cid, "model_ruling": before.ruling, "model_amount": before.amount, "expected": exp["ruling"],
                     "expected_amount": exp.get("amount"), "core_wrong": wrong, "model_escalated": model_escalated,
                     "blocked_by_gate": blocked, "auto": auto, "wrong_and_executed": auto and wrong,
                     "gate_reason": [l for l in lines if l.startswith(("HARD", "✗", "not eligible")) or "escalat" in l.lower()][:3]})
    n = len(rows)
    return {
        "arm": arm, "n": n,
        "core_wrong": sum(r["core_wrong"] for r in rows),
        "model_escalated": sum(r["model_escalated"] for r in rows),
        "blocked_by_gate": sum(r["blocked_by_gate"] for r in rows),
        "wrong_blocked": sum(r["blocked_by_gate"] and r["core_wrong"] for r in rows),
        "correct_blocked": sum(r["blocked_by_gate"] and not r["core_wrong"] for r in rows),
        "human_flow": sum(not r["auto"] for r in rows),
        "human_rate": round(sum(not r["auto"] for r in rows) / n, 3) if n else None,
        "auto": sum(r["auto"] for r in rows),
        "auto_rate": round(sum(r["auto"] for r in rows) / n, 3) if n else None,
        "wrong_and_executed": sum(r["wrong_and_executed"] for r in rows),
        "leaks": [r["case_id"] for r in rows if r["wrong_and_executed"]],
        "cases": rows,
    }


def court_arm(arm: str = "court") -> dict:
    """A pipeline arm's own numbers from its records (eligibility.auto decides execution); also used for judge_only."""
    rows = []
    for p in sorted(glob.glob(str(RESULTS / arm / "B-00??.json"))):
        rec = json.load(open(p))
        cid = rec["case_id"]
        exp = EXPECTED[cid]
        r = rec["ruling"]
        rp = Path(p).with_name(Path(p).name[:-5] + ".record.json")
        elig = json.load(open(rp)).get("eligibility") if rp.exists() else None
        auto = bool(elig.get("auto")) if isinstance(elig, dict) else rec.get("status") == "resolved"
        wrong = not core_ok(r["ruling"], r.get("amount"), r.get("escalate"), exp)
        rows.append({"case_id": cid, "core_wrong": wrong, "auto": auto, "wrong_and_executed": auto and wrong,
                     "model_escalated": bool(r.get("escalate")), "human_reasons": (elig or {}).get("reasons", [])})
    n = len(rows)
    return {"arm": arm, "n": n, "core_wrong": sum(r["core_wrong"] for r in rows),
            "model_escalated": sum(r["model_escalated"] for r in rows), "blocked_by_gate": None, "wrong_blocked": None, "correct_blocked": None,
            "human_flow": sum(not r["auto"] for r in rows), "human_rate": round(sum(not r["auto"] for r in rows) / n, 3) if n else None,
            "auto": sum(r["auto"] for r in rows), "auto_rate": round(sum(r["auto"] for r in rows) / n, 3) if n else None,
            "wrong_and_executed": sum(r["wrong_and_executed"] for r in rows), "leaks": [r["case_id"] for r in rows if r["wrong_and_executed"]],
            "cases": rows}


def main():
    out = {
        "definitions": __doc__.split("Definitions")[1].split("Caveat")[0].strip(),
        "caveat_raw": "the raw arm is given the case JSON without fact ids, so the verifier's citation rule blocks every raw ruling that is not "
                      "an escalation; the raw+gate row shows an interface requirement, not the gate's discriminative power",
        "arms": {a: gate_arm(a) for a in ("raw", "facts_only")},
    }
    if (RESULTS / "judge_only").exists():
        out["arms"]["judge_only"] = court_arm("judge_only")
    out["arms"]["court"] = court_arm()
    (RESULTS / "gate_ablation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{'arm':12} {'wrong':>5} {'esc':>4} {'blocked':>8} {'human':>10} {'auto':>6} {'wrong&exec':>11}  leaks")
    for a, m in out["arms"].items():
        print(f"{a:12} {m['core_wrong']:>5} {m['model_escalated']:>4} {str(m['blocked_by_gate']):>8} {m['human_flow']:>3} ({m['human_rate']:.0%}) {m['auto']:>6} {m['wrong_and_executed']:>11}  {m['leaks']}")
    print("written", RESULTS / "gate_ablation.json")


if __name__ == "__main__":
    main()
