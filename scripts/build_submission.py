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


def human_reasons(court_rows: list[dict]) -> dict:
    """Why the court's hand-offs happened, counted from the final rulings' grounds."""
    out = {"safety": 0, "undetermined": 0, "evidence": 0, "other": 0}
    for r in court_rows:
        ru = r["ruling"]
        if not ru.get("escalate"):
            continue
        if ru.get("safety_concern", "none") != "none":
            out["safety"] += 1
        elif any(sf.get("finding") == "undetermined" for sf in ru.get("segment_findings") or []):
            out["undetermined"] += 1
        elif ru.get("evidence_status", "sufficient") != "sufficient":
            out["evidence"] += 1
        else:
            out["other"] += 1
    return out


def blind_numbers() -> Optional[dict]:
    """The held-out set's scores, when it has been run (bench/results/blind/<arm>/X-*.json)."""
    sys.path.insert(0, str(ROOT / "bench"))
    import blind_report
    man = ROOT / "data" / "bench" / "blind" / "manifest.json"
    res = ROOT / "bench" / "results" / "blind"
    if not man.exists() or not res.exists():
        return None
    truth = {c["case_id"]: c["truth"] for c in json.loads(man.read_text())["cases"]}
    out = {"cases": len(truth)}
    for arm in sorted(p.name for p in res.iterdir() if p.is_dir()):
        files = [f for f in sorted(glob.glob(str(res / arm / "X-*.json"))) if not f.endswith(".record.json") and ".r" not in Path(f).name[6:]]
        if not files:
            continue
        ok = wrong = failed = 0
        for f in files:
            rec = json.loads(Path(f).read_text()); t = truth[rec["case_id"]]; ru = rec.get("ruling") or {}
            if not rec.get("ok"):
                failed += 1; continue
            if blind_report.exact(ru, t):
                ok += 1
            elif not ru.get("escalate"):
                wrong += 1
        out[arm] = {"exact": ok, "wrong_executed": wrong, "failed": failed}
    return out


