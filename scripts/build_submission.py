#!/usr/bin/env python3
"""Build web/submission.json from the benchmark result files.

Every number in the submission summary is read from bench/results/ (summary.json, gate_ablation.json, the per-run
files, the audit sample manifest) or counted from the repository, through the same loader the results page uses.
Nothing is typed by hand, so the summary cannot drift from the report. tests/test_numbers.py fails when the committed
file is older than the results.

    python scripts/build_submission.py            # rewrite web/submission.json
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))
import dashboard  # noqa: E402  (bench/dashboard.py: the results page's loader)

OUT = ROOT / "web" / "submission.json"
ARMS = ("raw", "facts_only", "judge_only", "court", "raw_swap", "facts_only_swap", "court_swap")


def run_files() -> list[dict]:
    rows = []
    for arm in ARMS:
        for f in sorted(glob.glob(str(ROOT / "bench" / "results" / arm / "*.json"))):
            if f.endswith(".record.json"):
                continue
            rows.append(json.loads(Path(f).read_text()))
    return rows


def audit() -> Optional[dict]:
    base = ROOT / "bench" / "results" / "audit_sample"
    if not (base / "manifest.json").exists():
        return None
    m = json.loads((base / "manifest.json").read_text())
    expected = {p.stem: json.loads(p.read_text()) for p in (ROOT / "data" / "bench" / "expected").glob("*.json")}
    matched, n = {}, {}
    for r in m["runs"]:
        e = expected[r["case_id"]]
        ok = r["ruling"] == e["ruling"] and bool(r["escalate"]) == bool(e["escalate"]) and abs(float(r["amount"] or 0) - float(e["amount"] or 0)) <= 0.01
        matched[r["arm"]] = matched.get(r["arm"], 0) + int(ok)
        n[r["arm"]] = n.get(r["arm"], 0) + 1
    calls = len(glob.glob(str(base / "*" / "*" / "calls" / "*.json")))
    files = sum(len(fs) for _, _, fs in __import__("os").walk(base))
    return {"runs": len(m["runs"]), "http_calls": calls, "files": files, "path": "bench/results/audit_sample/",
            "requested_model": m["requested_model"][0], "provider_model_reported": m["provider_model_reported"][0],
            "matched_reference": {a: f"{matched[a]}/{n[a]}" for a in ("court", "judge_only", "facts_only", "raw")}}


def build() -> dict:
    d = dashboard.load_all()
    S, G = d["summary"], d["gate"]["arms"]
    raw, fo, jo, ct = S["raw"], S["facts_only"], S["judge_only"], S["court"]
    n = ct["cases"]
    rows = run_files()
    ts = sorted(r["ts"] for r in rows)
    window = f"{ts[0][:16].replace('T', ' ')} to {ts[-1][11:16]} UTC"
    cnt = lambda rate: round(rate * n)
    au = audit()
    gps_s = round(d["gps_interval_s"] * d["gps_thin"])
    court_base = [r for r in rows if r["arm"] == "court" and not r.get("swap") and r.get("repeat", 0) == 0]
    flags = sum(1 for r in court_base if r["ruling"].get("flag_account"))
    cites_ct = ct["citations"] + ct["fact_citations"]
    cites_raw = raw["citations"] + raw["fact_citations"]
    return {
        "schema_version": "1.1",
        "generated_at": dt.date.today().isoformat(),
        "generated_by": "scripts/build_submission.py (numbers read from bench/results/)",
        "project": "Ryde Dispute Court",
        "team": "Akina Court",
        "tagline": "AI argues. Code verifies what can execute.",
        "hackathon": "Tencent Cloud AI CAN DO IT Hackathon Singapore 2026",
        "track": "Ryde: multi-agent autonomous dispute resolution",
        "built_with": ["CodeBuddy", "Pydantic AI", "DeepSeek-chat via the DeepSeek API", "FastAPI", "MapLibre", "OneMap Singapore routing"],
        "target_users": ["Ryde support and trust-and-safety operations (primary)", "riders and drivers (plain-language notices)", "compliance and audit (reproducibility receipt)"],
        "differentiation": "Facts are computed by code from platform, user and external records; the policy is a public, numbered, sourced document that runs as code; the agents may only cite both; a pre-execution policy check decides what may execute. Money can be automatic, account punishment never is.",
        "agents": ["Rider Advocate (tools, brief, rebuttal)", "Driver Advocate (tools, brief, rebuttal)", "Judge (no tools, rules only on open questions)", "Notice writer"],
        "dispute_categories": {"adjudicated": ["route deviation", "no-show fee"], "escalation_only": ["safety"]},
        "data": {
            "demo_cases": len([c for c in d["cases"] if c.startswith("C-")]),
            "benchmark_cases": n,
            "audit_variants": len(d["inject"]) + len(d["counterfactual"]),
            "nature": "synthetic trips on real OneMap road geometry; GPS traces simulated; no real rider or driver",
        },
        "policy": {"clauses": d["policy"]["policy_clauses"], "citable": d["policy"]["citable"], "informational": d["policy"]["informational"], "open_gaps": d["policy"]["gaps"]},
        "metrics": [
            {"name": "exact core decision, one model call",
             "value": f"{cnt(fo['exact'])}/{n} ({fo['exact']*100:.1f}%)",
             "comparator": f"{cnt(raw['exact'])}/{n} ({raw['exact']*100:.1f}%) with a raw case record, GPS thinned to {gps_s} s",
             "denominator": n, "scope": f"same DeepSeek model, one call each, {n} synthetic cases",
             "limitations": "measures the value of code-computed facts, not a contribution attributable to any one agent", "evidence_url": "/report.html"},
            {"name": "wrong core decisions that would execute",
             "value": f"{G['court']['wrong_and_executed']}/{n}",
             "comparator": f"{raw['wrong_executed']}/{n} for a raw single call with no execution check",
             "denominator": n, "scope": f"full court with the pre-execution policy check; {n} cases plus repeat runs",
             "limitations": "synthetic policy-conformance batch", "evidence_url": "/report.html"},
            {"name": "full court match to the policy-derived reference core decision",
             "value": f"{cnt(ct['exact'])}/{n}",
             "comparator": f"judge + policy check without advocates: {cnt(jo['exact'])}/{n}",
             "denominator": n, "scope": "outcome, amount to the cent, escalation",
             "limitations": "policy conformance, not production accuracy; reference answers derived from the written policy, no blind human labelling yet", "evidence_url": "/report.html"},
            {"name": "prototype routing",
             "value": f"{G['court']['auto']} auto-cleared, {G['court']['human_flow']} to a person, {flags} account flags to a person",
             "denominator": n, "scope": "eligibility decided by code after the ruling", "limitations": "not live Ryde volume", "evidence_url": "/ops.html"},
            {"name": "invalid citations",
             "value": f"{ct['invalid_citations'] + ct['invalid_fact_citations']} of {cites_ct:,} ({ct['fact_citations']} fact ids, {ct['citations']} clause ids)",
             "comparator": f"raw call: {raw['invalid_citations'] + raw['invalid_fact_citations']} of {cites_raw}, {raw['invalid_fact_citations']} invented fact ids",
             "scope": "court arm", "evidence_url": "/report.html"},
            *([{"name": "identity-swap invariance",
                "value": f"{ct['swap_invariance']*100:.0f}%", "comparator": f"raw call {raw['swap_invariance']*100:.1f}%",
                "scope": "rider and driver histories swapped", "evidence_url": "/report.html"}] if ct.get("swap_invariance") is not None else
              [{"name": "identity-swap invariance", "value": "not yet re-run on this version", "evidence_url": "/report.html"}]),
            *([{"name": "same ruling on repeat",
                "value": f"{ct['pass_all_repeats']*100:.1f}%", "scope": f"{ct['repeats']} runs of every case, full court", "evidence_url": "/report.html"}] if ct.get("pass_all_repeats") is not None else
              [{"name": "same ruling on repeat", "value": "not yet re-run on this version", "evidence_url": "/report.html"}]),
            {"name": "latency and cost",
             "value": f"{ct['latency_mean_s']} s mean, p95 {ct['latency_p95_s']} s, {ct['llm_calls_mean']:.0f} model calls, about {ct['input_tokens_mean']/1000:.0f}k input tokens per case",
             "comparator": f"raw single call {raw['latency_mean_s']} s, {raw['llm_calls_mean']:.0f} call", "evidence_url": "/report.html"},
        ],
        "boundaries": {
            "real": ["working API, UI and SSE event stream", "actual model runs", "deterministic fact and policy code", "sourced policy clauses with disclosed gaps", "OneMap road geometry", "reproducibility receipts", f"{d['tests']} automated tests"],
            "synthetic_or_simulated": ["riders, drivers, trips, GPS traces", f"{len([c for c in d['cases'] if c.startswith('C-')])} demo cases and {n} benchmark scenarios", "policy-derived reference outcomes", "traffic, congestion and weather values per scenario", "wallet, voucher and trust-and-safety integrations"],
            "model_never_authorizes": ["facts or their values", "allowed outcomes or the amount", "execution of a refund", "account punishment", "automatic ruling on safety complaints"],
        },
        "pages": {"landing": "/", "guided_case": "/replay.html?case=C-0001", "facts": "/facts.html?case=DISP-002", "ops_handoff": "/ops.html", "results": "/report.html", "policy": "/policy.html", "expert_court": "/court.html", "architecture": "/architecture-system.png", "health": "/api/health", "receipt_example": "/api/runs/C-0001/receipt"},
        "live_runs": "off on the public site; `Run live` works on a local copy with DEEPSEEK_API_KEY set (README, Run it)",
        "evidence": [
            {"claim": "facts computed by code", "path": "core/facts/tools.py"},
            {"claim": "policy as code: allowed outcomes and amount formula", "path": "core/policy_engine.py"},
            {"claim": "citation and ruling checks", "path": "core/verify.py"},
            {"claim": "state machine, eligibility, fault injection", "path": "core/orchestrate.py"},
            {"claim": "reproducibility receipt", "path": "core/receipt.py"},
            {"claim": "benchmark and ablations", "path": "bench/results/summary.md"},
            {"claim": "sourced policy", "path": "policy/policy.md"},
        ],
        "source_repository": "https://github.com/kalitass/akina-court",
        "demo_video": None,
        "codebuddy_evidence": "conversation screenshots and a development reflection attached to the submission",
        "provenance": {
            "requested_model": (au or {}).get("requested_model", "deepseek-chat"), "api": "DeepSeek API (pydantic-ai)",
            "api_reported_model_in_audit_sample": (au or {}).get("provider_model_reported"),
            "benchmark_window_utc": window,
            "stored_runs": len(rows), "recorded_model_calls": sum(r["llm_calls"] for r in rows),
            "input_tokens_total": sum(r["input_tokens"] for r in rows),
            "audit_sample": au,
            "verify": "python bench/provenance.py --hashes", "doc": "README.md (Where the numbers come from)",
        },
    }


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
