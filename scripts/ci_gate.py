#!/usr/bin/env python3
"""Pull-request gate for changes to the ruling logic. No model is called; the gate checks that whoever changed the
logic has already re-run everything and committed results that belong to this exact code.

    python scripts/ci_gate.py origin/main            # base ref the PR targets (CI passes it)
    python scripts/ci_gate.py origin/main --force    # run the full gate even when no gated path changed

Every PR: the diff must not carry forbidden words (see FORBIDDEN).
A PR that touches a gated path (core/, policy/policy.md, data/rates.json, bench/baseline.py) must also pass:
  1. receipts — every stored demo run and every court / judge record on the benchmark set verifies
     against this tree (case, policy, code and model fingerprints); the code fingerprint covers core/, so this holds
     only when the runs were produced by this code. A judge-only record with an older code fingerprint still stands
     when the experiment is provably the same: the judge's input rebuilt on this tree hashes to the receipt's
     judge_prompt_sha256 and the judge's instructions and model factory are unchanged since the producing commit;
  2. completeness — every benchmark case has a successful result in all four systems, on the current result schema,
     with no failed runs and all stored demo runs present;
  3. pages — regenerating every derived file from the results leaves the committed files unchanged;
  4. score floor — the full court still executes no wrong decision and its right-or-handed-off share has not dropped
     below the base branch.
Exit code 1 on any failure; the report also goes to $GITHUB_STEP_SUMMARY when set.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_PROVIDER", "deepseek")        # the fingerprint names the model; no key is needed

GATED = ("core/", "policy/policy.md", "data/rates.json", "bench/baseline.py")
# assembled at runtime so that this file never spells the words it forbids
FORBIDDEN = tuple("".join(parts) for parts in (("cl", "aude"), ("anthr", "opic"), ("co", "dex"), ("/private/", "tmp/"), ("~/.cl", "aude")))
ARMS = ("raw", "facts_only", "judge_only", "court")
GENERATORS = ("bench/report.py", "bench/gate_ablation.py", "bench/dashboard.py", "bench/ops_page.py",
              "scripts/build_policy_page.py", "scripts/build_submission.py", "scripts/sync_numbers.py")
GENERATED = ("bench/results/summary.md", "bench/results/summary.json", "bench/results/gate_ablation.json",
             "web/report.html", "web/ops.html", "web/policy.html", "web/submission.json", "README.md", "web/index.html", "web/i18n.zh.js")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Z]{2,5}")     # the results page prints the time it was generated


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout


def changed_files(base: str) -> list[str]:
    return [l for l in sh("git", "diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines() if l]   # a file moved out of core/ is a change to core/


def check_traces(base: str) -> list[str]:
    text = sh("git", "diff", f"{base}...HEAD").lower()
    hits = [w for w in FORBIDDEN if w in text]
    return [f"the diff contains a forbidden word: {w}" for w in hits]


def _judge_input(case) -> str:
    """The judge's input for a judge-only run, rebuilt on this tree: fact table → policy trace → judge prompt (no advocates)."""
    from core.agents.judge import judge_prompt
    from core.facts.tools import build_fact_table
    from core.orchestrate import Hooks, empty_brief, trip_summary
    from core.policy_engine import evaluate
    table = build_fact_table(case); cert = evaluate(case, table)
    items = [f"{q.clause} for {q.subject}: {q.element} — {q.detail}" for q in cert.predicates if q.status == "judge"]
    if cert.insufficient:
        items.append(f"EVIDENCE: {cert.insufficient} — the only outcome is escalate; evidence_status = insufficient and evidence_gap says what is missing")
    briefs = [empty_brief(s, "judge-only ablation: no advocate") for s in ("rider", "driver")]
    jp = judge_prompt(case.dispute.model_dump(), trip_summary(case), table, briefs, {}, cert.lines(), items)
    pc = Hooks().judge_context()
    return jp + ("\n\n" + pc if pc else "")


_COMMIT_OF: dict[str, str | None] = {}
JUDGE_FILES = ("core/agents/judge.py", "core/llm.py")      # the judge's instructions and the model factory: not part of the prompt hash


