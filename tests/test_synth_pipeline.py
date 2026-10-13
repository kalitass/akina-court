"""The generator is safe and deterministic: a scenario is identified by its name, a case rebuilds byte-for-byte from the
cached road legs, and every manifest entry is the scenario at its position in the list (a case keeps its id and date)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synth"))
import scenarios as S  # noqa: E402

from core.case_format import to_official  # noqa: E402

BENCH = ROOT / "data" / "bench"
ENTRIES = json.loads((BENCH / "manifest.json").read_text())["cases"]
CAND = BENCH / "candidates"
CAND_ENTRIES = json.loads((CAND / "manifest.json").read_text())["cases"] if (CAND / "manifest.json").exists() else []


def test_manifest_follows_the_scenario_list():
    """Manifest entry i is the i-th scenario of the list and every scenario is published: inserting or reordering a
    scenario would renumber cases."""
    names = [sp["name"] for sp in S.SCENARIOS]
    assert len(names) == len(set(names)), "duplicate scenario names"
    assert [e["name"] for e in ENTRIES] == names
    assert [e["case_id"] for e in ENTRIES] == [f"B-{i:04d}" for i in range(1, len(names) + 1)]
    files = sorted(p.stem for p in (BENCH / "cases").glob("*.json"))
    assert files == sorted(p.stem for p in (BENCH / "expected").glob("*.json")) == [e["case_id"] for e in ENTRIES]


def test_every_entry_says_where_it_came_from():
    for e in ENTRIES:
        assert e.get("reused_from") == "new" or e["reused_from"].startswith(("B-", "X-", "cand ")), e["case_id"]


def test_identity_depends_on_the_name_only():
    a, b = S.identity("bench", "rd_basic"), S.identity("bench", "rd_basic")
    assert a["noise"] == b["noise"] and a["geo"].random() == b["geo"].random() and a["text"].random() == b["text"].random()
    assert S.identity("bench", "rd_basic")["noise"] != S.identity("blind", "rd_basic")["noise"]


def test_candidate_manifest_follows_the_candidate_list():
    names = [sp["name"] for sp in S.CANDIDATES]
    assert len(names) == len(set(names)) and not set(names) & {sp["name"] for sp in S.SCENARIOS}
    assert [e["name"] for e in CAND_ENTRIES] == names
    assert all(json.loads((CAND / "expected" / f"{e['case_id']}.json").read_text()).get("escalate_ok") for e in CAND_ENTRIES)


REBUILD = [("bench", BENCH, S.SCENARIOS, e) for e in ENTRIES if e.get("identity") == S.IDENTITY_VERSION] + \
          [("candidates", CAND, S.CANDIDATES, e) for e in CAND_ENTRIES if e.get("identity") == S.IDENTITY_VERSION]


@pytest.mark.parametrize("which,base,specs,entry", REBUILD, ids=[r[3]["case_id"] for r in REBUILD])
def test_case_rebuilds_byte_for_byte_from_the_cache(which, base, specs, entry, monkeypatch):
    """No network: every leg of a published case is in onemap_cache.json, and the rebuild equals the committed record.
    The engine-agreement gate is a separate question (SYNTH_SKIP_ENGINE_CHECK); the certificate it writes is not compared."""
    monkeypatch.delenv("ONEMAP_TOKEN", raising=False); monkeypatch.delenv("ONEMAP_EMAIL", raising=False); monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    monkeypatch.setattr(S, "SKIP_ENGINE", True)
    i = int(entry["case_id"].split("-")[1])
    b = S.build_one(specs[i - 1], i, S.load_rates(), S.validate.policy_clauses(), S.routes(), entry, which)   # entry: the pinned loop plan
    assert to_official(b["case"]) == json.loads((base / "cases" / f"{entry['case_id']}.json").read_text())   # the file on disk is official-plus
    assert b["expected"] == json.loads((base / "expected" / f"{entry['case_id']}.json").read_text())
    got = json.loads(json.dumps(b["entry"]))            # tuples become lists on disk
    skip = ("validate_errors", "certificate")
    assert {k: v for k, v in got.items() if k not in skip} == {k: v for k, v in entry.items() if k not in skip}
