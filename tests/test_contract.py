"""The data against its story.

Every benchmark scenario makes claims about its record ("accident on the bypassed stretch", "rider agreed before the
segment", "driver tapped I'm Here 600 m away"). data/synth/contract.py turns the scenario's conditions into a table of
those claims and measures the record against them with its own geometry (nothing from core/). This file runs that
contract over every committed case (bench, blind, the six demo cases and the organisers' sample), checks that the
one-line `hard` label promises the reference answer, and re-derives every reference answer from the raw record and
the scenario labels without the engine, so an engine bug and a reference bug cannot hide each other.

Cases whose committed record still fails its contract are listed in KNOWN_PENDING with the reason; the test asserts
the set of failing cases is exactly that list, so a fix must remove the entry and a new defect cannot slip in.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synth"))
import contract  # noqa: E402

MAIN = json.loads((ROOT / "data" / "bench" / "manifest.json").read_text())
BLIND = json.loads((ROOT / "data" / "bench" / "blind" / "manifest.json").read_text())
BENCH = [(ROOT / "data" / "bench" / "cases", c) for c in MAIN["cases"]] + [(ROOT / "data" / "bench" / "blind" / "cases", c) for c in BLIND["cases"]]
LOC = {  # the named stop places of data/synth/scenarios.py (the contract needs the coordinates, not the generator)
    "Paya Lebar Square": (1.3176, 103.8929), "Clementi Mall": (1.3149, 103.7645), "Parkway Parade": (1.3012, 103.9052),
    "Northpoint City": (1.4295, 103.8355), "Great World City": (1.2936, 103.8319), "Changi City Point": (1.3345, 103.9623),
}

# Committed records that do not yet tell their story. Regenerating them needs the OneMap token (new legs), so the gate
# in scenarios.py refuses them from now on and this table documents the debt. The outcome of none of them changes.
KNOWN_PENDING: dict = {}      # every committed case passes its contract; add an entry only with the defect and the fix it waits for


# Committed labels the checker cannot read; scenarios.py already carries the corrected text, the manifest follows at regeneration.
LABEL_PENDING: dict = {}      # every label states its outcome after '->'


def spec_of(entry: dict) -> dict:
    spec = dict(entry["conditions"])
    spec["kind"], spec["name"] = entry["type"], entry["name"]
    return spec


def failures(case_dir: Path, entry: dict) -> list[str]:
    raw = json.loads((case_dir / f"{entry['case_id']}.json").read_text())
    return contract.check(raw, contract.contract_for(spec_of(entry), LOC))


# ---------------------------------------------------------------------------- every benchmark record vs its contract

def test_every_benchmark_record_meets_its_contract_except_the_known_pending_ones():
    failing = {}
    for case_dir, entry in BENCH:
        errs = failures(case_dir, entry)
        if errs:
            failing[entry["case_id"]] = errs
    unexpected = {cid: errs for cid, errs in failing.items() if cid not in KNOWN_PENDING}
    assert not unexpected, "records that do not tell their story: " + json.dumps(unexpected, indent=1, ensure_ascii=False)
    fixed = sorted(set(KNOWN_PENDING) - set(failing))
    assert not fixed, f"{fixed} now meet their contract: remove them from KNOWN_PENDING"


@pytest.mark.parametrize("cid", sorted(KNOWN_PENDING))
def test_known_pending_defects_change_no_reference_answer(cid):
    """The pending records are wrong on the map or the page, never in the answer: their label still promises the reference."""
    entry = next(c for _, c in BENCH if c["case_id"] == cid)
    assert [e for e in contract.check_label(entry["hard"], entry["truth"]) if "does not state" not in e] == []


def test_contract_covers_every_scenario_condition():
    """Every condition key a scenario can carry is read by contract_for (a new condition cannot go unchecked)."""
    read = {"kind", "loops", "service", "consent", "stop", "incident", "band", "prior", "threat", "weather", "gps_tail_cut_s",
            "by", "park_m", "wait_s", "within_s", "here", "cancel_s", "driver", "prior_ns", "chat", "gps_hole_s", "policy", "recorded_by",
            "statement_threat", "name"}
    seen = {k for _, c in BENCH for k in c["conditions"]}
    assert seen <= read, seen - read


# ---------------------------------------------------------------------------- the hand-scripted demo cases and the organisers' sample

DEMO = {
    # data/synth/build_cases.py c0001: Orchard jam after an accident, consent to Cavenagh, 7-Eleven stop far off the route
    "C-0001": {"kind": "route_deviation", "segments": 2, "pricing": "metered", "consent": "before", "stop": "unnamed", "stop_segment": 1, "incident": "on_stretch",
               "band": 1, "prior": 0, "threat": None, "route_km_min": {0: 0.5}, "stretch_driven_max": {0: 0.5}},
    "C-0007": {"kind": "route_deviation", "segments": 2, "pricing": "metered", "consent": "before", "stop": "unnamed", "stop_segment": 1, "incident": "on_stretch",
               "band": 1, "prior": 0, "threat": None, "route_km_min": {0: 0.5}, "stretch_driven_max": {0: 0.5}},   # C-0001's trip; the rider's reply came as a voice message
    "C-0002": {"kind": "route_deviation", "segments": 1, "pricing": "metered", "consent": "none", "stop": "none", "incident": "none",
               "band": 0, "prior": 3, "threat": None, "statement_consistent": True, "route_km_min": {0: 1.0}},
    "C-0003": {"kind": "route_deviation", "segments": 1, "pricing": "metered", "consent": "before", "stop": "none", "incident": "on_stretch",
               "band": 1, "prior": 0, "threat": None, "route_km_min": {0: 1.0}, "stretch_driven_max": {0: 0.5}},
    "C-0004": {"kind": "no_show", "cancelled_by": "driver", "by": "driver", "tap": True, "tap_distance_m": (590, 640), "never_within_200m": True,
               "wait_after_tap_s": (0, 0), "prior_ns": 0, "fee_in_statement": True},
    "C-0005": {"kind": "no_show", "cancelled_by": "rider", "by": "rider", "cancel_s": 540, "driver": "at_pickup", "tap": True,
               "tap_distance_m": (0, 60), "prior_ns": 0, "fee_in_statement": True},
    "C-0006": {"kind": "safety", "chat": "driver_threat", "statement_threat": False, "segments": 0, "no_stops": True, "pricing": "fixed"},
    # the organisers' sample: 3-min sampling, platform-confirmed arrival at the pin, 8 min at the pin, record-stated parameters
    "DISP-002": {"kind": "no_show", "cancelled_by": "driver", "by": "driver", "tap": True, "tap_distance_m": (0, 10), "wait_after_tap_s": (480, 480),
                 "prior_ns": 0, "fee_in_statement": True, "grid_s": None, "fare_recomputed": False, "estimate_equals_route": False,
                 "policy": {"free_wait_min": 5, "no_show_threshold_min": 8, "cancellation_fee": 5.0}},
}


def _demo_contract(cid: str) -> dict:
    c = {"grid_s": 5, "chat_in_window": True, "estimate_equals_route": True, "fare_recomputed": True, "weather": None}
    c.update(DEMO[cid])
    return c


@pytest.mark.parametrize("cid", sorted(DEMO))
def test_demo_case_meets_its_hand_written_contract(cid):
    raw = json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text())
    c = _demo_contract(cid)
    errs = contract.check(raw, c)
    # the demo chat is hand-written prose, not the generator's templates: the consent / stop lines are checked here by hand
    if cid in ("C-0001", "C-0007"):
        errs = [e for e in errs if "no driver route request" not in e and "no rider reply" not in e and "never asked for a stop" not in e]
        chat = raw["chat"]
        assert "go round by Cavenagh" in chat[0]["text"] and chat[0]["from"] == "driver"
        if cid == "C-0001":
            assert chat[1]["from"] == "rider" and chat[1]["text"].startswith("Sure") and "7-Eleven" in chat[1]["text"]
        else:   # the rider's reply is the ASR transcript of a voice message ("711" is how the recogniser wrote 7-Eleven)
            assert chat[1]["from"] == "rider" and chat[1]["text"].startswith("Okay, sure") and "711" in chat[1]["text"]
        assert chat[1]["ts"] < raw["trip"]["pickup_at"]
    if cid == "C-0003":
        errs = [e for e in errs if "no driver route request" not in e and "no rider reply" not in e]
        chat = raw["chat"]
        assert "ECP" in chat[0]["text"] and chat[1]["from"] == "rider" and chat[1]["text"].startswith("Ok")
    if cid in ("C-0001", "C-0007"):
        errs = [e for e in errs if "stop=unnamed: the 7-Eleven is only" not in e]   # 1.27 km off the route: checked below with the real number
        stop = contract.stops(contract.slice_gps(raw["gps"], raw["trip"]["pickup_at"], raw["trip"]["dropoff_at"]),
                              exclude=((raw["trip"]["pickup"]["lat"], raw["trip"]["pickup"]["lon"]), (raw["trip"]["dropoff"]["lat"], raw["trip"]["dropoff"]["lon"])))
        assert len(stop) == 1 and contract.project(stop[0]["lat"], stop[0]["lon"], [tuple(p) for p in raw["route"]["polyline"]])[0] > 1000
    assert errs == [], errs


# ---------------------------------------------------------------------------- the label promises the reference

@pytest.mark.parametrize("entry", [c for _, c in BENCH], ids=lambda c: c["case_id"])
def test_hard_label_promises_the_reference_answer(entry):
    errs = contract.check_label(entry["hard"], entry["truth"])
    if entry["case_id"] in LABEL_PENDING:
        assert errs and all("does not state" in e for e in errs), (entry["case_id"], errs)
        return
    assert errs == []
    imp = contract.label_implications(entry["hard"])
    # "exempt" in the outcome means no refund for that segment: a one-segment label that says exempt cannot carry an amount
    if imp["ruling"] == {"no_action"}:
        assert not entry["truth"]["amount"], entry["case_id"]
        assert entry["truth"]["ruling"] in ("no_action",)


def test_every_hard_label_names_an_outcome():
    """A label the checker cannot read ('...' with no '->') would never be checked; every scenario must say what it expects."""
    for _, c in BENCH:
        if c["case_id"] in LABEL_PENDING:
            continue
        assert contract.label_implications(c["hard"])["ruling"], f"{c['case_id']}: hard label does not state the expected outcome"
    import re
    src = (ROOT / "data" / "synth" / "scenarios.py").read_text()
    for name, hard in re.findall(r'^\s*[RNS]\("([a-z0-9_]+)".*?hard="([^"]*)"', src, flags=re.M | re.S):
        assert contract.label_implications(hard)["ruling"], f"scenarios.py {name}: hard label does not state the expected outcome"


# ---------------------------------------------------------------------------- the reference, re-derived without the engine

import reference  # noqa: E402


@pytest.mark.parametrize("case_dir,entry", BENCH, ids=lambda x: x["case_id"] if isinstance(x, dict) else "")
def test_reference_answer_re_derives_without_the_engine(case_dir, entry):
    raw = json.loads((case_dir / f"{entry['case_id']}.json").read_text())
    want = json.loads((case_dir.parent / "expected" / f"{entry['case_id']}.json").read_text())
    got = reference.derive_reference(raw, entry["conditions"], entry["type"])
    assert got["ruling"] == want["ruling"], (entry["case_id"], got, want["ruling"])
    assert bool(got["flag_account"]) == bool(want["flag_account"]), entry["case_id"]
    if got["amount"] is None:
        assert not want["amount"], (entry["case_id"], want["amount"])
    else:
        assert abs(got["amount"] - want["amount"]) <= 0.015, (entry["case_id"], got["amount"], want["amount"])
    assert want == entry["truth"], f"{entry['case_id']}: expected file and manifest truth differ"


# ---------------------------------------------------------------------------- the typed promise of every scenario

def test_every_scenario_states_its_expected_answer_and_the_reference_keeps_it():
    """`expect` is the scenario's typed promise (ruling, flag); the manifest truth must keep it. The free-text `hard`
    label stays for the reader and is no longer parsed for the check."""
    import scenarios as S
    for blind, specs in ((False, S.SCENARIOS), (True, S.BLIND_SCENARIOS)):
        by_name = {c["name"]: c for _, c in BENCH if c["case_id"].startswith("X-" if blind else "B-")}
        for sp in specs:
            assert sp.get("expect"), f"{sp['name']}: no expect= in the scenario line"
            if sp["name"] in by_name:
                assert contract.check_expect(sp["expect"], by_name[sp["name"]]["truth"]) == [], (sp["name"], sp["expect"], by_name[sp["name"]]["truth"]["ruling"])