def _commit_with_code_hash(h: str) -> str | None:
    """The most recent commit whose core/ fingerprint is `h` (searched over the last 300 commits), or None."""
    import shutil
    import tempfile
    import core.receipt as receipt
    if h in _COMMIT_OF:
        return _COMMIT_OF[h]
    found = None
    for c in sh("git", "rev-list", "--max-count=300", "HEAD").split():
        tmp = Path(tempfile.mkdtemp())
        try:
            tar = subprocess.run(["git", "archive", c, "core", "data/rates.json"], cwd=ROOT, capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", str(tmp)], input=tar, check=True)
            keep = receipt.ROOT
            try:
                receipt.ROOT = tmp
                if receipt.code_hash() == h:
                    found = c; break
            finally:
                receipt.ROOT = keep
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    _COMMIT_OF[h] = found
    return found


def _judge_only_equivalent(rec: dict, case, model: str) -> tuple[bool, str]:
    """A judge-only record whose code fingerprint is stale still stands when the experiment is the same: case, policy and
    model fingerprints match, the judge's input rebuilt on this tree hashes to the stored judge_prompt_sha256, and the
    judge's instructions and the model factory are unchanged since the commit that produced the record."""
    from core.receipt import _h, verify
    v = verify(rec.get("receipt"), case, model)
    changed = [k for k, ok in v["match"].items() if not ok]
    if changed != ["code_sha256"]:
        return False, v["status"]
    stored = (rec.get("receipt") or {}).get("judge_prompt_sha256")
    if not stored or _h(_judge_input(case).encode("utf-8")) != stored:
        return False, "the judge's input rebuilt on this tree differs from the one in the receipt — re-run"
    commit = _commit_with_code_hash(rec["receipt"]["code_sha256"])
    if commit is None:
        return False, "the receipt's code fingerprint matches no commit in recent history — re-run"
    diff = subprocess.run(["git", "diff", "--name-only", commit, "HEAD", "--", *JUDGE_FILES], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if diff:
        return False, f"the judge's instructions or model factory changed since {commit[:7]} ({', '.join(diff)}) — re-run"
    return True, f"same experiment: judge input identical, {' and '.join(JUDGE_FILES)} unchanged since {commit[:7]}"


def check_receipts() -> list[str]:
    from app.main import get_case
    from core.case_format import read_case
    from core.llm import describe_model
    from core.receipt import verify
    from core.schemas import Case
    bad: list[str] = []
    model = describe_model()
    for p in sorted((ROOT / "runs").glob("*.json")):
        if p.stem in ("precedents", "queue"):
            continue
        rec = json.loads(p.read_text())
        v = verify(rec.get("receipt"), Case.model_validate(get_case(rec["case_id"])), model)
        if not v["verified"]:
            bad.append(f"runs/{p.name}: {v['status']}")
    equivalent = 0
    for sub, cases in (("bench/results", "data/bench/cases"),):
        for arm in ("judge_only", "court"):
            for p in sorted((ROOT / sub / arm).glob("*.record.json")):
                rec = json.loads(p.read_text())
                case = Case.model_validate(read_case(ROOT / cases / f"{rec['case_id']}.json"))
                v = verify(rec.get("receipt"), case, model)
                if v["verified"]:
                    continue
                if arm == "judge_only":            # no advocates: the judge's input can be rebuilt and compared
                    ok, why = _judge_only_equivalent(rec, case, model)
                    if ok:
                        equivalent += 1; continue
                    bad.append(f"{sub}/{arm}/{p.name}: {why}")
                else:
                    bad.append(f"{sub}/{arm}/{p.name}: {v['status']}")
    if equivalent:
        print(f"  (receipts: {equivalent} judge-only record(s) carry an older code fingerprint but the same experiment: input rebuilt and identical, judge files unchanged)")
    return bad


def check_completeness() -> list[str]:
    from bench.run_bench import SCHEMA
    bad: list[str] = []
    for sub, cases, arms in (("bench/results", "data/bench/cases", ARMS),):
        ids = sorted(p.stem for p in (ROOT / cases).glob("*.json"))
        for arm in arms:
            for cid in ids:
                p = ROOT / sub / arm / f"{cid}.json"
                if not p.exists():
                    bad.append(f"{sub}/{arm}/{cid}.json missing"); continue
                r = json.loads(p.read_text())
                if not (r.get("ok") and r.get("ruling")):
                    bad.append(f"{sub}/{arm}/{cid}.json: run failed or has no ruling")
                elif r.get("ruling_schema") != SCHEMA:
                    bad.append(f"{sub}/{arm}/{cid}.json: ruling_schema {r.get('ruling_schema')} ≠ {SCHEMA}")
                if arm in ("judge_only", "court") and not (ROOT / sub / arm / f"{cid}.record.json").exists():
                    bad.append(f"{sub}/{arm}/{cid}.record.json missing")
    from scripts.prerecord_demos import DEMOS
    stored = [f"{p.stem}.json" for p in sorted((ROOT / "data" / "cases").glob("*.json"))] + [f"{case}~{k}.json" for k, (case, _) in DEMOS.items()]
    for name in stored:
        if not (ROOT / "runs" / name).exists():
            bad.append(f"runs/{name} missing")
    return bad


def check_pages() -> list[str]:
    before = {f: _norm(f) for f in GENERATED}
    for g in GENERATORS:
        r = subprocess.run([sys.executable, str(ROOT / g)], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            return [f"{g} failed: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode}"]
    bad = [f"{f} is stale: regenerating it from the results changes it" for f in GENERATED if before[f] != _norm(f)]
    subprocess.run(["git", "checkout", "--", *GENERATED], cwd=ROOT, capture_output=True)     # leave the tree as committed
    return bad


def _norm(rel: str) -> str:
    p = ROOT / rel
    return STAMP.sub("<stamp>", p.read_text(encoding="utf-8")) if p.exists() else ""


def check_scores(base: str) -> tuple[list[str], list[str]]:
    cur = json.loads((ROOT / "web" / "submission.json").read_text())["numbers"]
    try:
        old = json.loads(sh("git", "show", f"{base}:web/submission.json"))["numbers"]
    except subprocess.CalledProcessError:
        old = None
    bad, lines = [], ["| system | right or handed off | exact | wrong decisions executed | cleared |", "|---|---|---|---|---|"]
    for arm in ARMS:
        c = cur["arms"][arm]
        o = old["arms"].get(arm) if old else None
        delta = lambda k: f"{c[k]}" + (f" ({c[k] - o[k]:+d})" if o else "")
        lines.append(f"| {arm} | {delta('safe')}/{cur['cases']} | {delta('exact')} | {delta('wrong_executed_single_call')} | {delta('auto')} |")
    court = cur["arms"]["court"]
    if court["wrong_executed_single_call"] != 0:
        bad.append(f"the full court executes {court['wrong_executed_single_call']} wrong decision(s); the floor is 0")
    if old and court["safe"] / cur["cases"] < old["arms"]["court"]["safe"] / old["cases"]:      # a share: the set itself may have changed size
        bad.append(f"the full court's right-or-handed-off share dropped from {old['arms']['court']['safe']}/{old['cases']} to {court['safe']}/{cur['cases']}")
    return bad, lines


def main(argv: list[str]) -> int:
    base = next((a for a in argv if not a.startswith("--")), "origin/main")
    force = "--force" in argv
    out: list[str] = []
    problems = check_traces(base)
    out.append(f"trace scan: {'clean' if not problems else 'FAILED'}")
    changed = changed_files(base)
    gated = [f for f in changed if any(f.startswith(g) for g in GATED)]
    if not gated and not force:
        out.append("ruling-logic gate: skipped (no change under " + ", ".join(GATED) + ")")
    else:
        out.append("ruling-logic gate: " + (", ".join(gated) if gated else "forced"))
        for name, fn in (("receipts", check_receipts), ("completeness", check_completeness), ("pages", check_pages)):
            bad = fn()
            problems += bad
            out.append(f"  {name}: {'ok' if not bad else f'{len(bad)} problem(s)'}")
            out.extend("    - " + b for b in bad[:25])
        bad, table = check_scores(base)
        problems += bad
        out.append(f"  score floor: {'ok' if not bad else 'FAILED'}")
        out.extend("    - " + b for b in bad)
        out.extend(table)
    text = "\n".join(out)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text("## Ruling-logic gate\n\n```\n" + text + "\n```\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