def demo_numbers() -> dict:
    """Figures the landing page quotes from the demo cases themselves (never typed by hand)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.facts.tools import build_fact_table
    from core.schemas import Case
    exp = lambda cid: json.loads((ROOT / "data" / "expected" / f"{cid}.json").read_text())
    case = lambda cid: Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))
    c4 = build_fact_table(case("C-0004"))
    tap_m = next(f.value["m_from_pickup_at_tap"] for f in c4.facts if f.value and "m_from_pickup_at_tap" in f.value)
    stretch = json.loads((ROOT / "runs" / "C-0004~stretch.json").read_text())
    signals = sum(1 for f in stretch["facts"]["facts"] if (f.get("value") or {}).get("signal"))     # the one stored hearing with the bad-faith screen on
    return {"c0001_refund": exp("C-0001")["amount"], "c0007_refund": exp("C-0007")["amount"], "c0004_fee": exp("C-0004")["amount"], "c0004_tap_m": tap_m, "c0004_signals": signals,
            "disp002_fee": case("DISP-002").fare.cancellation_fee, "c0005_fee": exp("C-0005").get("amount") or case("C-0005").fare.cancellation_fee}


def build() -> dict:
    d = dashboard.load_all()
    S, G = d["summary"], d["gate"]["arms"]
    raw, fo, jo, ct = S["raw"], S["facts_only"], S["judge_only"], S["court"]
    n = ct["cases"]
    rows = run_files()
    ts = sorted(r["ts"] for r in rows)
    window = f"{ts[0][:16].replace('T', ' ')} to {ts[-1][11:16] if ts[-1][:10] == ts[0][:10] else ts[-1][:16].replace('T', ' ')} UTC"
    def cnt(arm: str) -> int:
        """Exact-match count for an arm: the number of ok cases whose core decision matched (never a rounded mean × 49)."""
        return sum(1 for v in S[arm]["per_case"].values() if v.get("exact"))
    au = audit()
    gps_s = round(d["gps_interval_s"] * d["gps_thin"])
    court_base = [r for r in rows if r["arm"] == "court" and not r.get("swap") and r.get("repeat", 0) == 0 and r.get("ok") and r.get("ruling")]
    failed_runs = sorted(f"{r['arm']}/{r['case_id']}" for r in rows if not (r.get("ok") and r.get("ruling")))
    flags = sum(1 for r in court_base if r["ruling"].get("flag_account") and not r["ruling"].get("escalate"))   # same rule as orchestrate: no action on an escalated case
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
        # machine-readable copy of every figure the pages may quote (tests/test_numbers.py scans the pages against it)
        "numbers": {
            "cases": n,
            "arms": {arm: {"exact": cnt(arm), "wrong_executed_single_call": S[arm].get("wrong_executed", 0), "core_wrong": G[arm]["core_wrong"],
                           # right, or handed to a person: only a wrong decision that executes counts against a system
                           "safe": n - S[arm].get("wrong_executed", 0),
                           "wrong_and_executed_with_gate": G[arm]["wrong_and_executed"], "auto": G[arm]["auto"], "human": G[arm]["human_flow"],
                           "blocked_by_gate": G[arm]["blocked_by_gate"]} for arm in ("raw", "facts_only", "judge_only", "court")},
            "court": {"auto": G["court"]["auto"], "human": G["court"]["human_flow"], "flags": flags,
                      "voucher": sum(1 for r in court_base if r["ruling"].get("ruling") in ("refund_full", "refund_partial", "fee_waived") and not r["ruling"].get("escalate")),
                      "no_refund": sum(1 for r in court_base if r["ruling"].get("ruling") == "no_action" and not r["ruling"].get("escalate")),
                      "latency_mean_s": ct["latency_mean_s"], "latency_p95_s": ct["latency_p95_s"],
                      "swap_invariance": ct.get("swap_invariance"), "pass_all_repeats": ct.get("pass_all_repeats")},
            "tests": d["tests"],
            "failed_runs": failed_runs,      # result files whose run produced no ruling: never counted as a decision
            # everything else a page may quote; scripts/sync_numbers.py writes these into README / index / i18n and
            # tests/test_numbers.py refuses any figure that is not one of them
            "per_arm": {arm: {"latency_mean_s": S[arm]["latency_mean_s"], "llm_calls_mean": S[arm]["llm_calls_mean"], "input_tokens_mean": S[arm]["input_tokens_mean"],
                              "cites_invalid": S[arm]["invalid_citations"] + S[arm]["invalid_fact_citations"], "cites_total": S[arm]["citations"] + S[arm]["fact_citations"]}
                        for arm in ("raw", "facts_only", "judge_only", "court")},
            "ratios": {"latency_x": round(ct["latency_mean_s"] / raw["latency_mean_s"]) if raw["latency_mean_s"] else None,
                       "tokens_x": round(ct["input_tokens_mean"] / raw["input_tokens_mean"]) if raw["input_tokens_mean"] else None,
                       "judge_only_token_share": round(ct["input_tokens_mean"] / jo["input_tokens_mean"]) if jo["input_tokens_mean"] else None},
            "types": {t: sum(1 for c in d["manifest"]["cases"] if c["type"] == t) for t in ("route_deviation", "no_show", "safety")},
            # how varied the set is: every case is one scenario line in data/synth/scenarios.py; its conditions are the
            # labels the generator injected (consent wording, stops, incidents, bands, weather, fare type, priors, waits ...)
            "scenarios": {"distinct": len({c["name"] for c in d["manifest"]["cases"]}),
                          "dimensions": len({k for c in d["manifest"]["cases"] for k in c["conditions"]}),
                          "condition_sets": len({json.dumps(c["conditions"], sort_keys=True) for c in d["manifest"]["cases"]})},
            "human_reasons": human_reasons(court_base),
            "provenance": {"runs": len(rows), "calls": sum(r.get("llm_calls", 0) for r in rows), "input_tokens_m": round(sum(r.get("input_tokens", 0) for r in rows) / 1e6, 1),
                           "window": window, "window_date": ts[0][:10], "http_calls": (au or {}).get("http_calls"), "audit_runs": (au or {}).get("runs"),
                           "audit_matched": (au or {}).get("matched_reference"), "served_model": (au or {}).get("provider_model_reported")},
            "blind": blind_numbers(),
            "policy": {"clauses": d["policy"]["policy_clauses"], "citable": d["policy"]["citable"], "informational": d["policy"]["informational"],
                       "gaps": d["policy"]["gaps"], "predicates": len({l.split()[1] for c in d["manifest"]["cases"] for l in c["certificate"] if l[:1] in "✓✗?–" and len(l.split()) > 1})},
            "demo": demo_numbers(),
        },
        "metrics": [
            {"name": "exact core decision, one model call",
             "value": f"{cnt('facts_only')}/{n} ({fo['exact']*100:.1f}%)",
             "comparator": f"{cnt('raw')}/{n} ({raw['exact']*100:.1f}%) with a raw case record, GPS thinned to {gps_s} s",
             "denominator": n, "scope": f"same DeepSeek model, one call each, {n} synthetic cases",
             "limitations": "measures the value of code-computed facts, not a contribution attributable to any one agent", "evidence_url": "/report.html"},
            {"name": "wrong core decisions that would execute",
             "value": f"{G['court']['wrong_and_executed']}/{n}",
             "comparator": f"{raw['wrong_executed']}/{n} for a raw single call with no execution check",
             "denominator": n, "scope": f"full court with the pre-execution policy check; {n} cases plus repeat runs",
             "limitations": "synthetic policy-conformance batch", "evidence_url": "/report.html"},
            {"name": "full court match to the policy-derived reference core decision",
             "value": f"{cnt('court')}/{n}",
             "comparator": f"judge + policy check without advocates: {cnt('judge_only')}/{n}",
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
            "stored_runs": len(rows), "recorded_model_calls": sum(r.get("llm_calls", 0) for r in rows),
            "input_tokens_total": sum(r.get("input_tokens", 0) for r in rows),
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
