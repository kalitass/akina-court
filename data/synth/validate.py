#!/usr/bin/env python3
"""Self-consistency checks for data/cases/*.json (+ data/expected/*.json). Exit 1 if any case fails.

    python3 data/synth/validate.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cases import ARRIVAL_RADIUS_M, MOVING_KMH, ROAD_NEAR_M, ROADS, SPEED_BANDS, measure_detours, project  # noqa: E402
from fare import FOLDED, POLICY_CANCELLATION_FEE, cancellation_fare, fixed_fare, load_rates, metered_fare, slice_gps, stationary_windows  # noqa: E402
from route_provider import haversine_m  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.case_format import read_case  # noqa: E402

CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cases")
EXPECTED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "expected")
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "policy", "policy.md")
NEAR_M = ROAD_NEAR_M            # a road / incident must sit within this of the actual trace OR of the optimal route
MAX_STEP_M = 125                # 5 s at 90 km/h; anything faster is a synthesis bug
HELP_CENTRE_FEE = 6.61          # Ryde's help-centre fee, still on the older demo records
SPEEDING_STEP_M = 140           # ~100 km/h: only where the complaint alleges speeding (the trace corroborates it)
STOP_WORDS = re.compile(r"\b(stop|7-eleven|wait here|pull over)\b", re.I)
RULINGS = {"refund_full", "refund_partial", "fee_waived", "no_action", "escalate"}

TOP = {"case_id", "dispute", "trip", "route", "gps", "traffic", "weather", "fare", "chat", "driver_statement", "profiles"}
TOP_OPTIONAL = {"calls", "fare_detail", "surge"}
TRIP_OPTIONAL = {"scheduled_at", "cancellation_reason"}  # v3 records: a booking for a set time; the reason picked in the app           # v3 records: call log, fare breakdown with the quote, surge log
TRIP = {"trip_id", "service_type", "pickup", "dropoff", "estimated_km", "estimated_min", "requested_at", "accepted_at",
        "driver_arrived_at", "driver_pressed_here_at", "pickup_at", "dropoff_at", "cancelled_at", "cancelled_by"}
FARE_TRIP = {"pricing", "base_fare", "distance_km", "distance_fare", "time_min", "time_fare", "waiting_min", "waiting_fee",
             "waiting_fee_basis", "surge_multiplier", "platform_fee", "discount", "total", "currency"}
FARE_CANCEL = {"pricing", "cancellation_fee", "currency"}
BAND = {"link_id", "road_name", "road_category", "speed_band", "window_start", "window_end", "geometry"}
PROFILE_R = {"account_age_days", "rating", "disputes_90d", "disputes_upheld_90d", "route_disputes_upheld_90d",
             "no_show_disputes_upheld_90d"}
PROFILE_D = PROFILE_R | {"trips_90d"}
EXPECTED = {"ruling", "amount", "cited_policy", "escalate", "rationale"}


def dt(s):
    return datetime.fromisoformat(s)


def policy_clauses(path=POLICY_PATH):
    """{clause_id: citable?} parsed from policy.md: a clause line starts with **ID**; '不可引用' on that line = not citable."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\*\*([A-Z]+-\d+)\*\*", line)
        if m:
            out[m.group(1)] = "不可引用" not in line
    return out


