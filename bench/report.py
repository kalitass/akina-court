#!/usr/bin/env python3
"""Metrics over bench/results/<arm>/*.json against data/bench/expected + manifest.

    .venv/bin/python bench/report.py                 # -> bench/results/summary.md + summary.json, prints the tables

Per arm: ruling accuracy, amount accuracy (±$0.01 / ±$0.50), escalate accuracy, flag_account accuracy, citation
validity (cited clause ids exist and are citable), policy-set recall (expected clauses ⊆ cited), mean / p95 latency,
mean input / output tokens, errors; consistency across repeats (same-ruling rate and pass^N); identity-swap
invariance (same ruling as the <arm>_swap run); accuracy by dispute type; a per-case diff table.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.policy import citable_ids, policy_clauses  # noqa: E402
from core.facts.tools import build_fact_table  # noqa: E402
from core.schemas import Case  # noqa: E402

_FACT_IDS: dict[str, set] = {}


def fact_ids(cid: str) -> set:
    if cid not in _FACT_IDS:
        p = BENCH / "cases" / f"{cid}.json"
        _FACT_IDS[cid] = build_fact_table(Case.model_validate(json.loads(p.read_text()))).ids() if p.exists() else set()
    return _FACT_IDS[cid]

BENCH = ROOT / "data" / "bench"
RESULTS = ROOT / "bench" / "results"
ARMS = ("raw", "facts_only", "judge_only", "court")


def load_results() -> dict[str, dict[str, list[dict]]]:
    """{arm: {case_id: [records sorted by repeat]}} for every arm directory (including *_swap)."""
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    if not RESULTS.exists():
        return out
    for d in sorted(p for p in RESULTS.iterdir() if p.is_dir()):
        for p in sorted(d.glob("B-*.json")):
            if p.name.endswith(".record.json"):
                continue
            try:
                rec = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            rp = p.with_name(p.name[:-5] + ".record.json")
            if rp.exists():
                try:
                    rec["eligibility"] = json.loads(rp.read_text()).get("eligibility")
                except json.JSONDecodeError:
                    pass
            out[d.name][rec["case_id"]].append(rec)
    for arm in out:
        for cid in out[arm]:
            out[arm][cid].sort(key=lambda r: r.get("repeat", 0))
    return out


def load_truth() -> tuple[dict[str, dict], dict[str, dict]]:
    expected = {p.stem: json.loads(p.read_text()) for p in sorted((BENCH / "expected").glob("B-*.json"))}
    manifest = {m["case_id"]: m for m in json.loads((BENCH / "manifest.json").read_text())["cases"]} if (BENCH / "manifest.json").exists() else {}
    return expected, manifest


def amt_eq(a, b, tol) -> bool:
    a = 0.0 if a is None else float(a)
    b = 0.0 if b is None else float(b)
    return abs(round(a * 100) - round(b * 100)) <= round(tol * 100)   # compared in whole cents: ±$0.01 means one cent, never a float hair


def model_escalated(r: dict) -> bool:
    """The arm's own ruling sent the case to a person: the flag or the outcome label says so. One definition for every
    scorer, so a ruling such as refund_partial + escalate=True lands in the same bucket in summary.json and gate_ablation.json."""
    return bool(r.get("escalate")) or r.get("ruling") == "escalate"


def has_flag(r: dict) -> bool:
    """Structured field when the run produced one; legacy runs fall back to the text, excluding 'no flag_account'."""
    if "flag_account" in r and r["flag_account"] is not None:
        return bool(r["flag_account"])
    txt = r.get("recommended_action") or ""
    return bool(re.search(r"(?<!no )(?<!without )\bflag_account\b", txt))


def p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]


REFUNDS = ("refund_full", "refund_partial", "fee_waived")
CLASSES = ("refund_full", "refund_partial", "fee_waived", "no_action", "escalate")


def score(rec: dict, exp: dict, citable: set, known: set) -> dict:
    r = rec.get("ruling") or {}
    cited = r.get("cited_policy") or []
    cited_f = r.get("cited_facts") or []
    fids = fact_ids(rec.get("case_id", ""))
    out = {
        "fact_cite_n": len(cited_f), "fact_cite_invalid_n": sum(1 for f in cited_f if f not in fids),
        "cite_valid_all": all(c in citable for c in cited) and all(f in fids for f in cited_f),
        "ruling": r.get("ruling") == exp["ruling"],
        "amount_1c": amt_eq(r.get("amount"), exp.get("amount"), 0.01),
        "amount_50c": amt_eq(r.get("amount"), exp.get("amount"), 0.50),
        "escalate": model_escalated(r) == bool(exp.get("escalate")),
        "cite_valid": all(c in citable for c in cited) if cited else True,
        "cite_invalid_n": sum(1 for c in cited if c not in citable),
        "cite_n": len(cited),
        "policy_recall": (len(set(exp.get("cited_policy", [])) & set(cited)) / len(exp["cited_policy"])) if exp.get("cited_policy") else 1.0,
        "policy_superset": set(exp.get("cited_policy", [])) <= set(cited),
    }
    if "flag_account" in exp and not exp.get("escalate"):
        out["flag"] = has_flag(r) == bool(exp["flag_account"])
    out["exact"] = out["ruling"] and out["amount_1c"] and out["escalate"]
    out["refund_due"] = exp["ruling"] in REFUNDS
    out["got_class"] = r.get("ruling") or "none"
    out["exp_class"] = exp["ruling"]
    out["abs_err"] = abs(float(r.get("amount") or 0) - float(exp.get("amount") or 0))
    # "executed": the arm would have acted on this ruling without a human. Single-call arms have no gate, so anything
    # that is not an escalation is executed; the court executes only what the certificate marks auto-eligible.
    elig = rec.get("eligibility")
    out["executed"] = (bool(elig.get("auto")) if isinstance(elig, dict) else rec.get("status") == "resolved") if "status" in rec or elig is not None \
        else (r.get("ruling") is not None and not model_escalated(r))
    out["wrong_executed"] = out["executed"] and not out["exact"]
    return out


def class_metrics(scores: dict) -> dict:
    """Confusion matrix + per-class precision / recall / F1 over the ruling label."""
    conf = {c: {d: 0 for d in CLASSES + ("none",)} for c in CLASSES}
    for s in scores.values():
        conf.setdefault(s["exp_class"], {d: 0 for d in CLASSES + ("none",)})
        conf[s["exp_class"]][s["got_class"] if s["got_class"] in CLASSES else "none"] += 1
    per = {}
    for c in CLASSES:
        tp = conf[c][c]
        fn = sum(conf[c].values()) - tp
        fp = sum(conf[e][c] for e in conf if e != c)
        if tp + fn == 0 and fp == 0:
            continue
        pr = tp / (tp + fp) if tp + fp else None
        rc = tp / (tp + fn) if tp + fn else None
        f1 = (2 * pr * rc / (pr + rc)) if pr and rc else 0.0
        per[c] = {"support": tp + fn, "tp": tp, "fp": fp, "fn": fn, "precision": pr, "recall": rc, "f1": f1}
    present = [v for v in per.values() if v["support"]]
    macro = {"precision": mean(v["precision"] for v in present if v["precision"] is not None),
             "recall": mean(v["recall"] for v in present), "f1": mean(v["f1"] for v in present)} if present else {}
    exp_refund = [s for s in scores.values() if s["exp_class"] in REFUNDS]
    exp_norefund = [s for s in scores.values() if s["exp_class"] not in REFUNDS]
    return {"confusion": conf, "per_class": per, "macro": macro,
            # money-facing errors a platform cares about
            "wrongful_refund_rate": mean(s["got_class"] in REFUNDS for s in exp_norefund) if exp_norefund else None,
            "missed_refund_rate": mean(s["got_class"] not in REFUNDS for s in exp_refund) if exp_refund else None,
            "refund_precision": per.get("refund_full", {}).get("precision"),
            "amount_1c_refund_cases": mean(s["amount_1c"] for s in scores.values() if s["refund_due"]) if exp_refund else None,
            "refund_cases": len(exp_refund),
            "money_error_mean": mean(s["abs_err"] for s in scores.values()),
            "money_error_total": sum(s["abs_err"] for s in scores.values()),
            "executed_rate": mean(s["executed"] for s in scores.values()),
            "wrong_executed": sum(s["wrong_executed"] for s in scores.values()),
            "wrong_executed_rate": mean(s["wrong_executed"] for s in scores.values()),
            "human_review_rate": mean(not s["executed"] for s in scores.values())}


def mean(xs) -> float:
    xs = list(xs)
    return statistics.fmean(xs) if xs else 0.0


def arm_metrics(arm: str, runs: dict[str, list[dict]], swap_runs: dict[str, list[dict]], expected: dict, manifest: dict,
                citable: set, known: set) -> dict:
    primary = {cid: recs[0] for cid, recs in runs.items() if recs}
    ok = {cid: r for cid, r in primary.items() if r.get("ok") and cid in expected}
    scores = {cid: score(r, expected[cid], citable, known) for cid, r in ok.items()}
    m = {"arm": arm, "cases": len(primary), "ok": len(ok), "errors": len(primary) - len(ok),
         "error_list": sorted(f"{cid}: {r.get('error')}" for cid, r in primary.items() if not r.get("ok"))}
    if not scores:
        return m
    for k in ("ruling", "amount_1c", "amount_50c", "escalate", "exact", "cite_valid", "policy_superset"):
        m[k] = round(mean(s[k] for s in scores.values()), 3)
    m["policy_recall"] = round(mean(s["policy_recall"] for s in scores.values()), 3)
    flags = [s["flag"] for s in scores.values() if "flag" in s]
    m["flag"] = round(mean(flags), 3) if flags else None
    m.update(class_metrics(scores))
    m["invalid_citations"] = sum(s["cite_invalid_n"] for s in scores.values())
    m["citations"] = sum(s["cite_n"] for s in scores.values())
    m["fact_citations"] = sum(s["fact_cite_n"] for s in scores.values())
    m["invalid_fact_citations"] = sum(s["fact_cite_invalid_n"] for s in scores.values())
    m["cite_valid_all"] = round(mean(s["cite_valid_all"] for s in scores.values()), 3)
    lat = [r["latency_s"] for r in ok.values()]
    m["latency_mean_s"] = round(mean(lat), 1)
    m["latency_p95_s"] = round(p95(lat), 1)
    m["input_tokens_mean"] = round(mean(r.get("input_tokens", 0) for r in ok.values()))
    m["output_tokens_mean"] = round(mean(r.get("output_tokens", 0) for r in ok.values()))
    m["llm_calls_mean"] = round(mean(r.get("llm_calls", 0) for r in ok.values()), 1)
    # by type
    by_type = defaultdict(list)
    for cid, s in scores.items():
        by_type[manifest.get(cid, {}).get("type", "?")].append(s["ruling"])
    m["ruling_by_type"] = {t: f"{sum(v)}/{len(v)}" for t, v in sorted(by_type.items())}
    # consistency across repeats
    multi = {cid: [r for r in recs if r.get("ok")] for cid, recs in runs.items() if len(recs) > 1}
    multi = {cid: recs for cid, recs in multi.items() if len(recs) > 1 and cid in expected}
    if multi:
        same = [len({r["ruling"]["ruling"] for r in recs}) == 1 for recs in multi.values()]
        passn = [all(r["ruling"]["ruling"] == expected[cid]["ruling"] for r in recs) for cid, recs in multi.items()]
        m["consistency_cases"] = len(multi)
        m["repeats"] = max(len(recs) for recs in multi.values())
        m["same_ruling_rate"] = round(mean(same), 3)
        m["pass_all_repeats"] = round(mean(passn), 3)
    # identity swap invariance
    both = [cid for cid in ok if swap_runs.get(cid) and swap_runs[cid][0].get("ok")]
    if both:
        inv = [ok[cid]["ruling"]["ruling"] == swap_runs[cid][0]["ruling"]["ruling"] for cid in both]
        m["swap_cases"] = len(both)
        m["swap_invariance"] = round(mean(inv), 3)
        m["swap_flips"] = [cid for cid, v in zip(both, inv) if not v]
    m["per_case"] = {cid: {**s, "got": ok[cid]["ruling"]} for cid, s in scores.items()}
    return m


def fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.1%}" if 0 <= v <= 1 else f"{v:.1f}"
    return str(v)


def cell(rec: dict | None, exp: dict) -> str:
    if rec is None:
        return "·"
    if not rec.get("ok"):
        return "ERR"
    r = rec["ruling"]
    amt = f" ${r['amount']:.2f}" if r.get("amount") is not None else ""
    flag = "+flag" if has_flag(r) else ""
    ok = r.get("ruling") == exp["ruling"] and amt_eq(r.get("amount"), exp.get("amount"), 0.01)
    return f"{'✓' if ok else '✗'} {r.get('ruling')}{amt}{flag}"


def build_report() -> tuple[str, dict]:
    expected, manifest = load_truth()
    results = load_results()
    citable, known = citable_ids(), set(policy_clauses())
    arms = [a for a in ARMS if a in results] + [a for a in results if a not in ARMS and not a.endswith("_swap")]
    metrics = {arm: arm_metrics(arm, results[arm], results.get(f"{arm}_swap", {}), expected, manifest, citable, known) for arm in arms}

    rows = [("cases scored (ok / run)", lambda m: f"{m.get('ok', 0)} / {m.get('cases', 0)}"),
            ("ruling accuracy", lambda m: fmt(m.get("ruling"))),
            ("  by type", lambda m: " ".join(f"{t}={v}" for t, v in m.get("ruling_by_type", {}).items()) or "–"),
            ("amount ±$0.01", lambda m: fmt(m.get("amount_1c"))),
            ("amount ±$0.50", lambda m: fmt(m.get("amount_50c"))),
            ("amount ±$0.01, refund cases only", lambda m: f"{fmt(m.get('amount_1c_refund_cases'))} (n={m.get('refund_cases', 0)})"),
            ("escalate accuracy", lambda m: fmt(m.get("escalate"))),
            ("exact (ruling+amount+escalate)", lambda m: fmt(m.get("exact"))),
            ("flag_account accuracy", lambda m: fmt(m.get("flag"))),
            ("macro precision / recall / F1 (ruling label)", lambda m: " / ".join(fmt(m.get("macro", {}).get(k)) for k in ("precision", "recall", "f1"))),
            ("wrongful refunds (refund where none was due)", lambda m: fmt(m.get("wrongful_refund_rate"))),
            ("missed refunds (no refund where one was due)", lambda m: fmt(m.get("missed_refund_rate"))),
            ("money error mean / total ($)", lambda m: f"{m.get('money_error_mean', 0):.2f} / {m.get('money_error_total', 0):.2f}"),
            ("executed without a human", lambda m: fmt(m.get("executed_rate"))),
            ("core decision wrong AND executed (cases; core = outcome + amount + escalation; raw / facts_only have no gate)", lambda m: f"{m.get('wrong_executed', 0)} ({fmt(m.get('wrong_executed_rate'))})"),
            ("routed to a human", lambda m: fmt(m.get("human_review_rate"))),
            ("citation validity, policy ids (rulings with no invalid clause id)", lambda m: fmt(m.get("cite_valid"))),
            ("citation validity, facts + policy (rulings with no invalid id)", lambda m: fmt(m.get("cite_valid_all"))),
            ("invalid / total policy citations", lambda m: f"{m.get('invalid_citations', 0)} / {m.get('citations', 0)}"),
            ("invalid / total fact citations", lambda m: f"{m.get('invalid_fact_citations', 0)} / {m.get('fact_citations', 0)}"),
            ("policy-set recall (mean)", lambda m: fmt(m.get("policy_recall"))),
            ("policy-set ⊇ expected", lambda m: fmt(m.get("policy_superset"))),
            ("latency mean / p95 (s)", lambda m: f"{m.get('latency_mean_s', '–')} / {m.get('latency_p95_s', '–')}"),
            ("input / output tokens (mean)", lambda m: f"{m.get('input_tokens_mean', '–')} / {m.get('output_tokens_mean', '–')}"),
            ("LLM calls per case (mean)", lambda m: str(m.get("llm_calls_mean", "–"))),
            ("consistency: same ruling across repeats", lambda m: f"{fmt(m.get('same_ruling_rate'))} (n={m.get('consistency_cases', 0)}, N={m.get('repeats', '–')})"),
            ("consistency: pass^N (all repeats correct)", lambda m: fmt(m.get("pass_all_repeats"))),
            ("identity-swap invariance", lambda m: f"{fmt(m.get('swap_invariance'))} (n={m.get('swap_cases', 0)})"),
            ("errors / timeouts", lambda m: str(m.get("errors", 0)))]
    lines = ["# Benchmark summary", "", f"Bench set: {len(expected)} cases (" +
             ", ".join(f"{t}={n}" for t, n in sorted(
                 ((t, sum(1 for m in manifest.values() if m['type'] == t)) for t in {m['type'] for m in manifest.values()}))) + "). "
             f"Models: {', '.join(sorted({r.get('model', '?') for a in results.values() for rs in a.values() for r in rs}))}.", "",
             "| metric | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for label, f in rows:
        lines.append(f"| {label} | " + " | ".join(f(metrics[a]) for a in arms) + " |")
    lines += ["", "## Per-class precision / recall (ruling label)", "", "| class | support | " + " | ".join(f"{a} P / R / F1" for a in arms) + " |", "|---|---|" + "---|" * len(arms)]
    for c in CLASSES:
        sup = max((metrics[a].get("per_class", {}).get(c, {}).get("support", 0) for a in arms), default=0)
        if not sup:
            continue
        lines.append(f"| {c} | {sup} | " + " | ".join(
            (lambda v: f"{fmt(v.get('precision'))} / {fmt(v.get('recall'))} / {fmt(v.get('f1'))}" if v else "–")(metrics[a].get("per_class", {}).get(c)) for a in arms) + " |")
    for a in arms:
        conf = metrics[a].get("confusion")
        if not conf:
            continue
        cols = [c for c in CLASSES if any(conf[e][c] for e in conf)] + (["none"] if any(conf[e]["none"] for e in conf) else [])
        lines += ["", f"### Confusion · {a} (rows = expected, columns = got)", "", "| expected \\ got | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        for e in CLASSES:
            if sum(conf[e].values()):
                lines.append(f"| {e} | " + " | ".join(str(conf[e][c]) for c in cols) + " |")
    lines += ["", "## Per-case diff", "", "| case | type | scenario | expected | " + " | ".join(arms) + " |", "|---|---|---|---|" + "---|" * len(arms)]
    for cid, exp in sorted(expected.items()):
        if not any(cid in results[a] for a in arms):
            continue
        amt = f" ${exp['amount']:.2f}" if exp.get("amount") is not None else ""
        flag = "+flag" if exp.get("flag_account") else ""
        lines.append(f"| {cid} | {manifest.get(cid, {}).get('type', '?')} | {manifest.get(cid, {}).get('name', '')} | {exp['ruling']}{amt}{flag} | "
                     + " | ".join(cell(results[a][cid][0] if results[a].get(cid) else None, exp) for a in arms) + " |")
    errs = [(a, e) for a in arms for e in metrics[a].get("error_list", [])]
    if errs:
        lines += ["", "## Errors", ""] + [f"- {a}: {e}" for a, e in errs]
    md = "\n".join(lines) + "\n"
    return md, metrics


def main():
    md, metrics = build_report()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.md").write_text(md, encoding="utf-8")
    (RESULTS / "summary.json").write_text(json.dumps(metrics, indent=1, ensure_ascii=False), encoding="utf-8")
    print(md)
    print(f"written {RESULTS / 'summary.md'} and summary.json")


if __name__ == "__main__":
    main()
