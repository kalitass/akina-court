"""One linter for every case file: the physical and story rules a reader checks by eye, measured from the record alone.

    .venv/bin/python data/synth/lint.py                 # every committed case (bench, held-out, demos, the organisers' sample)
    .venv/bin/python data/synth/lint.py data/cases/C-0001.json

These rules hold for any case, generated or hand-written; nothing here reads a scenario. Scenario-specific claims (what
the chat says, where the stop is) are the contract's job (contract.py); format and arithmetic are validate.py's.
Each violation is "CODE: detail". The generator refuses to publish a case with a violation; tests/test_lint.py runs it
over every committed file.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from contract import ENDPOINT_RADIUS_M, STOP_MIN_S, hav_m, project, segments, stops, ts  # noqa: E402

TYPING_S = 10              # a driver's message is typed in the TYPING_S before its timestamp; the car must not move meanwhile
TYPING_MOVE_M = 12         # GPS jitter allowance while stationary
CONNECTOR_M = 160          # the straight hop from the road to a pin (OneMap snaps a pin to the nearest road of each route); beyond this the pin is wrong
MIN_BYPASS_KM = 0.3        # mirrors the engine: entry and exit closer than this along the route = an out-and-back spur
RETRACE_MAX = 0.5          # a loop without a stop in it must not re-drive more than half of the stretch it left
LAST_DATE = datetime(2026, 10, 9, 23, 59, 59)
BANDS = {1: (0, 9), 2: (10, 19), 3: (20, 29), 4: (30, 39), 5: (40, 49), 6: (50, 59), 7: (60, 69), 8: (70, 999)}
BAND_NEAR_M = 80           # a sample describes a road when it lies within this of the road's geometry
BAND_MIN_SAMPLES = 6
PLACE_WORDS = ("mall", "mrt", "centre", "center", "point", "hub", "city", "square", "junction", "airport", "terminal", "plaza", "one")


def band_level(gps, geom, w0: str, w1: str, min_samples: int = BAND_MIN_SAMPLES):
    """The LTA band of a road in a window, from the trace: median speed of the moving samples (>= 5 km/h) within
    BAND_NEAR_M of the geometry while the window is open; None when fewer than BAND_MIN_SAMPLES samples describe it.
    The generator writes bands with this function and the linter checks them with it."""
    on = [p["speed_kmh"] for p in gps if w0 <= p["ts"] <= w1 and p["speed_kmh"] >= 5 and project(p["lat"], p["lon"], geom)[0] <= BAND_NEAR_M]
    if len(on) < min_samples:
        return None
    med = statistics.median(on)
    return next(k for k, (lo, hi) in BANDS.items() if med <= hi + 0.999)


def _pos_at(gps, t: datetime, tol_s: int = 30):
    """GPS samples within tol_s of t (sorted by distance in time)."""
    return sorted((p for p in gps if abs((ts(p) - t).total_seconds()) <= tol_s), key=lambda p: abs((ts(p) - t).total_seconds()))


WARN_CODES = ("TYPING", "RETRACE")     # a reader may frown, the record stays consistent: reported, not refused


def lint_case(case: dict, warnings: bool = False) -> list[str]:
    """Violations ("CODE: detail"). The WARN_CODES are returned only with warnings=True."""
    out = _lint(case)
    return out if warnings else [e for e in out if e.split(":")[0] not in WARN_CODES]


def _lint(case: dict) -> list[str]:
    errs: list[str] = []
    bad = errs.append
    t, gps, chat = case["trip"], case["gps"], case.get("chat", [])
    poly = [tuple(p) for p in case["route"]["polyline"]]
    P = (t["pickup"]["lat"], t["pickup"]["lon"])
    D = (t["dropoff"]["lat"], t["dropoff"]["lon"])
    end = t.get("dropoff_at") or t.get("cancelled_at")
    acc = datetime.fromisoformat(t["accepted_at"])

    # ---- timeline: every timestamp in order, nothing after the sets were built
    times = {"accepted_at": t["accepted_at"], "pickup_at": t.get("pickup_at"), "dropoff_at": t.get("dropoff_at"),
             "cancelled_at": t.get("cancelled_at"), "driver_pressed_here_at": t.get("driver_pressed_here_at"), "filed_at": case["dispute"]["filed_at"]}
    for k, v in times.items():
        if v and datetime.fromisoformat(v).replace(tzinfo=None) > LAST_DATE:
            bad(f"DATE: {k} {v} is after {LAST_DATE:%Y-%m-%d}")
    if t.get("pickup_at") and t.get("dropoff_at") and not (t["accepted_at"] < t["pickup_at"] < t["dropoff_at"]):
        bad("ORDER: accepted < pickup < dropoff does not hold")
    for a, b in zip(gps, gps[1:]):
        if ts(b) <= ts(a):
            bad(f"ORDER: gps timestamps not increasing at {b['ts']}"); break
    for m in chat:
        if not (t["accepted_at"] <= m["ts"] <= end):
            bad(f"ORDER: chat at {m['ts']} outside the trip")
    for inc in case.get("traffic", {}).get("incidents", []):
        if inc["reported_at"] > end:
            bad(f"ORDER: incident reported at {inc['reported_at']} after the trip ended")

    # ---- the driver does not type while driving (position, not the speed field)
    for m in chat:
        if m.get("from") != "driver" or m.get("kind", "message") != "message":
            continue
        tm = datetime.fromisoformat(m["ts"])
        window = [p for p in gps if tm - timedelta(seconds=TYPING_S) <= ts(p) <= tm]
        near = _pos_at(gps, tm)
        if not window and near and abs((ts(near[0]) - tm).total_seconds()) > 15:
            continue                                            # sparse record (the organisers' sample): cannot judge
        if not window and near:
            window = near[:1]
        if window:
            ref = (window[0]["lat"], window[0]["lon"])
            moved = max(hav_m(ref, (p["lat"], p["lon"])) for p in window)
            after = [p for p in gps if tm < ts(p) <= tm + timedelta(seconds=5)]
            if after:
                moved = max(moved, hav_m(ref, (after[0]["lat"], after[0]["lon"])))
            if moved > TYPING_MOVE_M:
                bad(f"TYPING: driver message at {m['ts'][11:19]} while the car moved {moved:.0f} m in {TYPING_S} s: '{m['text'][:40]}'")

    # ---- route geometry: pins on the road, loops that go somewhere
    for name, a, b in (("pickup", poly[0], poly[1]), ("dropoff", poly[-1], poly[-2])):
        if hav_m(a, b) > CONNECTOR_M:
            bad(f"PIN: {name} pin is {hav_m(a, b):.0f} m from the road the route snaps to (max {CONNECTOR_M} m): move the place's coordinate")
    if t.get("pickup_at") and t.get("dropoff_at"):
        trip = [p for p in gps if t["pickup_at"] <= p["ts"] <= t["dropoff_at"]]
        segs = segments(trip, poly)
        st = stops(trip, exclude=(P, D))
        from contract import along_km
        cum = along_km(poly)
        for k, s in enumerate(segs, 1):
            inside_stop = any(s["start"] <= x["start"] <= s["end"] for x in st)
            if inside_stop:
                continue                                        # an out-and-back to a stop is the stop's own shape
            if s["route_km"] < MIN_BYPASS_KM:
                bad(f"SPUR: segment {k} leaves and rejoins the route within {s['route_km']:.2f} km (an out-and-back, not a different way)")
                continue
            stretch = [(p, km) for p, km in zip(poly, cum) if s["entry_km"] + 0.05 <= km <= s["exit_km"] - 0.05]
            inside = [(p["lat"], p["lon"]) for p in trip[s["i0"]:s["i1"] + 1]]
            if len(stretch) >= 2 and inside:
                total = sum(hav_m(stretch[i][0], stretch[i + 1][0]) for i in range(len(stretch) - 1))
                redriven = sum(hav_m(stretch[i][0], stretch[i + 1][0]) for i in range(len(stretch) - 1)
                               if min(hav_m(stretch[i][0], g) for g in inside) <= 60 and min(hav_m(stretch[i + 1][0], g) for g in inside) <= 60)
                if total and redriven / total > RETRACE_MAX:
                    bad(f"RETRACE: segment {k} re-drives {redriven / total:.0%} of the {s['route_km']:.2f} km stretch it claims to leave")

    # ---- traffic: a band the car drove must agree with the trace; an incident is not written for this trip
    for b in case.get("traffic", {}).get("speed_bands", []):
        geom = [tuple(p) for p in b.get("geometry") or []]
        if len(geom) < 2:
            continue
        lvl = band_level(gps, geom, b["window_start"], b["window_end"])
        if lvl is not None and lvl != b["speed_band"]:
            bad(f"BAND: {b['road_name']} says band {b['speed_band']} but the car's own speed on it in the window is band {lvl}")
    for inc in case.get("traffic", {}).get("incidents", []):
        for nm in (t["pickup"]["name"], t["dropoff"]["name"]):
            if nm and nm.lower() in inc["message"].lower() and any(w in nm.lower() for w in PLACE_WORDS):
                bad(f"TELL: incident text names the trip's own place '{nm}' (a bulletin names roads, not destinations)")
    return errs


def all_case_files() -> list[str]:
    out = []
    for d in ("data/bench/cases", "data/bench/blind/cases", "data/cases"):
        p = os.path.join(ROOT, d)
        out += sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith(".json"))
    return out


def main(argv: list[str]) -> int:
    files = argv or all_case_files()
    n_bad = 0
    for f in files:
        errs = lint_case(json.load(open(f)), warnings=True)
        if errs:
            n_bad += any(e.split(":")[0] not in WARN_CODES for e in errs)
            print(os.path.relpath(f, ROOT))
            for e in errs:
                print(("   warn " if e.split(":")[0] in WARN_CODES else "   ") + e)
    print(f"{len(files)} files, {n_bad} with violations")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
