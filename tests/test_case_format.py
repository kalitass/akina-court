"""Case files are official-plus (core/case_format.py): the organisers' RydeResolve fields under their own names, plus ours.
The reader and the writer must be exact inverses on every committed case, and the organisers' samples must load as sent."""
import json
from pathlib import Path

import pytest

from core.case_format import is_official, load_official, read_case, to_internal, to_official
from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(p for d in ("data/cases", "data/bench/cases") for p in (ROOT / d).glob("*.json"))
SAMPLES = ("DISP-001", "DISP-002", "DISP-003")


def test_every_case_file_is_official_plus():
    assert FILES and [p.name for p in FILES if not is_official(json.loads(p.read_text()))] == []


def test_internal_to_official_plus_and_back_is_lossless():
    bad = []
    for p in FILES:
        internal = read_case(p)
        back = to_internal(to_official(internal))
        if back != internal or Case.model_validate(to_official(internal)) != Case.model_validate(internal):
            bad.append(p.stem)
    assert bad == []


def test_a_case_file_validates_in_either_shape():
    p = ROOT / "data" / "cases" / "C-0001.json"
    official, internal = json.loads(p.read_text()), read_case(p)
    assert Case.model_validate(official) == Case.model_validate(internal) == Case.model_validate_json(p.read_text())


@pytest.mark.parametrize("cid", SAMPLES)
def test_organisers_sample_loads_as_sent_and_the_case_file_keeps_every_official_field(cid):
    raw = load_official(ROOT / "data" / "samples" / f"{cid}.md")
    Case.model_validate(raw)                                        # the raw file, through the same path as every loader
    stored = json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text())
    for k, v in raw.items():
        if k == "case_metadata":                                    # we add provenance next to the official keys
            assert {kk: stored[k][kk] for kk in v} == v
        else:
            assert stored[k] == v, f"{cid}: official field {k} changed"


def test_the_official_v3_data_reaches_the_internal_case():
    d1, d2, d3 = (Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{c}.json").read_text())) for c in SAMPLES)
    assert d1.fare_detail.excess_distance_fare == 3.44 and d1.fare_detail.excess_tolls == 2.22 and d1.fare.quoted_total == 28.5
    assert [i.road for i in d1.traffic.road_incidents][0].startswith("PIE") and d1.traffic.road_incidents[0].cleared_at is not None
    assert len(d1.route.polyline) == 10 and d1.route.total_km == 20.5           # the record's own waypoints are the route
    assert d2.trip.scheduled_at.isoformat() == "2026-09-13T08:45:00+08:00" and d2.profiles.rider_account.fraud_flags == 1
    assert [(c.caller, c.callee) for c in d2.calls] == [("driver", "rider")]
    assert d3.dispute.type == "fare_dispute" and d3.fare.quoted_total == 12.0 and d3.fare.total == 16.5 and d3.fare.surge_multiplier == 1.5
    assert d3.fare_detail.upfront_quote.surge_multiplier == 1.0 and d3.fare_detail.surgeable_subtotal == 9.0
    assert d3.surge.rider_notified is False and d3.surge.trip_start_surge == 1.5
    assert d1.provenance["history_window"] == "all time"        # lifetime totals, not a 90-day window


def test_empty_v3_fields_leave_the_dump_unchanged():
    """A case that carries none of the v3 fields serialises (and so hashes, core/receipt.py) exactly as before they existed."""
    d = Case.model_validate(read_case(ROOT / "data" / "cases" / "C-0001.json")).model_dump(mode="json")
    assert not {"fare_detail", "surge", "calls"} & set(d) and "scheduled_at" not in d["trip"] and "road_incidents" not in d["traffic"]
    assert not {"rider_account", "driver_account"} & set(d["profiles"])