def check_case(c: dict, rates: dict, clauses: dict, expected: dict | None = None) -> list[str]:
    errs: list[str] = []
    ok = lambda cond, msg: None if cond else errs.append(msg)  # noqa: E731
    t, gps, fare = c["trip"], c["gps"], c["fare"]
    cancelled = t["cancelled_at"] is not None
    end = t["cancelled_at"] if cancelled else t["dropoff_at"]
    P = (t["pickup"]["lat"], t["pickup"]["lon"])
    poly = [tuple(p) for p in c["route"]["polyline"]]

    # schema
    ok(set(c) - TOP_OPTIONAL == TOP, f"top-level keys {sorted((set(c) - TOP_OPTIONAL) ^ TOP)}")
    ok(set(t) - TRIP_OPTIONAL == TRIP, f"trip keys {sorted((set(t) - TRIP_OPTIONAL) ^ TRIP)}")
    ok(set(fare) - {"quoted_total"} == (FARE_CANCEL if cancelled else FARE_TRIP), f"fare keys {sorted(set(fare))}")
    ok(c["dispute"]["type"] in {"route_deviation", "no_show", "safety", "fare_dispute"}, "dispute.type")
    ok(t["service_type"] in {"RydeTAXI", "RydeX"}, "trip.service_type")
    ok(all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+08:00", p["ts"]) for p in gps), "gps ts format")
    ok(set(c["profiles"]["rider"]) == PROFILE_R and set(c["profiles"]["driver"]) == PROFILE_D, "profile keys")
    for who, p in ((k, c["profiles"][k]) for k in ("rider", "driver")):
        ok(p["route_disputes_upheld_90d"] + p["no_show_disputes_upheld_90d"] <= p["disputes_upheld_90d"] <= p["disputes_90d"],
           f"{who} profile: per-type upheld counts exceed totals")

    # timeline
    ok(t["requested_at"] <= t["accepted_at"] <= end, "requested <= accepted <= end")
    ok(dt(c["dispute"]["filed_at"]) >= dt(end), "dispute filed after the trip ended")
    if cancelled:
        ok(t["pickup_at"] is None and t["dropoff_at"] is None and t["cancelled_by"] in {"rider", "driver", "system"}, "cancel fields")
    else:
        ok(t["accepted_at"] < t["pickup_at"] < t["dropoff_at"] and t["cancelled_by"] is None, "trip fields")

    # gps grid
    ok(gps[0]["ts"] == t["accepted_at"], "gps starts at accepted_at")
    ok(gps[-1]["ts"] == end, "gps ends at dropoff_at/cancelled_at")
    ok(all((dt(b["ts"]) - dt(a["ts"])).total_seconds() == 5 for a, b in zip(gps, gps[1:])), "gps is a 5 s grid")
    ok(all(p["speed_kmh"] >= 0 for p in gps), "speed >= 0")
    step = max(haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(gps, gps[1:]))
    limit = SPEEDING_STEP_M if re.search(r"speeding", c["dispute"]["statement"], re.I) else MAX_STEP_M
    ok(step <= limit, f"max 5 s displacement {step:.0f} m (> {limit} m)")
    if not cancelled:
        first = next(p for p in gps if p["ts"] == t["pickup_at"])
        last = next(p for p in gps if p["ts"] == t["dropoff_at"])
        ok(haversine_m((first["lat"], first["lon"]), P) < 5, "gps at pickup point when trip starts")
        ok(haversine_m((last["lat"], last["lon"]), (t["dropoff"]["lat"], t["dropoff"]["lon"])) < 5, "gps at dropoff point at the end")

    # route
    ok(t["estimated_km"] == c["route"]["total_km"] and t["estimated_min"] == c["route"]["total_min"], "estimate == route")
    ok(haversine_m(poly[0], P) < 5 and haversine_m(poly[-1], (t["dropoff"]["lat"], t["dropoff"]["lon"])) < 5,
       "route polyline spans pickup -> dropoff")

    # driver arrival (200 m rule) derived from gps
    within = [p["ts"] for p in gps if haversine_m((p["lat"], p["lon"]), P) <= ARRIVAL_RADIUS_M]
    ok(t["driver_arrived_at"] in ((within[0] if within else None), t["driver_pressed_here_at"]) if t["driver_pressed_here_at"] else t["driver_arrived_at"] == (within[0] if within else None),
       "driver_arrived_at == the arrival confirmation, or the first gps sample within 200 m")
    if t["driver_pressed_here_at"] and t["driver_arrived_at"]:
        ok(t["driver_pressed_here_at"] >= t["driver_arrived_at"], "'I'm Here' pressed after arriving")
    if t["driver_pressed_here_at"]:
        ok(t["accepted_at"] <= t["driver_pressed_here_at"] <= end, "'I'm Here' inside accepted..end")
    if c["dispute"]["type"] == "no_show":
        dmin = min(haversine_m((p["lat"], p["lon"]), P) for p in gps)
        ok((t["driver_arrived_at"] is not None) == (dmin < ARRIVAL_RADIUS_M) or t["driver_arrived_at"] == t["driver_pressed_here_at"],
           f"no_show: arrived_at vs min distance {dmin:.0f} m")
        if t["cancelled_by"] == "driver":
            ok(t["driver_pressed_here_at"] is not None, "driver no-show cancellation without an 'I'm Here' tap")

    # chat
    for m in c["chat"]:
        ok(t["accepted_at"] <= m["ts"] <= end, f"chat {m['ts']} outside accepted..end")
        ok(m["from"] in {"rider", "driver"}, "chat.from")
    trip_gps = slice_gps(gps, t["pickup_at"], t["dropoff_at"]) if not cancelled else []
    if not cancelled:
        stops = stationary_windows(trip_gps, rates["stationary_threshold_m"])
        asked = [m["ts"] for m in c["chat"] if STOP_WORDS.search(m["text"]) and m["from"] == "rider"]
        if c["dispute"]["type"] == "route_deviation":
            for ts in asked:  # a stop the rider asked for must show up in the trace after the message
                ok(any(s[0] >= ts for s in stops), f"chat asks for a stop at {ts} but gps shows none after it")
        if c["dispute"]["type"] == "safety":
            ok(not stops, "safety script: the trip continued without stopping")
        if not asked:
            ok(not stops, f"gps has an unexplained mid-trip stop {stops}")

    # detour geometry: the trace shares the optimal polyline except for its off-route segments, and the
    # segments (as core/facts/tools.py measures them) account for the billed excess up to matching noise
    if c["dispute"]["type"] == "route_deviation":
        detours = measure_detours(trip_gps, poly)
        ok(detours, "route_deviation: no off-route segment > 200 m from the optimal route")
        billed_excess = fare["distance_km"] - c["route"]["total_km"]
        seg_excess = sum(d["extra_km"] for d in detours)
        ok(-0.3 <= billed_excess - seg_excess <= 1.0,   # real roads hide some extra km inside the 200 m on-route band; 5 s steps cut corners
           f"segments add {seg_excess:.2f} km but the meter shows +{billed_excess:.2f} km over the optimal route")
        for d in detours:
            ok(d["extra_km"] >= 0.5, f"detour {d['start'][11:19]} adds only {d['extra_km']} km (too close to the 0.2 km noise floor)")
    if c["dispute"]["type"] == "safety":
        ok(not measure_detours(trip_gps, poly), "safety script: trace must follow the optimal route")

    # fare recomputed from the trace / rate card
    if cancelled:
        ok(fare in (cancellation_fare(rates), cancellation_fare(rates, POLICY_CANCELLATION_FEE), cancellation_fare(rates, HELP_CENTRE_FEE)),
           "cancellation fare == the policy's $5.00 (or the help centre's $6.61 of the older demo records)")
    elif fare["pricing"] == "metered":
        ok({k: v for k, v in fare.items() if k != "quoted_total"} == metered_fare(trip_gps, rates, fare["surge_multiplier"], fare["discount"],
                                                                                 fold_waiting=fare.get("waiting_fee_basis") == FOLDED), "metered fare == recomputed from gps")
        ok(abs(fare["time_min"] + fare["waiting_min"] - (dt(t["dropoff_at"]) - dt(t["pickup_at"])).total_seconds() / 60) < 0.02,
           "time_min + waiting_min == trip minutes (stop minutes billed once)")
    else:
        ok(fare == fixed_fare(c["route"], rates, fare["surge_multiplier"], fare["discount"]), "fixed fare == quoted from route")
    ok(fare["pricing"] == "metered" or t["service_type"] == "RydeX", "fare.pricing matches service_type (FARE-0: RydeX fares may be distance-based)")

    # traffic: every speed band / incident sits within NEAR_M of the actual trace OR of the optimal route (each judged
    # on its own), inside the trip window; bands the trace drives through agree with the GPS speeds
    trace_pts = [(p["lat"], p["lon"]) for p in gps]
    for b in c["traffic"]["speed_bands"]:
        ok(set(b) == BAND, f"speed band keys {sorted(set(b) ^ BAND)}")
        ok(1 <= b["speed_band"] <= 8, "speed_band range")
        ok(b["road_name"] in ROADS, f"unknown road {b['road_name']}")
        if b["road_name"] not in ROADS:
            continue
        lat, lon, cat, link = ROADS[b["road_name"]]
        ok(b["road_category"] == cat and b["link_id"] == link, f"{b['road_name']} category / link_id")
        ok(re.fullmatch(r"[1-8]", b["road_category"]), f"{b['road_name']} road_category must be an LTA v4 code 1-8")
        geom = [tuple(q) for q in b["geometry"]] if b.get("geometry") else [(lat, lon)]
        ok(len(geom) >= 2 or not b.get("geometry"), f"{b['road_name']} geometry needs >= 2 points")
        d_trace = min(haversine_m(g, q) for g in geom for q in trace_pts)
        d_route = min(project(g[0], g[1], poly)[0] for g in geom)
        ok(d_trace <= NEAR_M or d_route <= NEAR_M,
           f"{b['road_name']} is {d_trace:.0f} m from the trace and {d_route:.0f} m from the optimal route (> {NEAR_M} m)")
        ok(b["window_start"] <= end and b["window_end"] >= t["accepted_at"], f"{b['road_name']} window overlaps the trip")
        from lint import band_level           # the one measurement: generator, validator and linter agree by construction
        lvl = band_level(gps, geom, b["window_start"], b["window_end"])
        if lvl is not None:  # the trace drives this road during the window: the band is what the trace says
            ok(lvl == b["speed_band"], f"{b['road_name']} says band {b['speed_band']} but the trace measures band {lvl}")
    for i in c["traffic"]["incidents"]:
        d_trace = min(haversine_m((i["lat"], i["lon"]), q) for q in trace_pts)
        d_route = project(i["lat"], i["lon"], poly)[0]
        ok(d_trace <= NEAR_M or d_route <= NEAR_M,
           f"incident {i['type']} is {d_trace:.0f} m from the trace and {d_route:.0f} m from the optimal route")
        ok(i["reported_at"] <= end, "incident reported before the trip ended")
        ok(i["message"].startswith(f"({dt(i['reported_at']).day}/{dt(i['reported_at']).month}){dt(i['reported_at']):%H:%M}"),
           "incident message prefix matches reported_at (LTA DataMall format)")

    # expected ruling (Judge regression answer) exists and cites only citable clauses
    exp_path = os.path.join(EXPECTED_DIR, f"{c['case_id']}.json")
    if expected is None:
        ok(os.path.exists(exp_path), f"missing {os.path.relpath(exp_path)}")
    if expected is not None or os.path.exists(exp_path):
        e = expected if expected is not None else json.load(open(exp_path))
        ok(set(e) >= EXPECTED, f"expected keys {sorted(EXPECTED - set(e))} missing")
        ok(e.get("ruling") in RULINGS, f"expected.ruling {e.get('ruling')!r} not in vocabulary")
        ok(e.get("escalate") == (e.get("ruling") == "escalate"), "expected.escalate must match ruling == escalate")
        if clauses:
            for cid in e.get("cited_policy", []):
                ok(cid in clauses, f"expected cites unknown clause {cid}")
                ok(clauses.get(cid, False), f"expected cites non-citable clause {cid}")
        if e.get("ruling") in {"refund_full", "refund_partial", "fee_waived"}:
            ok(isinstance(e.get("amount"), (int, float)) and e["amount"] > 0, "refund ruling needs a positive amount")
            if cancelled:
                ok(e["amount"] == fare["cancellation_fee"], "refund of a cancellation fee must equal the fee charged")
            else:
                ok(e["amount"] <= fare["total"], "refund cannot exceed the fare")
        else:
            ok(e.get("amount") in (None, 0), "non-refund ruling must not carry an amount")
    return errs


def main():
    rates = load_rates()
    clauses = policy_clauses()
    failed = 0
    for path in sorted(glob.glob(os.path.join(CASES_DIR, "C-*.json"))):
        case = read_case(path)
        errs = check_case(case, rates, clauses)
        print(f"{case['case_id']} {'PASS' if not errs else 'FAIL'}")
        for e in errs:
            print(f"   - {e}")
        failed += bool(errs)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
