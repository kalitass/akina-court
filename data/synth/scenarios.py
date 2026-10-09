#!/usr/bin/env python3
"""Parametric benchmark generator: composes the build_cases.py helpers over a grid of conditions and writes

    data/bench/cases/B-0001.json ...      Case files (same schema as data/cases/)
    data/bench/expected/B-0001.json ...   {ruling, amount, cited_policy, escalate, rationale, flag_account}
    data/bench/manifest.json              per case: type, conditions, ground truth, what makes it hard

    set -a; . ./.env; set +a; unset ONEMAP_TOKEN      # the .env token expires every 72 h; email+password refreshes it
    .venv/bin/python data/synth/scenarios.py          # legs already in onemap_cache.json need no network

Ground truth is DERIVED, not typed: every generated case is run through core.facts.tools.build_fact_table and
core.policy_engine.evaluate; the mechanical slots (segment exists, incident on the replaced stretch, consent timing,
I'm Here tap, 200 m radius, 180 s grace, threat keyword) come from the engine, the interpretive slots (does the
rider's consent / stop request cover this segment) are filled from what the scenario injected, and the two must
agree or the generator aborts. Deterministic for a fixed SEED and a warm OneMap cache.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import urllib.error
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import validate  # noqa: E402
from build_cases import (LOC, ROADS, SGT, Congestion, Stop, along_km, approach_trace, band_from_gps, build_trajectory,  # noqa: E402
                         compose, detour_trace, dump, incident, measure_detours, nearest_idx, offset, place, profiles,
                         project, routes, secs, trip_block)
from fare import cancellation_fare, distance_km, fixed_fare, load_rates, metered_fare, slice_gps  # noqa: E402
from route_provider import haversine_m  # noqa: E402

from core.facts.tools import _flags, build_fact_table  # noqa: E402
from core.policy_engine import evaluate, expected_amount  # noqa: E402
from core.schemas import Case  # noqa: E402

SEED = 20261008
BENCH_DIR = os.path.join(ROOT, "data", "bench")
CASES_DIR = os.path.join(BENCH_DIR, "cases")
EXPECTED_DIR = os.path.join(BENCH_DIR, "expected")
CANCEL_FEE = 6.61

LOC.update({  # real Singapore places, coordinates from common knowledge (~50-100 m)
    "Changi Airport T3": (1.3644, 103.9915),
    "Jurong East MRT": (1.3330, 103.7422),
    "Woodlands Civic Centre": (1.4360, 103.7865),
    "NUS": (1.2966, 103.7764),
    "Sentosa Beach Station": (1.2494, 103.8303),
    "Punggol Waterway Point": (1.4064, 103.9021),
    "Tampines Mall": (1.3525, 103.9447),
    "Raffles Place": (1.2840, 103.8513),
    # named stop places (real malls) a rider can ask for by name
    "Parkway Parade": (1.3012, 103.9052),
    "Paya Lebar Square": (1.3176, 103.8929),
    "Clementi Mall": (1.3149, 103.7645),
    "Northpoint City": (1.4295, 103.8355),
    "Great World City": (1.2936, 103.8319),
    "Changi City Point": (1.3345, 103.9623),
})

WEATHER = {"fair": {"rain_mm": 0, "description": "Fair"},
           "light": {"rain_mm": 1.8, "description": "Light rain"},
           "heavy": {"rain_mm": 18.5, "description": "Heavy rain, thundery showers"}}
BAND_SPEED = {1: 8.0, 2: 15.0}           # km/h injected on the stretch before the detour -> LTA band
CONGESTION_LEN_KM = 0.45
OFFSET_CANDIDATES = [(1, 1000), (-1, 1000), (1, 1500), (-1, 1500), (1, 700), (-1, 700), (1, 2000), (-1, 2000)]
SPAN_CANDIDATES = [(1.0, 1.0), (1.5, 1.5), (0.7, 0.7), (2.0, 2.0), (1.0, 2.0), (2.0, 1.0)]

# chat lines whose keyword flags were checked against core.facts.tools._flags (asserted again at build time)
INNOCUOUS = [("rider", "Hi, I am at the main entrance in a blue shirt."),
             ("driver", "Arriving in 2 min, white Honda Vezel.")]


# ----------------------------------------------------------------------------------------------- small helpers

def iso(dt: datetime) -> str:
    return dt.isoformat()


def r5(s: float) -> int:
    """Round seconds to the 5 s GPS grid."""
    return int(round(s / 5.0)) * 5


def bearing(a, b) -> float:
    dlat = b[0] - a[0]
    dlon = (b[1] - a[1]) * math.cos(math.radians(a[0]))
    return math.degrees(math.atan2(dlon, dlat)) % 360


def msgs(*lines):
    return [{"ts": iso(ts), "from": who, "text": text} for ts, who, text in lines]


def road_cat(name: str) -> str:
    if "EXPRESSWAY" in name:
        return "1"
    if any(w in name for w in ("ROAD", "AVENUE", "BOULEVARD", "HIGHWAY", "PARKWAY", "WAY")):
        return "2"
    return "3"


_road_seq = [1000]


def register_road(name: str, pt) -> None:
    """Add a road seen on a OneMap route to the ROADS table (category by name, synthetic link id) so band()
    / validate.py accept it. Registration order is deterministic for a fixed scenario list."""
    if name not in ROADS:
        _road_seq[0] += 1
        ROADS[name] = (round(pt[0], 4), round(pt[1], 4), road_cat(name), f"SYN-{_road_seq[0]}")


def road_runs(route, min_m=800):
    """[(name, from_m, to_m)] of the roads on a route longer than min_m, longest first."""
    runs = [(r["name"], r["from_m"], r["to_m"]) for r in route["roads"] if r["to_m"] - r["from_m"] >= min_m]
    return sorted(runs, key=lambda r: r[1] - r[2])


def dominant_road(route, lo_km, hi_km) -> str:
    """Road name covering most of the along-track window [lo_km, hi_km] of a route."""
    best, best_len = None, 0.0
    for r in route["roads"]:
        ov = min(r["to_m"], hi_km * 1000) - max(r["from_m"], lo_km * 1000)
        if ov > best_len:
            best, best_len = r["name"], ov
    return best or route["roads"][0]["name"]


def band_on(road, level, start, end, geometry):
    lat, lon, cat, link = ROADS[road]
    return {"link_id": link, "road_name": road, "road_category": cat, "speed_band": level,
            "window_start": iso(start), "window_end": iso(end), "geometry": [list(p) for p in geometry]}


def gps_bands(route, legs, trip_gps, w0, w1, skip=(), max_n=2):
    """Speed bands derived from the trace for the longest roads of the optimal route the driver actually drove."""
    out = []
    for name, a, b in road_runs(route):
        if name in skip or len(out) >= max_n:
            continue
        mid = _point_at(route, (a + b) / 2000)
        register_road(name, mid)
        try:
            out.append(band_from_gps(name, trip_gps, w0, w1, [route, *legs]))
        except ValueError:
            continue
    return out


def _point_at(route, km):
    poly = [tuple(p) for p in route["polyline"]]
    cum = along_km(poly)
    i = min(range(len(poly)), key=lambda k: abs(cum[k] - km))
    return poly[i]


def vertex_at(opt, cum, km):
    return min(range(len(opt)), key=lambda k: abs(cum[k] - km))


def perp_point(opt, cum, km, side, dist_m):
    i = vertex_at(opt, cum, km)
    a, b = opt[max(i - 2, 0)], opt[min(i + 2, len(opt) - 1)]
    return offset(opt[i], (bearing(a, b) + 90 * side) % 360, dist_m)


def approach_leg(rp, P, D, rng, max_km=4.5):
    """A start point ~1.2 km behind the pickup (opposite side from the destination) whose OneMap route to the pickup
    is at most max_km; returns (start_point, approach_seconds at ~25 km/h, min 150 s)."""
    base = (bearing(P, D) + 180) % 360
    for _ in range(12):
        start = offset(P, (base + rng.uniform(-60, 60)) % 360, rng.choice([900, 1200, 1500]))
        try:
            r = rp.route([start, P])
        except urllib.error.HTTPError:
            continue
        if r["total_km"] <= max_km:
            return start, max(150, r5(r["total_km"] / 25 * 3600))
    raise RuntimeError("no approach route under %.1f km to the pickup" % max_km)


def after_tap_s(gps, P, tap: datetime, end: datetime) -> int:
    """Continuous seconds within 200 m of the pickup from the tap until the first exit / the end, the way
    core.facts.tools reports it in the tl-here fact (NS-1(iii) under the 2026-10-09 engine)."""
    pts = [p for p in gps if datetime.fromisoformat(p["ts"]) >= tap]
    t = 0
    for a, b in zip(pts, pts[1:]):
        if haversine_m((a["lat"], a["lon"]), P) <= 200 and haversine_m((b["lat"], b["lon"]), P) <= 200:
            t += 5
        else:
            break
    return t


def flagged(text, want: set) -> None:
    got = set(_flags(text))
    assert got == want, f"chat line {text!r} flags {sorted(got)} != intended {sorted(want)}"


# ----------------------------------------------------------------------------------------------- scenario list

def R(name, pair, **kw):
    d = dict(kind="route_deviation", name=name, pair=pair, service="RydeTAXI", loops=[{}], consent="none", stop="none",
             incident="none", band=0, prior=0, weather="fair", threat=None, hard="")
    d.update(kw)
    return d


def N(name, pair, **kw):
    d = dict(kind="no_show", name=name, pair=pair, service="RydeX", weather="fair", prior_ns=0, threat=None, hard="")
    d.update(kw)
    return d


def S(name, pair, **kw):
    d = dict(kind="safety", name=name, pair=pair, service="RydeX", weather="fair", hard="")
    d.update(kw)
    return d


# loops: list of {"frac": (a, b)} (perpendicular-offset loop on the stretch a..b of the optimal route) or
#        {"place": name} (loop through a named real place, used by the stop conditions)
# consent: none | before (driver asks + rider agrees before the segment) | after (same, after it started)
#        | request_only (driver asks, rider never replies) | scope_other (rider agreed to a 1-min petrol stop just
#          ahead, the segment is an unrelated 1-2 km loop) | before_seg1 (two loops: consent names only loop 1)
# stop: none | named (rider names the place, driver stops there) | unnamed (rider asks for "a 7-Eleven", driver
#        drives to one far off the route and stops)
# incident: none | on_stretch (on the replaced optimal stretch, reported before) | decoy_far (on the optimal route
#        but >= 2 km from the replaced stretch) | late (on the stretch, reported after the detour began)
#        | seg1 (two loops: incident on loop 1's stretch only)
# band: 0 | 1 | 2 (LTA band hand-set on the replaced stretch, backed by an 8 / 15 km/h crawl before the detour)
SCENARIOS = [
    # ---- route deviation ------------------------------------------------------------------------------------
    R("rd_basic", ("Raffles Place", "Changi Airport T3"), loops=[{"frac": (0.45, 0.60)}],
      hard="plain unexplained loop; the only trap is the rider overstating the extra km"),
    R("rd_consent_before", ("Clarke Quay", "Bedok Mall"), loops=[{"frac": (0.55, 0.72)}], consent="before",
      hard="RD-5: consent 3 min before the segment covers it -> no refund despite +km"),
    R("rd_consent_after", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.35, 0.60)}], consent="after",
      hard="same chat as rd_consent_before but timestamped after the segment started -> RD-5 fails"),
    R("rd_incident_on_stretch", ("Woodlands Civic Centre", "Punggol Waterway Point"), loops=[{"frac": (0.40, 0.55)}], incident="on_stretch",
      hard="RD-4(a): accident on the replaced stretch reported before -> exempt; the rider's complaint is loud"),
    R("rd_incident_decoy", ("Tanjong Pagar Centre", "Changi Airport T3"), loops=[{"frac": (0.30, 0.45)}], incident="decoy_far",
      hard="an accident exists on the optimal route but 2+ km from the replaced stretch -> no exemption"),
    R("rd_incident_late", ("Bugis Junction", "Jurong East MRT"), loops=[{"frac": (0.50, 0.65)}], incident="late",
      hard="accident on the stretch but reported after the driver had already left the route -> no exemption"),
    R("rd_band1_no_incident", ("Orchard Road", "NUS"), loops=[{"frac": (0.35, 0.55)}], band=1, weather="light",
      hard="RD-4(b): band 1 on the replaced stretch alone does not exempt (MVP rule) -> refund"),
    R("rd_band1_incident", ("Punggol Waterway Point", "Tampines Mall"), loops=[{"frac": (0.30, 0.50)}], band=1, incident="on_stretch",
      hard="band 1 + accident on the stretch -> exempt"),
    R("rd_band2_heavy_rain", ("NUS", "Raffles Place"), loops=[{"frac": (0.40, 0.60)}], band=2, weather="heavy",
      hard="driver blames flooding; weather is not RD-4 evidence and band 2 alone does not exempt -> refund"),
    R("rd_stop_named", ("Clarke Quay", "Bedok Mall"), loops=[{"place": "Paya Lebar Square"}], stop="named",
      hard="RD-3(a): rider named Paya Lebar Square; the loop and 4-min stop are the rider's own request -> no refund"),
    R("rd_stop_named_prior", ("Jurong East MRT", "NUS"), loops=[{"place": "Clementi Mall"}], stop="named", prior=2, weather="light",
      hard="named stop exempts the segment, so the driver's 2 priors do not trigger RD-6 -> no_action, no flag"),
    R("rd_stop_unnamed", ("Clarke Quay", "Bedok Mall"), loops=[{"frac": (0.55, 0.72)}], stop="unnamed",
      hard="RD-3(b): 'a 7-Eleven on the way' does not cover a loop to one 1 km off the route -> refund the km, keep the waiting"),
    R("rd_two_segs_consent_seg1", ("Woodlands Civic Centre", "Orchard Road"), loops=[{"frac": (0.25, 0.38)}, {"frac": (0.62, 0.75)}], consent="before_seg1",
      hard="two segments; the rider agreed to the first (named road) only -> refund segment 2 only"),
    R("rd_two_segs_incident_seg1", ("Marina Bay Sands", "Tampines Mall"), loops=[{"frac": (0.25, 0.38)}, {"frac": (0.62, 0.75)}], incident="seg1",
      hard="two segments; accident exempts the first, the second is unexplained -> refund segment 2 only"),
    R("rd_two_segs_plain", ("Tanjong Pagar Centre", "Changi Airport T3"), loops=[{"frac": (0.25, 0.38)}, {"frac": (0.62, 0.75)}],
      hard="two unexplained segments -> refund the sum"),
    R("rd_fixed_fare", ("Bugis Junction", "Jurong East MRT"), loops=[{"frac": (0.50, 0.65)}], service="RydeX",
      hard="RydeX is a fixed quote: real detour, zero refundable km -> no_action (RD-2 non-metered branch)"),
    R("rd_fixed_fare_consent", ("Punggol Waterway Point", "Tampines Mall"), loops=[{"frac": (0.30, 0.50)}], service="RydeX", consent="before",
      hard="fixed fare + consent -> no_action either way"),
    R("rd_prior_flag", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.35, 0.60)}], prior=2,
      hard="RD-6: driver has 2 upheld route disputes -> refund + flag_account"),
    R("rd_fixed_fare_prior_flag", ("Orchard Road", "NUS"), loops=[{"frac": (0.35, 0.55)}], service="RydeX", prior=2,
      hard="fixed fare so no refund, but RD-1 breach + 2 priors -> no_action + flag_account"),
    R("rd_no_deviation", ("Tampines Mall", "Changi Airport T3"), loops=[], weather="heavy",
      hard="rider complains the fare felt high; GPS follows the optimal route -> RD-1 fails, no_action"),
    R("rd_request_only", ("Clarke Quay", "Sentosa Beach Station"), loops=[{"frac": (0.30, 0.50)}], consent="request_only",
      hard="driver asked, rider never answered -> no agreement, RD-5 fails -> refund"),
    R("rd_scope_other", ("Woodlands Civic Centre", "Punggol Waterway Point"), loops=[{"frac": (0.40, 0.55)}], consent="scope_other",
      hard="rider agreed to a 1-min petrol stop just ahead; the segment is an unrelated 1-2 km loop with no stop -> consent does not cover it"),
    R("rd_consent_before_prior", ("Raffles Place", "Changi Airport T3"), loops=[{"frac": (0.45, 0.60)}], consent="before", prior=2,
      hard="consent exempts the segment, so RD-6 is NOT triggered despite 2 priors -> no_action, no flag"),
    R("rd_threat_in_chat", ("Marina Bay Sands", "Tampines Mall"), loops=[{"frac": (0.40, 0.55)}], threat="driver",
      hard="route dispute whose chat contains a threat keyword -> SAFE-1 overrides: escalate, no refund computed"),
    R("rd_consent_before_light", ("Bugis Junction", "Jurong East MRT"), loops=[{"frac": (0.50, 0.65)}], consent="before", weather="light", incident="decoy_far",
      hard="consent exempts; the decoy incident is irrelevant noise"),
    # ---- no-show ----------------------------------------------------------------------------------------------
    N("ns_fake_here_far", ("Bugis Junction", "Tanjong Pagar Centre"), by="driver", park_m=600, wait_s=210, here=True,
      hard="NS-2: I'm Here tapped 600 m away, never within 200 m -> refund + flag_account"),
    N("ns_wait_2min", ("Bedok Mall", "Raffles Place"), by="driver", park_m=40, wait_s=120, here=True,
      hard="NS-1(iii): only ~2 min inside 200 m -> refund, no flag"),
    N("ns_wait_4min", ("Raffles Place", "Changi Airport T3"), by="driver", park_m=40, wait_s=240, here=True,
      hard="all three NS-1 elements hold -> fee stands"),
    N("ns_rider_cancel_150s", ("Jurong East MRT", "NUS"), by="rider", cancel_s=150, driver="en_route",
      hard="NS-4: cancelled 150 s after matching -> inside the 3-min grace -> refund"),
    N("ns_rider_cancel_200s", ("NUS", "Raffles Place"), by="rider", cancel_s=200, driver="en_route",
      hard="NS-4: 200 s after matching -> fee stands even though the driver was still 1 km away ('driver was late' is not a Ryde rule, NS-8)"),
    N("ns_no_here_tap", ("Woodlands Civic Centre", "Punggol Waterway Point"), by="driver", park_m=40, wait_s=240, here=False,
      hard="driver waited 4 min at the pin but never tapped I'm Here -> NS-1(i) fails -> refund (NS-3), no flag"),
    N("ns_fake_here_350m", ("Punggol Waterway Point", "Tampines Mall"), by="driver", park_m=350, wait_s=240, here=True,
      hard="parked 350 m away: outside the 200 m radius -> refund + flag"),
    N("ns_wait_185s_edge", ("Clarke Quay", "Bedok Mall"), by="driver", park_m=40, within_s=185, here=True,
      hard="boundary: 185 s continuously inside 200 m after the tap (> 180) -> fee stands"),
    N("ns_wait_175s_edge", ("Tampines Mall", "Changi Airport T3"), by="driver", park_m=40, within_s=175, here=True,
      hard="boundary: 175 s inside 200 m after the tap (<= 180) -> refund"),
    N("ns_rider_cancel_175s", ("Orchard Road", "Marina Bay Sands"), by="rider", cancel_s=175, driver="en_route",
      hard="boundary 175 s -> grace -> refund"),
    N("ns_rider_cancel_185s", ("Bedok Mall", "Changi Airport T3"), by="rider", cancel_s=185, driver="en_route",
      hard="boundary 185 s -> fee stands"),
    N("ns_wait_4min_two_more_minutes", ("Tanjong Pagar Centre", "Sentosa Beach Station"), by="driver", park_m=40, wait_s=250, here=True, weather="heavy", chat="two_more",
      hard="rider texted 'give me 2 more minutes' in heavy rain; sympathy is not a clause -> fee stands"),
    N("ns_wait_2min_driver_claims_5", ("Jurong East MRT", "NUS"), by="driver", park_m=40, wait_s=125, here=True, chat="driver_claims",
      hard="driver's statement says 5 min, GPS says ~2 min -> refund"),
    N("ns_fake_here_1km_long_wait", ("Woodlands Civic Centre", "Orchard Road"), by="driver", park_m=1000, wait_s=300, here=True, weather="light",
      hard="waited 5 min but 1 km away -> NS-1(ii) fails -> refund + flag"),
    N("ns_rider_cancel_400s_driver_waiting", ("Raffles Place", "Sentosa Beach Station"), by="rider", cancel_s=400, driver="at_pickup",
      hard="driver was parked at the pin for minutes; rider cancels at 400 s -> fee stands"),
    N("ns_threat_in_chat", ("Bugis Junction", "Jurong East MRT"), by="driver", park_m=40, wait_s=240, here=True, chat="threat",
      hard="no-show facts favour the driver, but the chat holds a threat keyword -> escalate"),
    N("ns_rider_cancel_100s_bad_profile", ("Marina Bay Sands", "Tampines Mall"), by="rider", cancel_s=100, driver="en_route", prior_ns=2,
      hard="rider has 2 upheld no-show disputes; still inside grace -> refund"),
    N("ns_wait_4min_180m", ("Clarke Quay", "Sentosa Beach Station"), by="driver", park_m=180, wait_s=240, here=True,
      hard="parked 180 m from the pin (inside the 200 m radius), rider says 'not at the entrance' -> fee stands"),
    # ---- safety ------------------------------------------------------------------------------------------------
    S("safe_driver_threat", ("Clarke Quay", "Bedok Mall"), chat="driver_threat",
      hard="SAFE-1 keyword 'lock the door' from the driver -> escalate"),
    S("safe_rider_threat", ("Tampines Mall", "Changi Airport T3"), chat="rider_threat", service="RydeTAXI",
      hard="SAFE-1 keyword from the rider; the driver filed -> escalate, no refund"),
    S("safe_innocuous_chat_dangerous_driving", ("Jurong East MRT", "NUS"), chat="innocuous",
      hard="no keyword in chat; the complaint alleges dangerous driving -> SAFE-2 escalate"),
    S("safe_no_chat_harassment", ("Woodlands Civic Centre", "Punggol Waterway Point"), chat="none", weather="heavy",
      hard="no chat at all; harassment alleged in the statement -> escalate (SAFE-1 via type)"),
    S("safe_keyword_only_in_statement", ("NUS", "Raffles Place"), chat="innocuous", statement_threat=True,
      hard="the only threat word is in the driver's own statement, not the chat; still a safety ticket -> escalate"),
    R("rd_keyword_trap_find_you", ("Orchard Road", "NUS"), loops=[{"frac": (0.35, 0.55)}], threat="trap",
      hard="route dispute; rider wrote 'I'll find you at the lobby' which hits the threat keyword 'find you' -> the deterministic rule escalates"),
]


# ----------------------------------------------------------------------------------------------- route cases

FRAC_SHIFTS = [0.0, 0.08, -0.08, 0.16, -0.16]


def _loop_from_spec(opt, cum, lp, cand):
    """Loop dict for compose() from a loop spec and a candidate (shift, side, offset_m) or (back_km, fwd_km)."""
    if "place" in lp:
        via = LOC[lp["place"]]
        _, along = project(via[0], via[1], opt)
        back, fwd = cand
        i1, i2 = vertex_at(opt, cum, along - back), vertex_at(opt, cum, along + fwd)
    else:
        shift, side, dist = cand
        a, b = lp["frac"][0] + shift, lp["frac"][1] + shift
        L = cum[-1]
        if a * L < 0.8 or b * L > L - 0.8:
            return None
        i1, i2 = vertex_at(opt, cum, a * L), vertex_at(opt, cum, b * L)
        via = perp_point(opt, cum, (a + b) / 2 * L, side, dist)
    if i2 <= i1 + 2:
        return None
    return {"leave": opt[i1], "via": [via], "rejoin": opt[i2], "i1": i1, "i2": i2}


def avg_speed(route) -> float:
    """Cruising speed for a trip: 40 km/h when the optimal route has a long expressway run, else 30 km/h."""
    return 40.0 if any("EXPRESSWAY" in r["name"] and r["to_m"] - r["from_m"] > 3000 for r in route["roads"]) else 30.0


def _try_trace(rp, route, opt, loops, pickup_at, spec, stops_spec, cz_level):
    """Compose the driven polyline, solve the timeline, build the trace, measure. Raises ValueError on mismatch."""
    poly, spans, legs = compose(rp, opt, [{k: v for k, v in lp.items() if k in ("leave", "via", "rejoin")} for lp in loops])
    cum = along_km(poly)
    L = cum[-1]
    v_avg = avg_speed(route)
    zones = []
    if cz_level:
        z0 = max(spans[0][0] - CONGESTION_LEN_KM, 0.3)
        zones.append(Congestion(z0, spans[0][0], BAND_SPEED[cz_level]))

    def time_at(km):  # seconds to reach km along the driven polyline (zones at their speed, else v_avg)
        t, pos = 0.0, 0.0
        for z in sorted(zones, key=lambda z: z.from_km):
            lo, hi = max(pos, z.from_km), min(km, z.to_km)
            if hi > lo:
                t += (lo - pos) / v_avg * 3600 + (hi - lo) / z.speed_kmh * 3600
                pos = hi
        t += max(km - pos, 0) / v_avg * 3600
        return t

    stops, extra = [], 0
    for k, dur in stops_spec:               # stop at loop k's via point
        vi = nearest_idx(poly, loops[k]["via"][0])
        st = r5(time_at(cum[vi])) + extra
        stops.append(Stop(*poly[vi], start_s=st, duration_s=dur))
        extra += dur
    total_s = r5(time_at(L)) + extra
    _, trip_gps, found, legs2 = detour_trace(rp, opt, [{k: v for k, v in lp.items() if k in ("leave", "via", "rejoin")} for lp in loops],
                                              pickup_at, total_s, stops=stops, zones=zones, seed=spec["seed"])
    for f in found:
        if f["extra_km"] < 0.5:
            raise ValueError(f"segment adds only {f['extra_km']} km")
    hidden = (distance_km(trip_gps) - route["total_km"]) - sum(f["extra_km"] for f in found)
    if not -0.1 <= hidden <= 0.9:          # validate.py allows 1.0 km of extra km hidden inside the 200 m band
        raise ValueError(f"{hidden:.2f} km of extra distance hidden inside the on-route band")
    return poly, spans, legs2, trip_gps, found, total_s, stops


def build_route(spec, rates, rp, idx, rng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    opt = [tuple(p) for p in route["polyline"]]
    cum = along_km(opt)
    pickup_at = spec["day"]
    approach_start, approach_s = approach_leg(rp, P, D, rng)
    accepted = pickup_at - timedelta(seconds=approach_s + 10)
    stop_dur = {"named": 240, "unnamed": 250}.get(spec["stop"], 0)
    stops_spec = [(0, stop_dur)] if spec["stop"] != "none" else []
    cz = spec["band"]

    # ---- find loops one at a time (each attempt costs at most two cached OneMap legs) ----
    loops, found = [], []
    for k, lp in enumerate(spec["loops"]):
        cands = SPAN_CANDIDATES if "place" in lp else [(sh, side, d) for sh in FRAC_SHIFTS for side, d in OFFSET_CANDIDATES]
        ok = False
        for cand in cands:
            loop = _loop_from_spec(opt, cum, lp, cand)
            if loop is None or (loops and loop["i1"] <= loops[-1]["i2"]):
                continue
            try:
                _try_trace(rp, route, opt, loops + [loop], pickup_at, spec, [s for s in stops_spec if s[0] <= k], cz)
            except (ValueError, RuntimeError, AssertionError, urllib.error.HTTPError):
                continue        # no clean segment, or OneMap found no route (via point in the sea / a reserve)
            loops.append(loop)
            ok = True
            break
        if not ok:
            raise RuntimeError(f"{spec['name']}: no candidate produced loop {k}")
    if spec["loops"]:
        poly, spans, legs, trip_gps, found, total_s, stops = _try_trace(rp, route, opt, loops, pickup_at, spec, stops_spec, cz)
    else:
        total_s = r5(cum[-1] / avg_speed(route) * 3600)
        trip_gps = build_trajectory(opt, pickup_at, total_s, seed=spec["seed"])
        poly, spans, legs, stops = opt, [], [], []
    dropoff_at = pickup_at + timedelta(seconds=total_s)
    seg_start = [datetime.fromisoformat(f["start"]) for f in found]
    gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"]) + trip_gps[1:]
    pressed = pickup_at - timedelta(seconds=10)
    service = spec["service"]
    trip = trip_block(f"T-{2000 + idx}", service, place(spec["pair"][0]), place(spec["pair"][1]), route,
                      accepted - timedelta(seconds=35), accepted, gps, pressed, pickup_at, dropoff_at)
    R_ = [route, *legs]
    w0, w1 = accepted - timedelta(minutes=5), dropoff_at + timedelta(minutes=5)

    # ---- traffic ----
    bands, incidents = [], []
    stretch_roads = []
    stretches = []  # (lo_km, hi_km) of the optimal route each loop replaced
    for lp in loops:
        lo, hi = cum[lp["i1"]], cum[lp["i2"]]
        stretches.append((lo, hi))
        stretch_roads.append(dominant_road(route, lo, hi))
    if cz:
        lo, hi = stretches[0]
        road = stretch_roads[0]
        register_road(road, opt[loops[0]["i1"]])
        bands.append(band_on(road, cz, w0, seg_start[0], opt[loops[0]["i1"]:loops[0]["i2"] + 1]))
    bands += gps_bands(route, legs, trip_gps, w0, w1, skip=set(stretch_roads if cz else []), max_n=2)
    inc_kind = spec["incident"]
    if inc_kind in ("on_stretch", "seg1", "late"):
        lo, hi = stretches[0]
        pt = opt[vertex_at(opt, cum, (lo + hi) / 2)]
        at = (seg_start[0] + timedelta(seconds=90)) if inc_kind == "late" else (pickup_at - timedelta(minutes=12))
        incidents.append(incident("Accident", pt[0], pt[1], at,
                                  f"Accident on {stretch_roads[0].title()} (towards {spec['pair'][1]}). Lanes blocked, expect delays."))
    elif inc_kind == "decoy_far":
        lo, hi = stretches[0]
        km = hi + 2.5 if cum[-1] - hi > 3.0 else lo - 2.5
        assert 0.5 < km < cum[-1] - 0.5, f"{spec['name']}: no room for a decoy incident"
        pt = opt[vertex_at(opt, cum, km)]
        road = dominant_road(route, km - 0.2, km + 0.2)
        incidents.append(incident("Vehicle breakdown", pt[0], pt[1], pickup_at - timedelta(minutes=8),
                                  f"Vehicle breakdown on {road.title()}. Left lane blocked."))

    # ---- chat ----
    chat_lines, consent, stop_place = [], spec["consent"], None
    detour_road = {}
    for k, lg in enumerate(legs):
        # the road the driver names must differ from the congested stretch, else "go round via X to avoid X" is self-contradictory
        others = [r for r in lg["roads"] if r["name"].title() != stretch_roads[0].title()] or lg["roads"]
        detour_road[k] = max(others, key=lambda r: r["to_m"] - r["from_m"])["name"].title().replace("'S ", "'s ")
    if consent in ("before", "after", "before_seg1"):
        t_req = seg_start[0] + timedelta(seconds=(120 if consent == "after" else -200))
        road = detour_road[0]
        ask = f"Traffic ahead on {stretch_roads[0].title()} is building up, ok if I go round via {road}?"
        yes = "Sure, go ahead."
        flagged(ask, {"request"}); flagged(yes, {"agreement"})
        chat_lines += [(t_req, "driver", ask), (t_req + timedelta(seconds=40), "rider", yes)]
    elif consent == "request_only":
        t_req = seg_start[0] - timedelta(seconds=200)
        ask = f"Traffic ahead on {stretch_roads[0].title()} is building up, ok if I go round via {detour_road[0]}?"
        flagged(ask, {"request"})
        chat_lines += [(t_req, "driver", ask)]
    elif consent == "scope_other":
        t_req = seg_start[0] - timedelta(seconds=240)
        ask = "Mind if I pull in at the petrol station just ahead for one minute? Tank is almost empty."
        yes = "Sure, no problem."
        flagged(ask, {"request"}); flagged(yes, {"agreement"})
        chat_lines += [(t_req, "driver", ask), (t_req + timedelta(seconds=35), "rider", yes)]
    if spec["stop"] == "named":
        stop_place = spec["loops"][0]["place"]
        t_req = seg_start[0] - timedelta(seconds=240)
        ask = f"Can you stop at {stop_place}? I need to grab a parcel, 3-4 minutes."
        okm = "Ok"
        flagged(ask, {"request"}); flagged(okm, {"agreement"})
        chat_lines += [(t_req, "rider", ask), (t_req + timedelta(seconds=30), "driver", okm)]
    elif spec["stop"] == "unnamed":
        t_req = seg_start[0] - timedelta(seconds=240)
        ask = "Can you stop at a 7-Eleven on the way? Just need 2 minutes."
        okm = "Ok"
        flagged(ask, {"request"}); flagged(okm, {"agreement"})
        chat_lines += [(t_req, "rider", ask), (t_req + timedelta(seconds=30), "driver", okm)]
    if spec["threat"] == "driver":
        t = pickup_at + timedelta(seconds=total_s // 2)
        chat_lines += [(t, "rider", "Why are we going this way? This is not the route on the app."),
                       (t + timedelta(seconds=45), "driver", "Shut up and let me drive.")]
        flagged("Shut up and let me drive.", {"threat"})
    elif spec["threat"] == "trap":
        t = accepted + timedelta(seconds=60)
        line = "I'll find you at the lobby, I am in a red jacket."
        flagged(line, {"threat"})
        chat_lines += [(t, "rider", line)]
    if not chat_lines and rng.random() < 0.5:
        t = accepted + timedelta(seconds=50)
        chat_lines += [(t, INNOCUOUS[0][0], INNOCUOUS[0][1]), (t + timedelta(seconds=30), INNOCUOUS[1][0], INNOCUOUS[1][1])]
        for _, _, txt in chat_lines:
            flagged(txt, set())
    chat_lines.sort(key=lambda x: x[0])
    for t, _, _ in chat_lines:
        assert accepted <= t <= dropoff_at, f"{spec['name']}: chat at {t} outside the trip"

    # ---- fare, statements, profiles ----
    fare = metered_fare(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), rates) if service == "RydeTAXI" else fixed_fare(route, rates)
    extra_km = sum(f["extra_km"] for f in found)
    weather = WEATHER[spec["weather"]]
    rider_lines = {
        "none": f"The app estimated {route['total_km']:.0f} km but the driver went a different way and the meter came to {fare['distance_km']:.0f} km. He never asked me. I want the extra distance refunded.",
        "before": "The driver took a longer way round than the app showed and I paid more than the estimate. I want the difference back.",
        "after": "The driver only mentioned the different route after he had already turned off. I was overcharged for the extra distance.",
        "request_only": "The driver asked about another road but I did not reply; he went anyway and the fare was higher than the estimate.",
        "scope_other": "I agreed to a quick petrol stop, not to a long loop. The meter was higher than the estimate and he never stopped for petrol anyway.",
        "before_seg1": "I agreed to go round the jam near the start, but later he went off the route a second time without asking. I want that part refunded.",
    }
    statement = rider_lines.get(consent, rider_lines["none"])
    if spec["stop"] == "named":
        statement = f"I asked to stop at {stop_place} and we did, fine, but the fare was much more than the estimate. I think the detour was overcharged."
    elif spec["stop"] == "unnamed":
        statement = "I asked for a quick 7-Eleven stop on the way, not a drive to one far off the route. The meter was way above the estimate."
    elif not found:
        statement = f"The fare was higher than I expected for this trip in heavy rain, the driver must have taken a longer route."
    elif spec["threat"] == "driver":
        statement = "The driver went a different way and when I asked he told me to shut up. I was overcharged and felt unsafe."
    if inc_kind in ("on_stretch", "seg1") and consent == "none":
        statement = "The driver left the route the app showed and the meter was higher than the estimate. I never agreed to any change."
    driver_lines = {
        "none": "I followed my GPS; it rerouted me. Nothing wrong with the fare.",
        "before": f"Traffic was building up ahead so I asked the rider before turning off via {detour_road.get(0, 'the alternative road')} and the rider agreed.",
        "after": f"I told the rider I was going via {detour_road.get(0, 'another road')} and the rider said sure.",
        "request_only": "I asked the rider about the alternative road; no objection, so I took it.",
        "scope_other": "The rider agreed to a short stop so I thought a small change of route was fine.",
        "before_seg1": "I asked about going round the jam and the rider agreed. The second turn-off was my GPS rerouting.",
    }
    dstmt = driver_lines.get(consent, driver_lines["none"])
    if inc_kind in ("on_stretch", "seg1"):
        dstmt = f"There was an accident on {stretch_roads[0].title()} ahead, lanes were blocked, so I went round it. The extra distance was unavoidable."
    elif inc_kind == "late":
        dstmt = f"There was an accident on {stretch_roads[0].title()}; I went round it. The extra distance was unavoidable."
    elif inc_kind == "decoy_far":
        dstmt = "There was a breakdown on the route, the whole road was slow, so I took another way. Check the LTA incident feed."
    if spec["band"] and inc_kind == "none":
        dstmt = f"{stretch_roads[0].title()} was crawling" + (" and flooding in the heavy rain" if spec["weather"] == "heavy" else "") + ", so I went round it. Any driver would have done the same."
    if spec["stop"] == "named":
        dstmt = f"The rider asked me to stop at {stop_place}, so I drove there and waited while the rider went in."
    elif spec["stop"] == "unnamed":
        dstmt = "The rider asked for a 7-Eleven stop. I went to the one I know and waited."
    if not found:
        dstmt = "I followed the app route exactly. The meter is what it is; it was raining and traffic was slow."
    flagged(dstmt, set(_flags(dstmt)) - {"threat"})  # statements must never carry a threat keyword
    prior = spec["prior"]
    r_prof = (rng.randint(120, 1500), round(rng.uniform(4.5, 5.0), 1), rng.randint(0, 2), 0, 0, 0)
    d_dis = max(prior, rng.randint(0, 2))
    d_prof = (rng.randint(300, 2400), round(rng.uniform(4.4, 4.95), 2), rng.randint(300, 1300), d_dis + rng.randint(0, 2), d_dis, prior, 0)
    filed_at = dropoff_at + timedelta(minutes=rng.randint(20, 90))
    case = {
        "case_id": spec["case_id"],
        "dispute": {"type": "route_deviation", "filed_by": "rider", "filed_at": iso(filed_at), "statement": statement},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {"speed_bands": bands, "incidents": incidents},
        "weather": weather,
        "fare": fare,
        "chat": msgs(*chat_lines),
        "driver_statement": dstmt,
        "profiles": profiles(r_prof, d_prof),
    }
    # what the scenario knows about the interpretive slots, per segment (in time order)
    exempt_by_scenario = []
    for k in range(len(found)):
        if consent == "before":
            exempt_by_scenario.append(True)
        elif consent == "before_seg1":
            exempt_by_scenario.append(k == 0)
        elif spec["stop"] == "named":
            exempt_by_scenario.append(True)
        else:
            exempt_by_scenario.append(False)   # after / request_only / scope_other / unnamed stop / none
    meta = {"segments": found, "stretch_roads": stretch_roads, "detour_roads": detour_road, "exempt_by_scenario": exempt_by_scenario,
            "extra_km": round(extra_km, 2), "stop_place": stop_place}
    return case, meta


# ----------------------------------------------------------------------------------------------- no-show cases

def build_noshow(spec, rates, rp, idx, rng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    accepted = spec["day"]
    by = spec["by"]
    weather = WEATHER[spec["weather"]]
    chat_lines = []
    pressed = None
    if by == "driver":
        park_m = spec["park_m"]
        away = (bearing(D, P) + rng.uniform(-30, 30)) % 360          # park on the far side from the destination
        spot = offset(P, away, park_m) if park_m > 0 else P
        wait_s = spec.get("wait_s") or spec["within_s"]

        def trace(wait):
            cancelled = accepted + timedelta(seconds=approach_s + wait)
            return cancelled, build_trajectory(poly, accepted, secs(accepted, cancelled),
                                               stops=[Stop(*spot, start_s=approach_s, duration_s=wait, jitter_m=2.0,
                                                           anchor_s=60, away_from=P if park_m > 200 else None)], seed=spec["seed"])
        for att in range(12):
            start = offset(spot, (away + rng.uniform(-70, 70)) % 360, rng.choice([800, 1000, 1200]))
            try:
                approach = rp.route([start, spot])
            except urllib.error.HTTPError:
                continue
            poly = approach["polyline"]
            if approach["total_km"] > 3.2:
                continue        # one-way systems can turn 1.1 km as the crow flies into a long drive; pick another start
            approach_s = max(120, r5(approach["total_km"] / 25 * 3600))   # ~25 km/h on city streets
            cancelled, gps = trace(wait_s)
            dmin_before = min(haversine_m((p["lat"], p["lon"]), P) for p in gps if secs(accepted, datetime.fromisoformat(p["ts"])) < approach_s)
            if park_m > 200 and dmin_before <= 200:
                continue        # the approach must not brush the pickup radius when the story is "never arrived"
            break
        else:
            raise RuntimeError(f"{spec['name']}: no usable approach (length / 200 m radius)")
        park_at = accepted + timedelta(seconds=approach_s)
        if "within_s" in spec:   # land NS-1(iii)'s measure (seconds inside 200 m after the tap) exactly on the target
            got = after_tap_s(gps, P, park_at + timedelta(seconds=20), cancelled)
            wait_s += spec["within_s"] - got
            cancelled, gps = trace(wait_s)
            assert after_tap_s(gps, P, park_at + timedelta(seconds=20), cancelled) == spec["within_s"], spec["name"]
        pressed = park_at + timedelta(seconds=20) if spec["here"] else None
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=30), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by="driver")
        kind = spec.get("chat")
        plate = rng.choice(["silver Toyota Altis", "white Honda Vezel", "black Hyundai Ioniq", "grey Kia Niro"])
        if park_m > 200:
            chat_lines = [(park_at + timedelta(seconds=25), "driver", f"I'm here already, {plate}, please come out"),
                          (park_at + timedelta(seconds=80), "rider", "I'm at the pickup point and I don't see any car. Where are you?"),
                          (cancelled - timedelta(seconds=10), "driver", "Waited more than 3 min, cancelling")]
            statement = "The driver marked arrived but was never at the pickup point. I waited there the whole time and then got charged $6.61 as a no-show."
            dstmt = f"I pressed I'm Here and waited more than 3 minutes at the pickup. The rider never showed up, so I cancelled as a no-show."
        elif kind == "two_more":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here at the pickup point, {plate}."),
                          (park_at + timedelta(seconds=100), "rider", "Coming down, give me 2 more minutes"),
                          (cancelled - timedelta(seconds=15), "driver", "Called twice, no answer. Cancelling.")]
            statement = "It was pouring and I told the driver I needed two more minutes. He cancelled and I was charged $6.61."
            dstmt = "I waited more than 4 minutes at the pickup in the rain and called twice. The rider never came."
        elif kind == "driver_claims":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here, {plate}."),
                          (cancelled - timedelta(seconds=10), "driver", "Cancelling, waited too long")]
            statement = "The driver cancelled barely two minutes after arriving and I was charged $6.61."
            dstmt = "I waited at least 5 minutes at the pickup and the rider did not come. I cancelled as a no-show."
        elif kind == "threat":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here, {plate}."),
                          (park_at + timedelta(seconds=120), "rider", "2 min, coming"),
                          (cancelled - timedelta(seconds=20), "driver", "Hurry up or I will find you and you will regret it.")]
            flagged(chat_lines[-1][2], {"threat"})
            statement = "The driver threatened me in the chat and then cancelled and charged me $6.61."
            dstmt = "I waited more than 4 minutes. The rider kept saying 2 minutes. I cancelled as a no-show."
        elif not spec["here"]:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"At the pickup point, {plate}."),
                          (cancelled - timedelta(seconds=10), "driver", "Waited 4 min, cancelling")]
            statement = "The driver cancelled and I was charged $6.61. I was on my way down."
            dstmt = "I waited 4 minutes at the pickup and cancelled as a no-show. I forgot to press the I'm Here button but I was there."
        elif park_m >= 150:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here, {plate}, at the side road."),
                          (park_at + timedelta(seconds=120), "rider", "I'm at the entrance, I don't see you"),
                          (cancelled - timedelta(seconds=10), "driver", "Waited more than 3 min, cancelling")]
            statement = "The driver was not at the entrance where the pin was. He cancelled and I was charged $6.61."
            dstmt = "I was parked at the pickup, a short walk from the entrance, pressed I'm Here and waited more than 3 minutes."
        else:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here at the pickup point, {plate}."),
                          (cancelled - timedelta(seconds=10), "driver", "Waited more than 3 min, cancelling")]
            if wait_s >= 180:
                statement = "I came out a minute after the driver cancelled. I was charged $6.61 for nothing."
                dstmt = "I pressed I'm Here and waited more than 3 minutes. Rider no-show, so I cancelled."
            else:
                statement = "The driver cancelled on me after barely two minutes and I was charged $6.61."
                dstmt = "I pressed I'm Here and waited for the rider, then cancelled as a no-show."
        end = cancelled
    else:  # rider cancelled
        cancel_s = spec["cancel_s"]
        cancelled = accepted + timedelta(seconds=cancel_s)
        if spec["driver"] == "en_route":
            start = offset(P, (bearing(D, P) + rng.uniform(-30, 30)) % 360, 2600)
            approach = rp.route([start, P])
            full = [tuple(p) for p in approach["polyline"]]
            cum = along_km(full)
            drive_km = 30.0 / 3600 * cancel_s          # 30 km/h; the driver is still on the way when the rider cancels
            cut = vertex_at(full, cum, drive_km)
            poly = full[:max(cut, 2) + 1]
            gps = build_trajectory(poly, accepted, cancel_s, seed=spec["seed"])
            chat_lines = [(accepted + timedelta(seconds=40), "rider", "How long will you be?"),
                          (accepted + timedelta(seconds=70), "driver", "About 5 min, traffic")] if cancel_s > 120 else []
            for _, _, txt in chat_lines:
                flagged(txt, set())
            statement = (f"The driver was still far away after {cancel_s // 60} minutes so I cancelled and booked another ride, and got charged $6.61."
                         if cancel_s > 180 else f"I cancelled within {cancel_s // 60} minutes because the driver was nowhere near, and still got charged $6.61.")
            dstmt = "I was on my way when the rider cancelled."
        else:  # driver parked at the pin, rider cancels late
            spot = offset(P, (bearing(D, P)) % 360, 40)
            for _ in range(12):
                start = offset(spot, (bearing(D, P) + rng.uniform(-70, 70)) % 360, 700)
                try:
                    approach = rp.route([start, spot])
                except urllib.error.HTTPError:
                    continue
                if approach["total_km"] <= 1.6:
                    break
            else:
                raise RuntimeError(f"{spec['name']}: no short approach to the pickup")
            park_s = min(max(120, r5(approach["total_km"] / 25 * 3600)), cancel_s - 150)
            gps = build_trajectory(approach["polyline"], accepted, cancel_s,
                                   stops=[Stop(*spot, start_s=park_s, duration_s=cancel_s - park_s, jitter_m=1.5)], seed=spec["seed"])
            pressed = accepted + timedelta(seconds=park_s + 15)
            chat_lines = [(pressed, "driver", "I'm here at the pickup, black Hyundai Ioniq."),
                          (accepted + timedelta(seconds=300), "rider", "Sorry, plans changed, I will cancel")]
            statement = "I cancelled because my plans changed and the driver had not even arrived. $6.61 is unfair."
            dstmt = "I was parked at the pickup for minutes when the rider cancelled."
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=30), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by="rider")
        end = cancelled
    chat_lines.sort(key=lambda x: x[0])
    for t, _, _ in chat_lines:
        assert accepted <= t <= end, f"{spec['name']}: chat at {t} outside accepted..cancelled"
    bands = gps_bands(approach, [], gps, accepted - timedelta(minutes=5), end + timedelta(minutes=5), max_n=1)
    prior_ns = spec["prior_ns"]
    r_prof = (rng.randint(120, 1500), round(rng.uniform(4.3, 5.0), 1), prior_ns + rng.randint(0, 1), prior_ns, 0, prior_ns)
    d_dis = rng.randint(0, 2)
    d_prof = (rng.randint(300, 2400), round(rng.uniform(4.4, 4.95), 2), rng.randint(300, 1300), d_dis + rng.randint(0, 1), d_dis, 0, d_dis)
    filed_at = end + timedelta(minutes=rng.randint(5, 60))
    case = {
        "case_id": spec["case_id"],
        "dispute": {"type": "no_show", "filed_by": "rider", "filed_at": iso(filed_at), "statement": statement},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {"speed_bands": bands, "incidents": []},
        "weather": weather,
        "fare": cancellation_fare(rates),
        "chat": msgs(*chat_lines),
        "driver_statement": dstmt,
        "profiles": profiles(r_prof, d_prof),
    }
    return case, {}


# ----------------------------------------------------------------------------------------------- safety cases

def build_safety(spec, rates, rp, idx, rng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    opt = [tuple(p) for p in route["polyline"]]
    pickup_at = spec["day"]
    approach_start, approach_s = approach_leg(rp, P, D, rng)
    accepted = pickup_at - timedelta(seconds=approach_s + 10)
    total_s = r5(along_km(opt)[-1] / avg_speed(route) * 3600)
    dropoff_at = pickup_at + timedelta(seconds=total_s)
    trip_gps = build_trajectory(opt, pickup_at, total_s, seed=spec["seed"])
    gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"]) + trip_gps[1:]
    service = spec["service"]
    trip = trip_block(f"T-{2000 + idx}", service, place(spec["pair"][0]), place(spec["pair"][1]), route,
                      accepted - timedelta(seconds=35), accepted, gps, pickup_at - timedelta(seconds=10), pickup_at, dropoff_at)
    mid = pickup_at + timedelta(seconds=total_s // 2)
    kind = spec["chat"]
    filed_by = "rider"
    if kind == "driver_threat":
        chat_lines = [(mid, "rider", "Please stop the car, I want to get out here."),
                      (mid + timedelta(seconds=60), "driver", "Sit down or I lock the doors.")]
        flagged(chat_lines[1][2], {"threat"})
        statement = "The driver threatened to lock me in when I asked to get out. I felt unsafe for the whole ride."
        dstmt = "The rider tried to open the door while we were moving. I told her to sit down for her own safety."
    elif kind == "rider_threat":
        chat_lines = [(mid, "driver", "Please do not smoke in the car."),
                      (mid + timedelta(seconds=40), "rider", "Say that again and I will punch you.")]
        flagged(chat_lines[1][2], {"threat"})
        filed_by = "driver"
        statement = "The passenger threatened to punch me when I asked him not to smoke. I want this reported."
        dstmt = "The passenger threatened to punch me when I asked him not to smoke. I want this reported."
    elif kind == "innocuous":
        chat_lines = [(accepted + timedelta(seconds=50), INNOCUOUS[0][0], INNOCUOUS[0][1]),
                      (accepted + timedelta(seconds=80), INNOCUOUS[1][0], INNOCUOUS[1][1])]
        for _, _, txt in chat_lines:
            flagged(txt, set())
        statement = "The driver was speeding and braking hard the whole way, overtaking on the shoulder. I was scared and felt unsafe."
        dstmt = "I drove normally. The rider was on the phone the whole trip and never complained to me."
        if spec.get("statement_threat"):
            dstmt = "The rider is stupid and was on the phone the whole trip. I drove normally."
    else:  # none
        chat_lines = []
        statement = "The driver kept making comments about my body and asked for my number. I felt harassed and unsafe."
        dstmt = "I made small talk. Nothing inappropriate happened."
    fare = metered_fare(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), rates) if service == "RydeTAXI" else fixed_fare(route, rates)
    bands = gps_bands(route, [], trip_gps, accepted - timedelta(minutes=5), dropoff_at + timedelta(minutes=5), max_n=2)
    r_prof = (rng.randint(120, 1500), round(rng.uniform(4.5, 5.0), 1), 0, 0, 0, 0)
    d_prof = (rng.randint(300, 2400), round(rng.uniform(4.6, 4.95), 2), rng.randint(300, 1300), 0, 0, 0, 0)
    filed_at = dropoff_at + timedelta(minutes=rng.randint(5, 40))
    case = {
        "case_id": spec["case_id"],
        "dispute": {"type": "safety", "filed_by": filed_by, "filed_at": iso(filed_at), "statement": statement},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {"speed_bands": bands, "incidents": []},
        "weather": WEATHER[spec["weather"]],
        "fare": fare,
        "chat": msgs(*chat_lines),
        "driver_statement": dstmt,
        "profiles": profiles(r_prof, d_prof),
    }
    return case, {}


# ----------------------------------------------------------------------------------------------- ground truth

def derive_truth(case_dict: dict, spec: dict, meta: dict) -> dict:
    """Run the fact tools + policy engine on the generated case, fill the interpretive slots from the scenario."""
    case = Case.model_validate(case_dict)
    table = build_fact_table(case)
    cert = evaluate(case, table)
    lines = cert.lines()
    kind = cert.dispute_type
    if kind == "safety":
        threat = any((f.value or {}).get("threat") for f in table.facts)
        cited = ["SAFE-1"] if threat else ["SAFE-1", "SAFE-2"]
        why = ("Threat keyword in the chat triggers SAFE-1: no automatic ruling, escalate with a fact summary."
               if threat else "Safety ticket without a keyword hit: SAFE-1/SAFE-2 still forbid an automatic ruling -> escalate.")
        if case.dispute.type != "safety":
            why = f"{case.dispute.type} dispute, but a chat message hits the threat keyword table -> SAFE-1 overrides every other clause: escalate."
        return {"ruling": "escalate", "amount": None, "cited_policy": cited, "escalate": True, "rationale": why,
                "flag_account": False, "_cert": lines}
    if kind == "no_show":
        ruling = cert.allowed[0]
        amount = CANCEL_FEE if ruling == "refund_full" else None
        by = case.trip.cancelled_by
        if by == "rider":
            cited = ["NS-0", "NS-4"]
        else:
            cited = ["NS-0", "NS-1"] + (["NS-2"] if ruling == "refund_full" else [])
            if not case.trip.driver_pressed_here_at:
                cited.append("NS-3")
        why = "; ".join(lines) + f". -> {ruling}" + (f" ${amount:.2f} (NS-7 voucher)" if amount else "") + (" + flag_account (NS-2 fake arrival tap)" if cert.flag_required else "")
        return {"ruling": ruling, "amount": amount, "cited_policy": cited, "escalate": False, "rationale": why,
                "flag_account": bool(cert.flag_required), "_cert": lines}
    # route deviation
    seg_ids = list(cert.segments)                       # fact ids in time order (gps-detour-k numbering)
    scen = meta.get("exempt_by_scenario", [])
    assert len(seg_ids) == len(scen), f"{spec['name']}: engine sees {len(seg_ids)} segments, scenario injected {len(scen)}"
    findings, notes = {}, []
    for fid, want in zip(seg_ids, scen):
        s = cert.segments[fid]
        if s["exempt"] is None:
            findings[fid] = want
            notes.append(f"{fid} interpretive slot ({s['why']}): scenario says {'exempt' if want else 'NOT exempt'}")
        else:
            # mechanical slot: the engine decided (RD-4 incident exempts; no candidate -> not exempt). The scenario's
            # own label only covers interpretive consent/stop scope, so an RD-4 exemption may override a False label.
            if s["exempt"] != want and not (s["exempt"] and spec["incident"] in ("on_stretch", "seg1")):
                raise AssertionError(f"{spec['name']}: engine says {fid} exempt={s['exempt']} but the scenario intended {want}")
            findings[fid] = s["exempt"]
            notes.append(f"{fid} mechanical: exempt={s['exempt']} ({s['why']})")
    metered = case.trip.service_type == "RydeTAXI"
    non_exempt = [fid for fid in seg_ids if not findings[fid]]
    amount = expected_amount(cert, findings) if metered else None
    if amount is not None and amount <= 0:
        amount = None
    ruling = "refund_partial" if (metered and amount) else "no_action"
    prior = case.profiles.driver.route_disputes_upheld_90d >= 1
    flag = bool(prior and non_exempt)
    cited = ["RD-1", "RD-2"] if seg_ids else ["RD-1"]
    if any(p.clause == "RD-4" and p.status == "pass" for p in cert.predicates):
        cited.append("RD-4")
    if any(p.clause == "RD-5" and p.status == "judge" for p in cert.predicates):
        cited.append("RD-5")
    if any(p.clause == "RD-3" and p.status == "judge" for p in cert.predicates):
        cited.append("RD-3")
    if flag:
        cited.append("RD-6")
    parts = [f"{len(seg_ids)} off-route segment(s) measured" if seg_ids else "no off-route segment: GPS follows the optimal route (RD-1 fails)"]
    parts += notes
    if metered and non_exempt:
        parts.append("refund = " + " + ".join(f"{cert.segments[f]['extra_km']:.2f} km" for f in non_exempt) + f" × ${cert.rate_per_km:.2f}/km = ${amount:.2f} (RD-2)")
    elif not metered and seg_ids:
        parts.append(f"{case.trip.service_type} is a fixed quote: no km refund (RD-2 non-metered branch)" + ("; RD-1 breach recorded" if non_exempt else ""))
    if flag:
        parts.append(f"driver has {case.profiles.driver.route_disputes_upheld_90d} upheld route disputes in 90 d and the case is upheld -> flag_account (RD-6)")
    elif prior and seg_ids:
        parts.append("driver has priors but no segment is upheld against him -> RD-6 not triggered")
    return {"ruling": ruling, "amount": amount, "cited_policy": cited, "escalate": False, "rationale": "; ".join(parts) + ".",
            "flag_account": flag, "_cert": lines}


# ----------------------------------------------------------------------------------------------- main

def validate_bench(case_dict: dict, spec: dict, rates, clauses) -> list[str]:
    validate.EXPECTED_DIR = EXPECTED_DIR
    errs = validate.check_case(case_dict, rates, clauses)
    if spec["kind"] == "no_show" and not spec.get("here", True):
        errs = [e for e in errs if "without an 'I'm Here' tap" not in e]   # that IS the scenario (NS-3)
    if spec["kind"] == "route_deviation" and not spec["loops"]:
        errs = [e for e in errs if "no off-route segment" not in e]        # deliberate hard negative (RD-1 fails)
    if spec["kind"] == "route_deviation" and spec["service"] == "RydeX" and spec["loops"]:
        # the meter check assumes a metered fare; for a fixed quote re-check the GPS km against the segments instead
        errs = [e for e in errs if "but the meter shows +0.00 km" not in e]
        t = case_dict["trip"]
        trip_gps = slice_gps(case_dict["gps"], t["pickup_at"], t["dropoff_at"])
        segs = measure_detours(trip_gps, [tuple(p) for p in case_dict["route"]["polyline"]])
        hidden = (distance_km(trip_gps) - case_dict["route"]["total_km"]) - sum(d["extra_km"] for d in segs)
        if not -0.1 <= hidden <= 1.0:
            errs.append(f"RydeX: segments leave {hidden:.2f} km of driven excess unexplained")
    return errs


def main(limit: int | None = None):
    rng0 = random.Random(SEED)
    rates = load_rates()
    clauses = validate.policy_clauses()
    rp = routes()
    for d in (CASES_DIR, EXPECTED_DIR):
        os.makedirs(d, exist_ok=True)
        for old in os.listdir(d):          # a renumbered scenario must not leave a stale case behind
            if old.startswith("B-") and old.endswith(".json"):
                os.remove(os.path.join(d, old))
    day0 = datetime(2026, 9, 25, 8, 0, 0, tzinfo=SGT)
    hours = [8, 9, 12, 14, 17, 18, 21, 22]
    manifest, failures = [], []
    specs = SCENARIOS[:limit] if limit else SCENARIOS
    for i, spec in enumerate(specs, 1):
        spec = dict(spec)
        spec["case_id"] = f"B-{i:04d}"
        spec["seed"] = SEED + i
        spec["day"] = (day0 + timedelta(days=i // 2)).replace(hour=hours[i % len(hours)], minute=(i * 7) % 60, second=0)
        rng = random.Random(SEED * 7 + i)
        builder = {"route_deviation": build_route, "no_show": build_noshow, "safety": build_safety}[spec["kind"]]
        try:
            case, meta = builder(spec, rates, rp, i, rng)
            truth = derive_truth(case, spec, meta)
            expected = {k: v for k, v in truth.items() if not k.startswith("_")}
            with open(os.path.join(EXPECTED_DIR, f"{spec['case_id']}.json"), "w") as f:
                json.dump(expected, f, indent=2, ensure_ascii=False)
                f.write("\n")
            dump(case, os.path.join(CASES_DIR, f"{spec['case_id']}.json"))
            errs = validate_bench(case, spec, rates, clauses)
            if errs:
                failures.append((spec["case_id"], spec["name"], errs))
            cond = {k: v for k, v in spec.items() if k not in ("seed", "day", "case_id", "name", "kind", "hard", "pair")}
            manifest.append({
                "case_id": spec["case_id"], "name": spec["name"], "type": spec["kind"], "pair": list(spec["pair"]),
                "conditions": cond, "truth": expected, "hard": spec["hard"],
                "segments": meta.get("segments", []), "stretch_roads": meta.get("stretch_roads", []),
                "certificate": truth["_cert"], "validate_errors": errs,
            })
            seg = "".join(f" seg +{s['extra_km']:.2f}km" for s in meta.get("segments", []))
            print(f"{spec['case_id']} {spec['name']:36} {expected['ruling']:14} {expected['amount'] or '':>6} flag={expected['flag_account']!s:5}{seg} {'FAIL ' + str(errs) if errs else 'ok'}")
        except Exception as e:  # noqa: BLE001
            failures.append((spec["case_id"], spec["name"], [f"{type(e).__name__}: {e}"]))
            print(f"{spec['case_id']} {spec['name']:36} BUILD FAILED {type(e).__name__}: {e}")
    with open(os.path.join(BENCH_DIR, "manifest.json"), "w") as f:
        json.dump({"seed": SEED, "generated_by": "data/synth/scenarios.py", "cases": manifest}, f, indent=1, ensure_ascii=False)
    by_type = {}
    for m in manifest:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1
    print(f"\n{len(manifest)} cases written: {by_type}; {len(failures)} failure(s)")
    for cid, name, errs in failures:
        print(f"  {cid} {name}: {errs}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
