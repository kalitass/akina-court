"""Every judge-facing figure comes from the benchmark files, through one script, and no page carries a figure by hand.

Source of truth: scripts/build_submission.py `numbers` (derived from bench/results/ and the data files).
Writer: scripts/sync_numbers.py fills the <!--n:...--> markers in README.md and web/index.html, regenerates the charts
and the meta description, and renders web/i18n.zh.src.js into web/i18n.zh.js.
These tests fail until `scripts/sync_numbers.py` has been run on the current results — by design.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_submission  # noqa: E402


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def built():
    return build_submission.build()


def test_submission_json_matches_benchmark_files(built):
    committed = json.loads((ROOT / "web" / "submission.json").read_text())
    for d in (built, committed):
        d.pop("generated_at", None)
    assert committed == built, "web/submission.json is stale: run scripts/build_submission.py"


def test_pages_carry_the_synced_numbers():
    """README, index and the Chinese dictionary equal what scripts/sync_numbers.py renders from today's numbers."""
    sync = _mod("sync_numbers")
    n = sync.numbers()
    stale = [str(p.relative_to(ROOT)) for p, text in sync.outputs(n).items() if p.read_text() != text]
    assert not stale, f"run scripts/sync_numbers.py: {stale}"
    if shutil.which("node"):
        assert subprocess.run(["node", "--check", str(ROOT / "web" / "i18n.zh.js")], capture_output=True).returncode == 0


# ---------------------------------------------------------------------------- no figure by hand

ALLOWED = ("179 s", "181 s", "$1 ", "$99", "90-day", "200 m", "5 s", "3 min", "8-minute", "20-second", "90 seconds", "30 m",
           "3 agents", "2 adjudicated", "0.2 km", "120 s", "2 minutes", "3 minutes", "30 days", "2026", "SG 2026", "7 more stored audits",
           "two layers", "11 clauses", "17 citable", "4 informational", "13 rules", "21 clauses", "$6.61", "$5.00", "6:61")
FIGURE = re.compile(r"\b\d{1,3}\s*/\s*\d{1,3}\b"            # fractions such as 42/49
                    r"|\b\d+(?:\.\d+)?\s*(?:s|seconds)\s+per\b"   # latency per case
                    r"|\b\d+\s+(?:automated\s+)?tests\b"           # test counts
                    r"|\b\d{2,3}%"                                  # percentages
                    r"|\$\d+\.\d\d"                                 # money
                    r"|\b\d+(?:,\d{3})+\b"                          # 1,234-style counts
                    r"|\b\d+(?:\.\d)?\s*M\s+input\b"                 # token totals
                    r"|\d+\s*(?:件|桩|个案例|个合成)")                      # Chinese counters (cases, disputes)


def _strip_generated(text: str) -> str:
    text = re.sub(r"<!--n:[^>]*-->.*?<!--/n-->", " § ", text, flags=re.S)
    text = re.sub(r"<!--chart:[a-z_]+-->.*?<!--/chart-->", " § ", text, flags=re.S)
    text = re.sub(r"<!--gen:[a-z_]+-->.*?<!--/gen-->", " § ", text, flags=re.S)
    text = re.sub(r"<style>.*?</style>|<script[^>]*>.*?</script>", " ", text, flags=re.S)
    return text


@pytest.mark.parametrize("page", ["README.md", "web/index.html", "web/i18n.zh.src.js"])
def test_no_figure_is_typed_by_hand(page):
    text = _strip_generated((ROOT / page).read_text())
    if page.endswith(".src.js"):
        text = re.sub(r"\{n:[^}]+\}", " § ", text)
    bad = [m.group(0) for m in FIGURE.finditer(text) if not any(a in text[max(0, m.start() - 12):m.end() + 12] for a in ALLOWED)]
    assert not bad, f"{page}: figures outside <!--n:...--> markers (add a marker or a `numbers` key): {bad}"


# ---------------------------------------------------------------------------- the result files agree with each other

def test_summary_and_gate_ablation_agree(built):
    """report.py and gate_ablation.py were run on the same results: per arm, cases − exact == core_wrong."""
    n = built["numbers"]
    for arm, a in n["arms"].items():
        assert n["cases"] - a["exact"] == a["core_wrong"] + len([f for f in n["failed_runs"] if f.startswith(arm + "/")]), \
            f"{arm}: summary.json says {a['exact']} exact but gate_ablation.json says {a['core_wrong']} wrong — run bench/report.py and bench/gate_ablation.py back to back"


def test_no_benchmark_run_is_marked_failed(built):
    """A run saved with ok:false (a model stage never answered) is not a result. Re-run it with
    bench/run_bench.py --cases <id> --arms <arm> --force before the pages are published."""
    assert not built["numbers"]["failed_runs"], f"re-run these: {built['numbers']['failed_runs']}"
    blind = built["numbers"].get("blind") or {}
    bad = {arm: v["failed"] for arm, v in blind.items() if isinstance(v, dict) and v.get("failed")}
    assert not bad, f"held-out set has failed runs per arm {bad}: re-run with --set blind --cases ... --force"


def test_every_auto_cleared_court_record_says_what_would_change_it():
    for p in sorted((ROOT / "bench" / "results" / "court").glob("B-*.record.json")):
        rec = json.loads(p.read_text())
        elig = rec.get("eligibility") or {}
        if elig.get("auto"):
            assert elig.get("what_would_change"), f"{p.name}: auto-cleared with no 'what would change' sentence"


def test_bench_court_records_are_the_bare_court():
    """No precedent, SLA or bad-faith stretch event inside a benchmark hearing (the flags are neutralised by the runner)."""
    for p in sorted((ROOT / "bench" / "results" / "court").glob("B-*.record.json")):
        rec = json.loads(p.read_text())
        titles = [e.get("title", "") for e in rec.get("events", [])]
        assert not any(t.startswith(("Precedent", "Bad-faith")) for t in titles), (p.name, [t for t in titles if t.startswith(("Precedent", "Bad-faith"))])


def test_stored_demo_runs_match_the_expected_answers():
    """The landing page quotes data/expected amounts while the replay plays runs/<case>.json: both must say the same.
    Fails until scripts/run_case.py all has been re-run on the current code and data — by design."""
    for p in sorted((ROOT / "data" / "expected").glob("C-*.json")):
        exp = json.loads(p.read_text())
        run = ROOT / "runs" / p.name
        assert run.exists(), f"{run} missing: run scripts/run_case.py all"
        got = json.loads(run.read_text())["ruling"]
        assert got["ruling"] == exp["ruling"] and bool(got.get("escalate")) == bool(exp.get("escalate")), (p.name, got["ruling"], exp["ruling"])
        assert abs(round(float(got.get("amount") or 0) * 100) - round(float(exp.get("amount") or 0) * 100)) <= 1, (p.name, got.get("amount"), exp.get("amount"))
