"""The generator is safe and deterministic: a scenario is identified by its name, a case rebuilds byte-for-byte from the
cached road legs, and the scenario list is append-only (a case keeps its id and date for ever)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synth"))
import scenarios as S  # noqa: E402

SETS = [(False, ROOT / "data" / "bench"), (True, ROOT / "data" / "bench" / "blind")]


def entries(blind: bool):
    return json.loads(((SETS[1][1] if blind else SETS[0][1]) / "manifest.json").read_text())["cases"]


@pytest.mark.parametrize("blind", [False, True])
def test_scenario_list_is_append_only(blind):
    """Manifest entry i is the i-th scenario of the list: inserting or reordering a scenario would renumber cases."""
    names = [sp["name"] for sp in (S.BLIND_SCENARIOS if blind else S.SCENARIOS)]
    assert len(names) == len(set(names)), "duplicate scenario names"
    for e in entries(blind):
        i = int(e["case_id"].split("-")[1])
        assert names[i - 1] == e["name"], f"{e['case_id']} is {e['name']} in the manifest but {names[i - 1]} in the list"


def test_identity_depends_on_the_name_only():
    a, b = S.identity("bench", "rd_basic"), S.identity("bench", "rd_basic")
    assert a["noise"] == b["noise"] and a["geo"].random() == b["geo"].random() and a["text"].random() == b["text"].random()
    assert S.identity("bench", "rd_basic")["noise"] != S.identity("blind", "rd_basic")["noise"]


REBUILD = [(blind, e) for blind, _ in SETS for e in entries(blind) if e.get("identity") == S.IDENTITY_VERSION]


@pytest.mark.parametrize("blind,entry", REBUILD, ids=[e["case_id"] for _, e in REBUILD])
def test_case_rebuilds_byte_for_byte_from_the_cache(blind, entry, monkeypatch):
    """No network: every leg of a published case is in onemap_cache.json, and the rebuild equals the committed record."""
    monkeypatch.delenv("ONEMAP_TOKEN", raising=False); monkeypatch.delenv("ONEMAP_EMAIL", raising=False); monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    specs = S.BLIND_SCENARIOS if blind else S.SCENARIOS
    i = int(entry["case_id"].split("-")[1])
    b = S.build_one(specs[i - 1], i, blind, S.load_rates(), S.validate.policy_clauses(), S.routes(), entry)   # entry: the pinned loop plan
    base = SETS[1][1] if blind else SETS[0][1]
    assert b["case"] == json.loads((base / "cases" / f"{entry['case_id']}.json").read_text())
    assert b["expected"] == json.loads((base / "expected" / f"{entry['case_id']}.json").read_text())
    got = json.loads(json.dumps(b["entry"]))            # tuples become lists on disk
    assert {k: v for k, v in got.items() if k != "validate_errors"} == {k: v for k, v in entry.items() if k != "validate_errors"}
