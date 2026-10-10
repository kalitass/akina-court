#!/usr/bin/env python3
"""Parametric benchmark generator: composes the build_cases.py helpers over a grid of conditions and writes

    data/bench/cases/B-0001.json ...      Case files (same schema as data/cases/)
    data/bench/expected/B-0001.json ...   {ruling, amount, cited_policy, escalate, rationale, flag_account}
    data/bench/manifest.json              per case: type, conditions, ground truth, what makes it hard

    set -a; . ./.env; set +a; unset ONEMAP_TOKEN      # the .env token expires every 72 h; email+password refreshes it
    .venv/bin/python data/synth/scenarios.py          # legs already in onemap_cache.json need no network

Ground truth is DERIVED, not typed: every generated case is run through core.facts.tools.build_fact_table and
core.policy_engine.evaluate; the mechanical slots (segment exists, incident on the replaced stretch, consent timing,
I'm Here tap, 200 m radius, 180 s grace) come from the engine, the interpretive slots (did the rider agree, does the
rider's consent / stop request cover this segment) are filled from what the scenario injected, and the two must
agree or the generator aborts. Deterministic for a fixed SEED and a warm OneMap cache.
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import urllib.error
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import contract  # noqa: E402
import validate  # noqa: E402
from build_cases import (LOC, PAUSE_S, ROADS, SGT, Congestion, Stop, along_km, approach_trace, band_from_gps, build_trajectory,  # noqa: E402
                         compose, detour_trace, dump, incident, measure_detours, nearest_idx, offset, pause_stops, place, profiles,
                         project, routes, secs, trip_block)
from fare import cancellation_fare, distance_km, fixed_fare, load_rates, metered_fare, slice_gps  # noqa: E402
from route_provider import haversine_m  # noqa: E402

from core.facts.tools import build_fact_table  # noqa: E402
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
    # more origins / destinations (OneMap search, 2026-10-10) so the same route does not carry a dozen cases
    "AMK Hub": (1.3694, 103.8484),
    "Toa Payoh HDB Hub": (1.3321, 103.8485),
    "NEX Serangoon": (1.3508, 103.8722),
    "VivoCity": (1.2643, 103.8223),
    "Suntec City": (1.2955, 103.8585),
    "Junction 8": (1.3505, 103.8487),
    "Jurong Point": (1.3395, 103.7066),
    "Pasir Ris MRT": (1.3730, 103.9492),
    "Hougang Mall": (1.3725, 103.8937),
    "Buona Vista MRT": (1.3063, 103.7903),
    "Kallang Wave Mall": (1.3031, 103.8731),
    "Compass One": (1.3921, 103.8950),
})
# where a rider waits at each pickup (the pickup line names it, instead of a "main entrance" that a kerb or a campus has not)
PICKUP_SPOT = {
    "Orchard Road": "at the kerb outside Mandarin Gallery", "NUS": "outside University Hall", "Raffles Place": "at the Raffles Place taxi stand",
    "Clarke Quay": "at the Clarke Quay taxi stand", "Bugis Junction": "at the Victoria Street entrance", "Marina Bay Sands": "at the Tower 1 taxi stand",
    "Tanjong Pagar Centre": "at the taxi stand", "Sentosa Beach Station": "outside Beach Station", "Jurong East MRT": "at the taxi stand outside the MRT",
    "Woodlands Civic Centre": "at the main entrance", "Punggol Waterway Point": "at the taxi stand", "Tampines Mall": "at the taxi stand",
    "Bedok Mall": "at the taxi stand", "Changi Airport T3": "at the arrival pickup, door 3", "AMK Hub": "at the taxi stand", "Toa Payoh HDB Hub": "at the taxi stand",
    "NEX Serangoon": "at the taxi stand", "VivoCity": "at the taxi stand", "Suntec City": "at the Tower 3 drop-off", "Junction 8": "at the taxi stand",
    "Jurong Point": "at the taxi stand", "Pasir Ris MRT": "at the taxi stand outside the MRT", "Hougang Mall": "at the taxi stand",
    "Buona Vista MRT": "outside exit A", "Kallang Wave Mall": "at the taxi stand", "Compass One": "at the taxi stand",
}
CARS = ["silver Toyota Altis", "white Honda Vezel", "black Hyundai Ioniq", "grey Kia Niro", "blue Toyota Prius", "white BYD e6"]
OUTFITS = ["in a blue shirt", "in a grey hoodie", "with a black backpack", "in a white dress", "in a red cap"]

WEATHER = {"fair": {"rain_mm": 0, "description": "Fair"},
           "light": {"rain_mm": 1.8, "description": "Light rain"},
           "heavy": {"rain_mm": 18.5, "description": "Heavy rain, thundery showers"}}
BAND_SPEED = {1: 8.0, 2: 15.0}           # km/h injected on the stretch before the detour -> LTA band
CONGESTION_LEN_KM = 0.45
CRAWL_PAST_KM = 0.5                      # the crawl runs this far past the turn-off (the slip road is in the same jam), so the
                                         # 150 s before the measured segment start are still at crawling speed
MAX_DETOUR_RATIO = 4.0                   # a loop may drive at most this many times the stretch it replaces (what the road network allows)
MIN_REPLACED_PLAIN_KM = 0.5              # a plain loop (no incident, no agreement on it) must still replace this much of the route: no out-and-back spur
OFFSET_CANDIDATES = [(1, 1000), (-1, 1000), (1, 1500), (-1, 1500), (1, 700), (-1, 700), (1, 2000), (-1, 2000)]
SPAN_CANDIDATES = [(1.0, 1.0), (1.5, 1.5), (0.7, 0.7), (2.0, 2.0), (1.0, 2.0), (2.0, 1.0)]
APPROACH_PAUSE_S = 75                    # the driver's pickup message is typed at a halt this many seconds into the approach

# LTA DataMall writes an expressway incident with its direction ("(towards TPE)"); axis says which end of the road each label names
EXPRESSWAY_DIR = {
    "SELETAR EXPRESSWAY": ("EW", "towards TPE", "towards BKE"),
    "AYER RAJAH EXPRESSWAY": ("EW", "towards MCE", "towards Tuas"),
    "TAMPINES EXPRESSWAY": ("EW", "towards PIE", "towards SLE"),
    "PAN ISLAND EXPRESSWAY": ("EW", "towards Changi", "towards Tuas"),
    "EAST COAST PARKWAY": ("EW", "towards Changi", "towards MCE"),
    "MARINA COASTAL EXPRESSWAY": ("EW", "towards ECP", "towards AYE"),
    "KRANJI EXPRESSWAY": ("EW", "towards BKE", "towards PIE"),
    "CENTRAL EXPRESSWAY": ("NS", "towards SLE", "towards AYE"),
    "KALLANG PAYA LEBAR EXPRESSWAY": ("NS", "towards TPE", "towards MCE"),
    "BUKIT TIMAH EXPRESSWAY": ("NS", "towards Woodlands", "towards PIE"),
}

# ordinary pickup chatter; what any line means is for the court to read, nothing is labelled. Several wordings per line,
# chosen by the case's own rng, so a judge opening ten files does not meet the same sentence ten times.
PICKUP_LINES = ["Hi, I am {spot}, {outfit}.", "Hello, waiting {spot}, {outfit}.", "I'm {spot} already, {outfit}."]
ARRIVING_LINES = ["Arriving in about {n} min, {car}.", "On my way, about {n} min, {car}.", "{n} min away, {car}."]
ASK_LINES = ["Traffic ahead on {jam} is building up, ok if I go round via {alt}?",
             "Jam on {jam} is building up ahead, can I go round via {alt}?",
             "Looks like traffic on {jam} is building up, mind if I go round via {alt}?"]
ASK_GENERAL_LINES = ["Traffic ahead on {jam} is building up, shall I take another way?",
                     "Jam on {jam} is building up ahead, want me to take another way?"]
YES_LINES = ["Sure, go ahead.", "Sure, no problem.", "Sure, your call."]
HERE_LINES = ["I'm here at the pickup point, {car}.", "Reached, {car}, waiting at the pickup.", "At the pickup now, {car}."]
HERE_FAR_LINES = ["I'm here already, {car}, please come out", "Reached already, {car}, come out please"]
WHERE_LINES = ["I'm at the pickup point and I don't see any car. Where are you?", "I'm at the pickup point, no car here. Where are you?"]
CANCEL_LINES = ["Waited more than {n} min, cancelling", "More than {n} min already, I have to cancel", "{n} min up, cancelling the trip"]
HOW_LONG_LINES = ["How long will you be?", "Hi, how far are you?", "Are you near?"]
ETA_LINES = ["About 5 min, traffic", "5 min more, traffic is slow", "Coming, about 5 min"]
GPS_LINES = ["I followed my GPS; it rerouted me. Nothing wrong with the fare.",
             "I went where the GPS sent me; it rerouted. The fare is what the meter showed.",
             "The GPS rerouted me, that's all. Nothing wrong with the fare."]
NOSHOW_DRIVER_LINES = ["I pressed I'm Here and waited more than {n} minutes. Rider no-show, so I cancelled.",
                       "I tapped I'm Here, waited over {n} minutes, nobody came, so I cancelled as a no-show.",
                       "After pressing I'm Here I waited more than {n} minutes at the pickup. No rider, so I cancelled."]
ON_WAY_LINES = ["I was on my way when the rider cancelled.", "I was driving to the pickup when the rider cancelled.",
                "The rider cancelled while I was still on the way."]
CAME_OUT_LINES = ["I came out a minute after the driver cancelled. I was charged ${fee} for nothing.",
                  "I got downstairs a minute after he cancelled and was charged ${fee} for nothing.",
                  "By the time I came out he had cancelled, and I was charged ${fee} anyway."]
RIDER_NONE_LINES = ["The app estimated {est} km but the driver went a different way and the meter came to {got} km. He never asked me. I want the extra distance refunded.",
                    "The app estimated {est} km; the driver turned off the route without a word and the meter read {got} km at the end. Please refund the extra distance.",
                    "My app estimated {est} km. The driver took some other way and the meter ended at {got} km. He never asked. I want the difference refunded."]


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
      hard="plain unexplained loop; the only trap is the rider overstating the extra km -> refund the measured extra km"),
    R("rd_consent_before", ("Clarke Quay", "Bedok Mall"), loops=[{"frac": (0.55, 0.72)}], consent="before", band=2,
      hard="RD-5: the rider agreed to a named road 3 min before the segment, but no record ties the driven segment to that road (G13) -> undetermined, a person decides"),
    R("rd_consent_after", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.35, 0.60)}], consent="after", band=2,
      hard="same chat as rd_consent_before but timestamped after the segment started -> RD-5 fails, refund"),
    R("rd_incident_on_stretch", ("Woodlands Civic Centre", "Punggol Waterway Point"), loops=[{"frac": (0.30, 0.52)}], incident="on_stretch",
      hard="RD-4(a): accident on the replaced stretch reported before -> exempt; the rider's complaint is loud"),
    R("rd_incident_decoy", ("Tanjong Pagar Centre", "Changi Airport T3"), loops=[{"frac": (0.30, 0.45)}], incident="decoy_far",
      hard="an accident exists on the optimal route but 2+ km from the replaced stretch -> no exemption, refund"),
    R("rd_incident_late", ("Bugis Junction", "Jurong East MRT"), loops=[{"frac": (0.50, 0.65)}], incident="late",
      hard="accident on the stretch but reported after the driver had already left the route -> no exemption, refund"),
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
      hard="two segments; the rider agreed to a named road for the first only; nothing ties segment 1 to that road (G13) -> undetermined on 1, counts on 2 -> a person decides the amount"),
    R("rd_two_segs_incident_seg1", ("Marina Bay Sands", "Tampines Mall"), loops=[{"frac": (0.25, 0.38)}, {"frac": (0.62, 0.75)}], incident="seg1",
      hard="two segments; accident exempts the first, the second is unexplained -> refund segment 2 only"),
    R("rd_two_segs_plain", ("Tanjong Pagar Centre", "Changi Airport T3"), loops=[{"frac": (0.25, 0.38)}, {"frac": (0.62, 0.75)}],
      hard="two unexplained segments -> refund the sum"),
    R("rd_fixed_fare", ("Bugis Junction", "Jurong East MRT"), loops=[{"frac": (0.50, 0.65)}], service="RydeX",
      hard="RydeX is a fixed quote: real detour, zero refundable km -> no_action (RD-2 non-metered branch)"),
    R("rd_fixed_fare_consent", ("Punggol Waterway Point", "Tampines Mall"), loops=[{"frac": (0.30, 0.50)}], service="RydeX", consent="before", band=2,
      hard="fixed fare + agreement to a named road: the finding changes no amount and no flag -> may stay undetermined, no_action either way"),
    R("rd_prior_flag", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.35, 0.60)}], prior=2,
      hard="RD-6: driver has 2 upheld route disputes -> refund + flag_account"),
    R("rd_fixed_fare_prior_flag", ("Orchard Road", "NUS"), loops=[{"frac": (0.35, 0.55)}], service="RydeX", prior=2,
      hard="fixed fare so no refund, but RD-1 breach + 2 priors -> no_action + flag_account"),
    R("rd_no_deviation", ("Tampines Mall", "Changi Airport T3"), loops=[], weather="heavy",
      hard="rider complains the fare felt high; GPS follows the optimal route -> RD-1 fails, no_action"),
    R("rd_request_only", ("Clarke Quay", "Sentosa Beach Station"), loops=[{"frac": (0.30, 0.50)}], consent="request_only", band=2,
      hard="driver asked, rider never answered -> no agreement, RD-5 fails -> refund"),
    R("rd_scope_other", ("Woodlands Civic Centre", "Punggol Waterway Point"), loops=[{"frac": (0.40, 0.55)}], consent="scope_other",
      hard="rider agreed to a 1-min petrol stop just ahead; the segment is an unrelated 1-2 km loop with no stop -> consent does not cover it, refund"),
    R("rd_consent_before_prior", ("Raffles Place", "Changi Airport T3"), loops=[{"frac": (0.45, 0.60)}], consent="before", band=2, prior=2,
      hard="agreement to a named road with no record tying the segment to it (G13); with 2 priors the RD-6 flag depends on the finding -> undetermined, a person decides"),
    R("rd_threat_in_chat", ("Marina Bay Sands", "Tampines Mall"), loops=[{"frac": (0.40, 0.55)}], threat="driver",
      hard="route dispute whose chat holds an intimidating driver message -> the judge's safety screen (SAFE-1) overrides: escalate, no refund computed"),
    R("rd_consent_before_light", ("Bugis Junction", "Jurong East MRT"), loops=[{"frac": (0.50, 0.65)}], consent="before", band=2, weather="light", incident="decoy_far",
      hard="agreement to a named road, no record tying the segment to it (G13); the decoy incident is far from the route and settles nothing -> undetermined, a person decides"),
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
      hard="NS-4: 200 s after matching -> fee stands even though the driver was still over a kilometre away ('driver was late' is not a Ryde rule, NS-8)"),
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
      hard="no-show facts favour the driver, but the chat holds an intimidating driver message -> safety screen: escalate"),
    N("ns_rider_cancel_100s_bad_profile", ("Marina Bay Sands", "Tampines Mall"), by="rider", cancel_s=100, driver="en_route", prior_ns=2,
      hard="rider has 2 upheld no-show disputes; still inside grace -> refund"),
    N("ns_wait_4min_180m", ("Clarke Quay", "Sentosa Beach Station"), by="driver", park_m=180, wait_s=240, here=True,
      hard="parked 180 m from the pin (inside the 200 m radius), rider says 'not at the entrance' -> fee stands"),
    # ---- safety ------------------------------------------------------------------------------------------------
    S("safe_driver_threat", ("Clarke Quay", "Bedok Mall"), chat="driver_threat",
      hard="SAFE-1: driver threatens to lock the rider in -> escalate"),
    S("safe_rider_threat", ("Tampines Mall", "Changi Airport T3"), chat="rider_threat", service="RydeTAXI",
      hard="SAFE-1: rider threatens the driver; the driver filed -> escalate, no refund"),
    S("safe_innocuous_chat_dangerous_driving", ("Jurong East MRT", "NUS"), chat="innocuous",
      hard="innocuous chat; the complaint alleges dangerous driving -> SAFE-2 escalate"),
    S("safe_no_chat_harassment", ("Woodlands Civic Centre", "Punggol Waterway Point"), chat="none", weather="heavy",
      hard="no chat at all; harassment alleged in the statement -> escalate (SAFE-1 via type)"),
    S("safe_keyword_only_in_statement", ("NUS", "Raffles Place"), chat="innocuous", statement_threat=True,
      hard="the only hint word is in the driver's own statement, not the chat; still a safety ticket -> escalate"),
    R("rd_keyword_trap_find_you", ("Orchard Road", "NUS"), loops=[{"frac": (0.35, 0.55)}], threat="trap",
      hard="route dispute; rider wrote 'I'll find you at the pickup' (a pickup arrangement that contains a threat hint word) -> the court must read it as ordinary chat and rule on the detour: refund"),
]


# ----------------------------------------------------------------------------------------------- route cases

FRAC_SHIFTS = [0.0, 0.08, -0.08, 0.16, -0.16]
MIN_REPLACED_KM = contract.MIN_REPLACED_KM   # a loop whose story goes round a stretch must really bypass this much of the optimal route


def loop_must_bypass(spec: dict) -> bool:
    """True when the story says the first loop goes ROUND a stretch: an accident on it (RD-4 tests whether the incident sits on
    the replaced stretch), "go round via X to avoid Y" (the car must not drive the whole of Y), or "take whichever way is
    faster" (a loop that reaches nothing is a driver's errand)."""
    return spec["incident"] in ("on_stretch", "seg1", "late") or spec["consent"] in contract.ROAD_NAMING_CONSENT + ("general", "general_cn")
MIN_EXTRA_KM = 0.6                           # candidate floor: the trace is re-sampled once the halts are in, 0.5 exactly could fall under it


def crawl_reaches_segment(trip_gps, seg_start: str, level: int) -> bool:
    """The contract's own reading of a band record: the median moving speed in the 150 s before the measured segment start
    sits in the band (LTA band 1: 0-9 km/h, band 2: 10-19 km/h)."""
    t0 = datetime.fromisoformat(seg_start)
    pre = [p["speed_kmh"] for p in trip_gps if t0 - timedelta(seconds=150) <= datetime.fromisoformat(p["ts"]) < t0 and p["speed_kmh"] >= 5]
    lo, hi = {1: (0, 9), 2: (10, 19)}[level]
    return bool(pre) and lo <= statistics.median(pre) <= hi + 1
OFFLINE_SKIPS: dict[str, int] = {}           # scenario -> loop candidates skipped because their leg is not in the cache (no token)


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


def is_expressway(name: str) -> bool:
    return any(w in name for w in ("EXPRESSWAY", "PARKWAY", "HIGHWAY"))


def avg_speed(route) -> float:
    """Cruising speed for a trip: 40 km/h when the optimal route has a long expressway-class run (ECP and the highways
    included), else 30 km/h."""
    return 40.0 if any(is_expressway(r["name"]) and r["to_m"] - r["from_m"] > 3000 for r in route["roads"]) else 30.0


def surface_km(route, km: float, margin_m: float = 150) -> float:
    """The along-track km nearest to `km` that lies on a surface road of the route (not inside an expressway run): where a
    car can halt at a junction. Returns `km` itself when it is already on a surface road."""
    runs = [(r["from_m"] / 1000, r["to_m"] / 1000) for r in route["roads"] if is_expressway(r["name"])]
    L = route["total_km"]
    if not any(a - margin_m / 1000 <= km <= b + margin_m / 1000 for a, b in runs):
        return km
    cands = []
    for a, b in runs:
        cands += [a - margin_m / 1000 - 0.1, b + margin_m / 1000 + 0.1]
    cands = [c for c in cands if 0.2 <= c <= L - 0.2 and not any(a - margin_m / 1000 <= c <= b + margin_m / 1000 for a, b in runs)]
    return min(cands, key=lambda c: abs(c - km)) if cands else km


def _timing(cum, spans, cz_level, v_avg):
    """(zones, time_at, km_at) for a driven polyline: time_at(km) = seconds of driving to reach km (zones at their own speed,
    else v_avg; halts not included), km_at(t) its inverse."""
    zones = []
    if cz_level and spans:
        z0 = max(spans[0][0] - CONGESTION_LEN_KM, 0.3)
        zones.append(Congestion(z0, min(spans[0][0] + CRAWL_PAST_KM, cum[-1] - 0.3), BAND_SPEED[cz_level]))

    def time_at(km):
        t, pos = 0.0, 0.0
        for z in sorted(zones, key=lambda z: z.from_km):
            lo, hi = max(pos, z.from_km), min(km, z.to_km)
            if hi > lo:
                t += (lo - pos) / v_avg * 3600 + (hi - lo) / z.speed_kmh * 3600
                pos = hi
        t += max(km - pos, 0) / v_avg * 3600
        return t

    def km_at(t):
        lo, hi = 0.0, cum[-1]
        for _ in range(48):
            mid = (lo + hi) / 2
            if time_at(mid) < t:
                lo = mid
            else:
                hi = mid
        return lo

    return zones, time_at, km_at


def _try_trace(rp, route, opt, loops, pickup_at, spec, stops_spec, cz_level, pauses_km=()):
    """Compose the driven polyline, solve the timeline, build the trace, measure. `pauses_km`: along-track km of the driven
    polyline where the car halts PAUSE_S seconds (a junction where the driver types a message). Raises ValueError on mismatch.
    Returns a dict: poly, spans, legs, gps, found, total_s, stops, pause_start_s (per pause, seconds after pickup), time_at, km_at."""
    poly, spans, legs = compose(rp, opt, [{k: v for k, v in lp.items() if k in ("leave", "via", "rejoin")} for lp in loops])
    cum = along_km(poly)
    L = cum[-1]
    zones, time_at, km_at = _timing(cum, spans, cz_level, avg_speed(route))

    events = []                            # (vertex, duration, tag)
    for k, dur in stops_spec:              # stop at loop k's via point
        events.append((nearest_idx(poly, loops[k]["via"][0]), dur, ("stop", k)))
    taken = {e[0] for e in events}
    for j, km in enumerate(pauses_km):
        vi = vertex_at(poly, cum, min(max(km, 0.05), L - 0.05))
        while vi in taken or vi in (0, len(poly) - 1) or any(abs(cum[vi] - cum[u]) < 0.002 for u in taken):
            vi += 1
        taken.add(vi)
        events.append((vi, PAUSE_S, ("pause", j)))
    stops, extra, pause_start = [], 0, {}
    for vi, dur, tag in sorted(events, key=lambda e: cum[e[0]]):
        st = r5(time_at(cum[vi])) + extra
        stops.append(Stop(*poly[vi], start_s=st, duration_s=dur))
        if tag[0] == "pause":
            pause_start[tag[1]] = st
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
    return {"poly": poly, "spans": spans, "legs": legs2, "gps": trip_gps, "found": found, "total_s": total_s, "stops": stops,
            "pause_start_s": [pause_start[j] for j in range(len(pauses_km))], "time_at": time_at, "km_at": km_at}


def build_route(spec, rates, rp, idx, rng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    opt = [tuple(p) for p in route["polyline"]]
    cum = along_km(opt)
    pickup_at = spec["day"]
    approach_start, approach_s = approach_leg(rp, P, D, rng)
    accepted = pickup_at - timedelta(seconds=approach_s + 10)
    stop_dur = {"named": 240, "unnamed": 250, "driver_errand": 240}.get(spec["stop"], 0)
    stops_spec = [(0, stop_dur)] if spec["stop"] != "none" else []
    cz = spec["band"]
    consent = spec["consent"]
    # pickup chatter happens only when nothing else is scripted; decided now because the driver's line needs a halt in the approach
    innocuous = consent == "none" and spec["stop"] == "none" and not spec["threat"] and rng.random() < 0.5
    car, outfit = rng.choice(CARS), rng.choice(OUTFITS)

    # ---- find loops one at a time (each attempt costs at most two cached OneMap legs) ----
    # a frac loop must replace >= MIN_REPLACED_KM of the optimal route when its story goes round a stretch (else >= MIN_REPLACED_PLAIN_KM:
    # an out-and-back spur bypasses nothing) and drive at most MAX_DETOUR_RATIO times the stretch it replaces; among the
    # candidates that qualify the smallest extra km wins.
    # A loop through a named place is the rider's own request: the first candidate that measures cleanly is kept.
    loops = []
    for k, lp in enumerate(spec["loops"]):
        cands = SPAN_CANDIDATES if "place" in lp else [(sh, side, d) for sh in FRAC_SHIFTS for side, d in OFFSET_CANDIDATES]
        best = None
        for cand in cands:
            loop = _loop_from_spec(opt, cum, lp, cand)
            if loop is None or (loops and loop["i1"] <= loops[-1]["i2"]):
                continue
            try:
                trial = _try_trace(rp, route, opt, loops + [loop], pickup_at, spec, [s for s in stops_spec if s[0] <= k], cz)
            except (ValueError, RuntimeError, AssertionError, urllib.error.HTTPError) as e:
                if "leg not in cache" in str(e):
                    OFFLINE_SKIPS[spec["name"]] = OFFLINE_SKIPS.get(spec["name"], 0) + 1   # reported by main(): an online run may choose this candidate
                continue        # no clean segment, or OneMap found no route (via point in the sea / a reserve)
            seg = trial["found"][k]
            if "place" in lp:
                best = (seg["extra_km"], loop)
                break
            need = MIN_REPLACED_KM if (k == 0 and loop_must_bypass(spec)) else MIN_REPLACED_PLAIN_KM
            if seg["route_km"] < need or seg["driven_km"] > MAX_DETOUR_RATIO * seg["route_km"] or seg["extra_km"] < MIN_EXTRA_KM:
                continue
            t_entry = secs(pickup_at, datetime.fromisoformat(seg["start"]))
            if k == 0 and cz and not crawl_reaches_segment(trial["gps"], seg["start"], cz):
                continue        # the crawl must still be on when the measured segment starts (what the contract reads)
            if k == 0 and (consent != "none" or spec["stop"] != "none") and t_entry < 80:
                continue        # the chat about this loop needs room before it
            if best is None or seg["extra_km"] < best[0]:
                best = (seg["extra_km"], loop)
        if best is None:
            raise RuntimeError(f"{spec['name']}: no candidate produced loop {k}")
        loops.append(best[1])

    # ---- first pass: where the loops start in time; then the halts at which the driver types, and the final trace ----
    pauses_km, chat_plan = [], {}
    if spec["loops"]:
        first = _try_trace(rp, route, opt, loops, pickup_at, spec, stops_spec, cz)
        t_entry = secs(pickup_at, datetime.fromisoformat(first["found"][0]["start"]))
        km_at, spans = first["km_at"], first["spans"]

        def halt(t_s, tag):
            pauses_km.append(km_at(max(t_s, 10)))
            chat_plan[tag] = len(pauses_km) - 1

        if consent == "after":
            halt(t_entry + 120, "ask")
        elif consent == "scope_other":
            halt(t_entry - 240, "ask")
        elif consent != "none":
            halt(t_entry - 200, "ask")
        if spec["stop"] in ("named", "unnamed"):
            halt(t_entry - 210, "stop_ok")
        if spec["threat"] == "driver":
            pauses_km.append((spans[0][0] + spans[0][1]) / 2)     # inside the loop, on its surface roads
            chat_plan["threat"] = len(pauses_km) - 1
        tr = _try_trace(rp, route, opt, loops, pickup_at, spec, stops_spec, cz, pauses_km)
        poly, spans, legs, trip_gps, found, total_s, stops = tr["poly"], tr["spans"], tr["legs"], tr["gps"], tr["found"], tr["total_s"], tr["stops"]
        halts = [pickup_at + timedelta(seconds=s) for s in tr["pause_start_s"]]
    else:
        # no loop: the trip follows the route; in heavy rain the traffic is slow (the fare runs over the estimate on time)
        total_s = r5(max(cum[-1] / avg_speed(route) * 3600, route["total_min"] * 60 * 1.35 if spec["weather"] == "heavy" else 0))
        trip_gps = build_trajectory(opt, pickup_at, total_s, seed=spec["seed"])
        poly, spans, legs, stops, found, halts = opt, [], [], [], [], []
    dropoff_at = pickup_at + timedelta(seconds=total_s)
    seg_start = [datetime.fromisoformat(f["start"]) for f in found]
    gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"],
                         pauses=[(APPROACH_PAUSE_S, 20)] if innocuous else ()) + trip_gps[1:]
    pressed = pickup_at - timedelta(seconds=10)
    service = spec["service"]
    trip = trip_block(f"T-{2000 + idx}", service, place(spec["pair"][0]), place(spec["pair"][1]), route,
                      accepted - timedelta(seconds=35), accepted, gps, pressed, pickup_at, dropoff_at)
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

    def heading(lo, hi, road):
        """DataMall direction label for an incident on `road` between optimal km lo..hi, from the way the route runs there."""
        a, b = opt[vertex_at(opt, cum, lo)], opt[vertex_at(opt, cum, hi)]
        axis, pos, neg = EXPRESSWAY_DIR.get(road, (None, None, None))
        if axis == "EW":
            return pos if b[1] >= a[1] else neg
        if axis == "NS":
            return pos if b[0] >= a[0] else neg
        after = [r["name"] for r in route["roads"] if r["from_m"] >= hi * 1000 and r["name"] != road]
        return f"towards {after[0].title()}" if after else "towards the city"

    def exit_name(lo, road):
        """The surface road the route came from before `road` (DataMall names the exit the incident sits after)."""
        before = [r["name"] for r in route["roads"] if r["to_m"] <= lo * 1000 + 1 and r["name"] != road and not is_expressway(r["name"])]
        return before[-1].title() if before else None

    if inc_kind in ("on_stretch", "seg1", "late"):
        lo, hi = stretches[0]
        pt = opt[vertex_at(opt, cum, (lo + hi) / 2)]
        # `late`: listed well after the driver had turned off (he could not have been reacting to a published incident)
        at = (seg_start[0] + timedelta(seconds=600)) if inc_kind == "late" else (pickup_at - timedelta(minutes=12))
        road = stretch_roads[0]
        where = f" after {exit_name(lo, road)} Exit" if exit_name(lo, road) and is_expressway(road) else ""
        incidents.append(incident("Accident", pt[0], pt[1], at,
                                  f"Accident on {road.title()} ({heading(lo, hi, road)}){where}. Avoid lane {rng.choice([1, 2])}."))
    elif inc_kind == "decoy_far":
        lo, hi = stretches[0]
        km = hi + 2.5 if cum[-1] - hi > 3.0 else lo - 2.5
        assert 0.5 < km < cum[-1] - 0.5, f"{spec['name']}: no room for a decoy incident"
        pt = opt[vertex_at(opt, cum, km)]
        road = dominant_road(route, km - 0.2, km + 0.2)
        incidents.append(incident("Vehicle breakdown", pt[0], pt[1], pickup_at - timedelta(minutes=8),
                                  f"Vehicle breakdown on {road.title()} ({heading(km - 0.2, km + 0.2, road)}). Avoid lane 1."))

    # ---- chat (every driver line during the trip is typed at a halt; the rider types from the back seat) ----
    chat_lines, stop_place = [], None
    detour_road, alt_road = {}, {}
    for k, lg in enumerate(legs):
        # the road the driver names must differ from the congested stretch, else "go round via X to avoid X" is self-contradictory
        others = [r for r in lg["roads"] if r["name"].title() != stretch_roads[0].title()] or lg["roads"]
        detour_road[k] = max(others, key=lambda r: r["to_m"] - r["from_m"])["name"].title().replace("'S ", "'s ")
        rest = [r for r in others if r["name"].title().replace("'S ", "'s ") != detour_road[k]]
        alt_road[k] = (max(rest, key=lambda r: r["to_m"] - r["from_m"])["name"].title().replace("'S ", "'s ") if rest else "the service road alongside")
    jam = stretch_roads[0].title() if stretch_roads else ""
    road = detour_road.get(0, "")
    if "ask" in chat_plan:
        t_ask = halts[chat_plan["ask"]] + timedelta(seconds=5)
        if consent in ("before", "after", "before_seg1", "named_elsewhere"):
            chat_lines += [(t_ask, "driver", rng.choice(ASK_LINES).format(jam=jam, alt=road)), (t_ask + timedelta(seconds=40), "rider", rng.choice(YES_LINES))]
        elif consent in ("general", "general_cn", "general_errand"):
            # a GENERAL route choice: the rider authorises any route that gets there, naming none
            yes = "随便你，哪条快走哪条，我赶时间。" if consent == "general_cn" else "Just take whichever way is faster lah, I'm late."
            chat_lines += [(t_ask, "driver", rng.choice(ASK_GENERAL_LINES).format(jam=jam)), (t_ask + timedelta(seconds=40), "rider", yes)]
        elif consent in ("named_singlish", "named_cn"):
            # agreement to a NAMED road, worded in Singlish / Chinese
            yes = {"named_singlish": "Can lah, go ahead.", "named_cn": f"可以，走 {road} 吧。"}[consent]
            chat_lines += [(t_ask, "driver", rng.choice(ASK_LINES).format(jam=jam, alt=road)), (t_ask + timedelta(seconds=40), "rider", yes)]
        elif consent == "negation":
            chat_lines += [(t_ask, "driver", rng.choice(ASK_LINES).format(jam=jam, alt=road)),
                           (t_ask + timedelta(seconds=40), "rider", f"No, I'm not okay with that. Please stay on {jam}.")]
        elif consent == "request_only":
            chat_lines += [(t_ask, "driver", rng.choice(ASK_LINES).format(jam=jam, alt=road))]
        elif consent == "scope_other":
            chat_lines += [(t_ask, "driver", "Mind if I pull in at the petrol station just ahead for one minute? Tank is almost empty."),
                           (t_ask + timedelta(seconds=35), "rider", "Sure, no problem.")]
    if "stop_ok" in chat_plan:
        t_ok = halts[chat_plan["stop_ok"]] + timedelta(seconds=5)
        if spec["stop"] == "named":
            stop_place = spec["loops"][0]["place"]
            ask = f"Can you stop at {stop_place}? I need to grab a parcel, 3-4 minutes."
        else:
            ask = "Can you stop at a 7-Eleven on the way? Just need 2 minutes."
        chat_lines += [(t_ok - timedelta(seconds=25), "rider", ask), (t_ok, "driver", rng.choice(["Ok", "Ok can", "Sure"]))]
    if "threat" in chat_plan:
        t = halts[chat_plan["threat"]]
        chat_lines += [(t - timedelta(seconds=40), "rider", "Why are we going this way? This is not the route on the app."),
                       (t + timedelta(seconds=5), "driver", "Shut up and let me drive.")]
    elif spec["threat"] == "trap":
        t = accepted + timedelta(seconds=60)
        line = f"I'll find you {PICKUP_SPOT.get(spec['pair'][0], 'at the main entrance')}, I am in a red jacket."
        chat_lines += [(t, "rider", line)]
    if innocuous:
        t = accepted + timedelta(seconds=50)
        n = max(1, round((approach_s + 10 - (APPROACH_PAUSE_S + 5)) / 60))
        chat_lines += [(t, "rider", rng.choice(PICKUP_LINES).format(spot=PICKUP_SPOT.get(spec["pair"][0], "at the main entrance"), outfit=outfit)),
                       (accepted + timedelta(seconds=APPROACH_PAUSE_S + 5), "driver", rng.choice(ARRIVING_LINES).format(n=n, car=car))]
    chat_lines.sort(key=lambda x: x[0])
    for t, _, _ in chat_lines:
        assert accepted <= t <= dropoff_at, f"{spec['name']}: chat at {t} outside the trip"
    for t, who, _ in chat_lines:            # a driver who is driving does not type: every driver line sits in a halt
        if who == "driver" and t > pickup_at:
            at = min(gps, key=lambda p: abs((datetime.fromisoformat(p["ts"]) - t).total_seconds()))
            assert at["speed_kmh"] < 5, f"{spec['name']}: driver line at {t:%H:%M:%S} while moving ({at['speed_kmh']} km/h)"

    # ---- fare, statements, profiles ----
    fare = metered_fare(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), rates) if service == "RydeTAXI" else fixed_fare(route, rates)
    extra_km = sum(f["extra_km"] for f in found)
    weather = WEATHER[spec["weather"]]
    rider_lines = {
        "none": rng.choice(RIDER_NONE_LINES).format(est=f"{route['total_km']:.0f}", got=f"{fare['distance_km']:.0f}"),
        "before": "The driver took a longer way round than the app showed and I paid more than the estimate. I want the difference back.",
        "after": "The driver only mentioned the different route after he had already turned off. I said sure because we were already on it, "
                 "not because I agreed beforehand. I was overcharged for the extra distance.",
        "request_only": "The driver asked about another road but I did not reply; he went anyway and the fare was higher than the estimate.",
        "scope_other": "I agreed to a quick petrol stop, not to a long loop. The meter was higher than the estimate and he never stopped for petrol anyway.",
        "before_seg1": "I agreed to go round the jam near the start, but later he went off the route a second time without asking. I want that part refunded.",
        "general": "I told him any faster way was fine, but the meter ended up well above the estimate. I don't think it was faster at all.",
        "general_cn": "我说过哪条快走哪条，结果车费比预估高了一截，我不觉得那条路更快。",
        "general_errand": "I said take any faster way, not stop somewhere for four minutes. The meter was way above the estimate.",
        "named_singlish": "I said can when he asked about the other road, but the fare was much higher than the app showed. Was that even the road he said?",
        "named_cn": "他问能不能换路我说可以，但车费比预估贵了很多，我不确定他走的是不是他说的那条路。",
        "named_elsewhere": "I agreed to the road he named, but he says himself he went a different way. The fare was much higher than the estimate.",
        "negation": "He asked about another road and I said no, stay on the main road. He went anyway and the fare was higher.",
    }
    statement = rider_lines.get(consent, rider_lines["none"])
    if service == "RydeX" and found:
        # a fixed quote has no meter and no "more than the estimate": the rider's grievance is the route itself
        fixed_lines = {
            "none": f"The app showed a {route['total_km']:.0f} km route but the driver went a different way and never asked me. I know the fare was a fixed quote; I still want the detour on record.",
            "before": "The driver took a longer way round than the app showed. The fare was a fixed quote, but I want the detour looked at.",
        }
        statement = fixed_lines.get(consent, fixed_lines["none"])
    if spec["stop"] == "named":
        statement = f"I asked to stop at {stop_place} and we did, fine, but the fare was much more than the estimate. I think the detour was overcharged."
    elif spec["stop"] == "unnamed":
        statement = "I asked for a quick 7-Eleven stop on the way, not a drive to one far off the route. The meter was way above the estimate."
    elif not found:
        statement = "The fare was higher than I expected for this trip in heavy rain, the driver must have taken a longer route."
    elif spec["threat"] == "driver":
        statement = "The driver went a different way and when I asked he told me to shut up. I was overcharged and felt unsafe."
    if inc_kind in ("on_stretch", "seg1") and consent == "none":
        statement = "The driver left the route the app showed and the meter was higher than the estimate. I never agreed to any change."
    driver_lines = {
        "none": rng.choice(GPS_LINES),
        "before": f"Traffic was building up ahead so I asked the rider before turning off via {road or 'the alternative road'} and the rider agreed.",
        "after": f"I told the rider I was going via {road or 'another road'} and the rider said sure.",
        "request_only": "I asked the rider about the alternative road; no objection, so I took it.",
        "scope_other": "The rider agreed to a short stop so I thought a small change of route was fine.",
        "before_seg1": "I asked about going round the jam and the rider agreed. The second turn-off was my GPS rerouting.",
        "general": "Traffic was building up ahead. I asked the rider and the rider said any faster way was fine, so I went round.",
        "general_cn": "Traffic was building up ahead. I asked the rider and the rider said any faster way was fine, so I went round.",
        "general_errand": "The rider said any route was fine. I went round the jam and stopped briefly to collect something on the way.",
        "named_singlish": f"I asked the rider before turning off via {road or 'the alternative road'} and the rider said can.",
        "named_cn": f"I asked the rider before turning off via {road or 'the alternative road'} and the rider agreed.",
        "named_elsewhere": f"I asked the rider about going via {road or 'the alternative road'} and the rider agreed. In the end I went by {alt_road.get(0, 'the service road alongside')} instead because it looked clearer; same direction.",
        "negation": "I asked the rider about the alternative road. The traffic was bad so I took it anyway; it was faster.",
    }
    dstmt = driver_lines.get(consent, driver_lines["none"])
    if inc_kind in ("on_stretch", "seg1"):
        dstmt = f"There was an accident on {jam} ahead, lanes were blocked, so I went round it. The extra distance was unavoidable."
    elif inc_kind == "late":
        dstmt = f"There was an accident on {jam}; I went round it. The extra distance was unavoidable."
    elif inc_kind == "decoy_far":
        dstmt = "There was a breakdown on the route, the whole road was slow, so I took another way. Check the LTA incident feed."
    elif spec["band"] and consent == "none":
        dstmt = f"{jam} was crawling" + (" and flooding in the heavy rain" if spec["weather"] == "heavy" else "") + ", so I went round it. Any driver would have done the same."
    if spec["stop"] == "named":
        dstmt = f"The rider asked me to stop at {stop_place}, so I drove there and waited while the rider went in."
    elif spec["stop"] == "unnamed":
        dstmt = "The rider asked for a 7-Eleven stop. I went to the one I know and waited."
    if not found:
        dstmt = "I followed the app route exactly. The meter is what it is; it was raining and traffic was slow."
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
    # what the scenario knows about the interpretive slots, per segment (in time order), under the frozen evidence rules:
    #   named stop (RD-3): the rider named the place and the stop fact sits inside the segment -> exempt
    #   consent to a NAMED road before the segment (RD-5): the agreement is real, but nothing in the record ties the driven
    #     segment to that road (the fact table carries no road names for the driven path) -> undetermined (G13);
    #     whether that sends the case to a person depends on whether the finding changes the outcome (derive_truth)
    #   after / request_only / scope_other / unnamed stop / none -> counts
    #   general route choice ("whichever way is faster"): the loop goes round the congested stretch -> exempt; with a
    #     driver's own stop inside it (general_errand) the segment is the driver's errand -> counts
    #   named road but the driver's own account puts the car on another road (named_elsewhere) -> counts
    #   "No, stay on the main road" (negation) -> counts
    finding_by_scenario, exempt_by_scenario = [], []
    for k in range(len(found)):
        if consent in ("before", "named_singlish", "named_cn") or (consent == "before_seg1" and k == 0):
            finding_by_scenario.append("undetermined"); exempt_by_scenario.append(None)
        elif spec["stop"] == "named" or consent in ("general", "general_cn"):
            finding_by_scenario.append("exempt"); exempt_by_scenario.append(True)
        else:
            finding_by_scenario.append("counts"); exempt_by_scenario.append(False)   # after / request_only / scope_other / unnamed / errand / elsewhere / negation / none
    if spec.get("gps_tail_cut_s"):
        cut = dropoff_at - timedelta(seconds=spec["gps_tail_cut_s"])
        gps = [p for p in gps if datetime.fromisoformat(p["ts"]) <= cut]
        case["gps"] = gps
        found = measure_detours(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), opt)   # the manifest shows the segments the fact tool will see
    meta = {"segments": found, "stretch_roads": stretch_roads, "detour_roads": detour_road, "exempt_by_scenario": exempt_by_scenario,
            "finding_by_scenario": finding_by_scenario, "extra_km": round(extra_km, 2), "stop_place": stop_place}
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
        if spec.get("gps_hole_s"):      # the trace stops for a while in the middle of the wait
            h0 = park_at + timedelta(seconds=90)
            h1 = h0 + timedelta(seconds=spec["gps_hole_s"])
            gps = [p for p in gps if not (h0 < datetime.fromisoformat(p["ts"]) < h1)]
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=30), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by=spec.get("recorded_by", "driver"))
        kind = spec.get("chat")
        plate = rng.choice(CARS)
        thr = (spec.get("policy") or {}).get("no_show_threshold_min", 3)     # the wait the driver claims follows the rule on the record
        here_line = rng.choice(HERE_LINES).format(car=plate)
        cancel_line = rng.choice(CANCEL_LINES).format(n=thr)
        if spec.get("recorded_by", "driver") is None:
            # who cancelled is not on record: neither the chat nor the statements may say it either, or the gap is no gap
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line)]
            statement = "I was on my way down when the booking disappeared from my app, and I was charged $6.61."
            dstmt = "I pressed I'm Here and waited at the pickup. The rider never boarded and the booking ended as cancelled."
        elif park_m > 200:
            chat_lines = [(park_at + timedelta(seconds=25), "driver", rng.choice(HERE_FAR_LINES).format(car=plate)),
                          (park_at + timedelta(seconds=80), "rider", rng.choice(WHERE_LINES)),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = "The driver marked arrived but was never at the pickup point. I waited there the whole time and then got charged $6.61 as a no-show."
            dstmt = f"I pressed I'm Here and waited more than {thr} minutes at the pickup. The rider never showed up, so I cancelled as a no-show."
        elif kind == "two_more":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line),
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
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = "The driver was not at the entrance where the pin was. He cancelled and I was charged $6.61."
            dstmt = "I was parked at the pickup, a short walk from the entrance, pressed I'm Here and waited more than 3 minutes."
        else:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            if wait_s >= 180:
                statement = rng.choice(CAME_OUT_LINES).format(fee="6.61")
                dstmt = (rng.choice(NOSHOW_DRIVER_LINES).format(n=thr) if thr == 3 else
                         f"I pressed I'm Here and waited the full {thr} minutes the rule gives. Rider no-show, so I cancelled.")
            else:
                statement = "The driver cancelled on me after barely two minutes and I was charged $6.61."
                dstmt = "I pressed I'm Here and waited for the rider, then cancelled as a no-show."
        end = cancelled
    else:  # rider cancelled
        cancel_s = spec["cancel_s"]
        cancelled = accepted + timedelta(seconds=cancel_s)
        if spec["driver"] == "en_route":
            drive_km = 30.0 / 3600 * cancel_s          # 30 km/h; the driver is still on the way when the rider cancels
            for _ in range(12):
                start = offset(P, (bearing(D, P) + rng.uniform(-30, 30)) % 360, 2600)
                approach = rp.route([start, P])
                full = [tuple(p) for p in approach["polyline"]]
                cum = along_km(full)
                cut = vertex_at(full, cum, drive_km)
                poly = full[:max(cut, 2) + 1]
                # the driver must be ON THE WAY: a one-way system can send the first kilometre away from the pickup, and a judge
                # reading the map would see a car driving off, not a driver who was "still far away"
                if haversine_m(poly[-1], P) < haversine_m(start, P) - 300 and min(haversine_m(q, P) for q in poly) > 200:
                    break
            else:
                raise RuntimeError(f"{spec['name']}: no approach route that brings the driver closer in {cancel_s} s")
            # the driver answers the rider's question at a halt (a junction about a minute into the drive), not while driving
            halt_s = 60 if cancel_s > 120 else None
            gps = build_trajectory(poly, accepted, cancel_s, stops=pause_stops(poly, cancel_s - 20, [(halt_s, 20)]) if halt_s else (), seed=spec["seed"])
            chat_lines = [(accepted + timedelta(seconds=40), "rider", rng.choice(HOW_LONG_LINES)),
                          (accepted + timedelta(seconds=halt_s + 5), "driver", rng.choice(ETA_LINES))] if halt_s else []
            statement = ("The driver was still far away after more than 3 minutes so I cancelled and booked another ride, and got charged $6.61."
                         if cancel_s > 180 else
                         rng.choice(["I cancelled within 3 minutes because the driver was nowhere near, and still got charged $6.61.",
                                     "The driver was nowhere near, so I cancelled less than 3 minutes after matching and still got charged $6.61."]))
            dstmt = rng.choice(ON_WAY_LINES)
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
            chat_lines = [(pressed, "driver", rng.choice(HERE_LINES).format(car=rng.choice(CARS))),
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
    if spec.get("policy"):          # the record states its own parameters (the organisers' sample format)
        case["policy_params"] = dict(spec["policy"])
        if spec["policy"].get("cancellation_fee"):
            case["fare"]["cancellation_fee"] = spec["policy"]["cancellation_fee"]
            case["dispute"]["statement"] = statement.replace("$6.61", f"${spec['policy']['cancellation_fee']:.2f}")
    return case, {}


# ----------------------------------------------------------------------------------------------- safety cases

def build_safety(spec, rates, rp, idx, rng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    opt = [tuple(p) for p in route["polyline"]]
    pickup_at = spec["day"]
    approach_start, approach_s = approach_leg(rp, P, D, rng)
    accepted = pickup_at - timedelta(seconds=approach_s + 10)
    drive_s = r5(along_km(opt)[-1] / avg_speed(route) * 3600)
    kind = spec["chat"]
    # the in-car exchange happens at a halt on a surface road (a junction), never at speed on an expressway: the driver's
    # line is typed during the halt, the rider's from the back seat just before / after it
    pauses = []
    if kind in ("driver_threat", "rider_threat"):
        L = along_km(opt)[-1]
        halt_km = surface_km(route, L * 0.5)
        pauses = [(r5(drive_s * halt_km / L), PAUSE_S)]
    total_s = drive_s + sum(d for _, d in pauses)
    dropoff_at = pickup_at + timedelta(seconds=total_s)
    trip_gps = build_trajectory(opt, pickup_at, total_s, stops=pause_stops(opt, drive_s, pauses), seed=spec["seed"])
    gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"],
                         pauses=[(APPROACH_PAUSE_S, 20)] if kind == "innocuous" else ()) + trip_gps[1:]
    service = spec["service"]
    trip = trip_block(f"T-{2000 + idx}", service, place(spec["pair"][0]), place(spec["pair"][1]), route,
                      accepted - timedelta(seconds=35), accepted, gps, pickup_at - timedelta(seconds=10), pickup_at, dropoff_at)
    halt = pickup_at + timedelta(seconds=pauses[0][0]) if pauses else None
    filed_by = "rider"
    if kind == "driver_threat":
        chat_lines = [(halt - timedelta(seconds=40), "rider", "Please stop the car, I want to get out here."),
                      (halt + timedelta(seconds=5), "driver", "Sit down or I lock the doors.")]
        statement = "The driver threatened to lock me in when I asked to get out. I felt unsafe for the whole ride."
        dstmt = "The rider tried to open the door at the lights. I told her to sit down for her own safety and drove on."
    elif kind == "rider_threat":
        chat_lines = [(halt + timedelta(seconds=5), "driver", "Please do not smoke in the car."),
                      (halt + timedelta(seconds=45), "rider", "Say that again and I will punch you.")]
        filed_by = "driver"
        statement = "The passenger threatened to punch me when I asked him not to smoke. I want this reported."
        dstmt = "I asked the passenger politely not to smoke in the car; he said he would punch me if I said it again. I kept driving and did not answer him."
    elif kind == "innocuous":
        n = max(1, round((approach_s + 10 - (APPROACH_PAUSE_S + 5)) / 60))
        chat_lines = [(accepted + timedelta(seconds=50), "rider", rng.choice(PICKUP_LINES).format(spot=PICKUP_SPOT.get(spec["pair"][0], "at the main entrance"), outfit=rng.choice(OUTFITS))),
                      (accepted + timedelta(seconds=APPROACH_PAUSE_S + 5), "driver", rng.choice(ARRIVING_LINES).format(n=n, car=rng.choice(CARS)))]
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
        threat_chat = spec.get("chat") in ("driver_threat", "rider_threat")
        cited = ["SAFE-1"] if threat_chat else ["SAFE-1", "SAFE-2"]
        why = ("Safety complaint whose chat holds a threat: SAFE-1 forbids an automatic ruling -> escalate with a fact summary for the reviewer."
               if threat_chat else "Complaint filed as a safety incident: SAFE-1/SAFE-2 forbid an automatic ruling -> escalate with a fact summary for the reviewer.")
        return {"ruling": "escalate", "amount": None, "cited_policy": cited, "escalate": True, "rationale": why,
                "flag_account": False, "_cert": lines}
    if spec.get("threat") == "driver" or spec.get("chat") == "threat":
        # the chat holds a line any reader takes as intimidation ("Shut up and let me drive", "you will regret it"):
        # the court's safety screen (SAFE-1) sends it to a person. Not a keyword rule: the reference is the scenario's intent.
        why = f"{case.dispute.type} dispute, but the chat holds an intimidating message; the judge's safety screen (SAFE-1) overrides every other clause: escalate."
        return {"ruling": "escalate", "amount": None, "cited_policy": ["SAFE-1"], "escalate": True, "rationale": why,
                "flag_account": False, "_cert": lines}
    if cert.insufficient:
        return {"ruling": "escalate", "amount": None, "cited_policy": ["NS-0", "NS-1"] if kind == "no_show" else ["RD-1"], "escalate": True,
                "rationale": "; ".join(lines) + f". Evidence insufficient (G12): {cert.insufficient} -> escalate, a person decides.",
                "flag_account": False, "evidence_gap": cert.insufficient, "_cert": lines}
    if kind == "no_show":
        ruling = cert.allowed[0]
        amount = cert.fee if ruling == "refund_full" else None
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
    kinds = meta.get("finding_by_scenario", ["exempt" if w else "counts" for w in scen])
    assert len(seg_ids) == len(scen), f"{spec['name']}: engine sees {len(seg_ids)} segments, scenario injected {len(scen)}"
    findings, notes, open_slots = {}, [], []
    for fid, want, kind in zip(seg_ids, scen, kinds):
        s = cert.segments[fid]
        if s["exempt"] is None:
            findings[fid] = want
            if kind == "undetermined":
                road = meta.get("detour_roads", {}).get(seg_ids.index(fid), "the named road")
                notes.append(f"{fid} interpretive slot: the rider agreed to '{road}' before the segment (RD-5), but no record ties this driven segment to that road "
                             f"(G13) -> undetermined" + (" and it changes the outcome -> a person decides" if s.get("changes_outcome", True) else
                                                        ", and it changes neither the amount nor the flag, only whether an RD-1 breach is recorded against the driver -> no_action either way"))
                if s.get("changes_outcome", True):
                    open_slots.append((fid, road))
            else:
                notes.append(f"{fid} interpretive slot ({s['why']}): scenario says {kind}")
        else:
            # mechanical slot: the engine decided (RD-4 incident exempts; no candidate -> not exempt). The scenario's
            # own label only covers interpretive consent/stop scope, so an RD-4 exemption may override a False label.
            if s["exempt"] != want and want is not None and not (s["exempt"] and spec["incident"] in ("on_stretch", "seg1")):
                raise AssertionError(f"{spec['name']}: engine says {fid} exempt={s['exempt']} but the scenario intended {want}")
            findings[fid] = s["exempt"]
            notes.append(f"{fid} mechanical: exempt={s['exempt']} ({s['why']})")
    metered = case.trip.service_type == "RydeTAXI"
    cited = ["RD-1", "RD-2"] if seg_ids else ["RD-1"]
    if any(p.clause == "RD-4" and p.status == "pass" for p in cert.predicates):
        cited.append("RD-4")
    if spec["consent"] != "none" and any(p.clause == "RD-5" and p.status == "judge" for p in cert.predicates):
        cited.append("RD-5")    # the chat holds a route exchange the judge had to read
    if spec["stop"] != "none" and any(p.clause == "RD-3" and p.status == "judge" for p in cert.predicates):
        cited.append("RD-3")
    if open_slots:
        gap = "; ".join(f"no record ties segment {fid} to {road}, the road the rider agreed to" for fid, road in open_slots)
        return {"ruling": "escalate", "amount": None, "cited_policy": cited, "escalate": True,
                "rationale": "; ".join([f"{len(seg_ids)} off-route segment(s) measured"] + notes) + f". Evidence gap (G13): {gap}. -> escalate, a person decides.",
                "flag_account": False, "evidence_gap": gap, "_cert": lines}
    non_exempt = [fid for fid in seg_ids if findings[fid] is False]
    amount = expected_amount(cert, {f: (True if v is None else v) for f, v in findings.items()}) if metered else None   # an open slot that changes nothing is fixed-fare: no amount anyway
    if amount is not None and amount <= 0:
        amount = None
    ruling = "refund_partial" if (metered and amount) else "no_action"
    prior = case.profiles.driver.route_disputes_upheld_90d >= 1
    flag = bool(prior and non_exempt)
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


# ----------------------------------------------------------------------------------------------- blind set
# Written after the prompts of 2026-10-10 were frozen and never used to tune them. Generated into data/bench/blind/
# with its own seed and the X- prefix; the reference answers come from the same frozen rules (derive_truth).
BLIND_SEED = 20261010
BLIND_SCENARIOS = [
    R("bl_general_consent", ("Bugis Junction", "Changi Airport T3"), loops=[{"frac": (0.40, 0.58)}], consent="general", band=2,
      hard="'whichever way is faster lah': a general route choice covers the loop round the jam -> exempt, no refund"),
    R("bl_general_consent_cn", ("Toa Payoh HDB Hub", "Changi City Point"), loops=[{"frac": (0.42, 0.60)}], consent="general_cn", band=2,
      hard="Chinese general route choice ('哪条快走哪条') -> exempt, no refund"),
    R("bl_general_errand", ("AMK Hub", "VivoCity"), loops=[{"frac": (0.38, 0.55)}], consent="general_errand", stop="driver_errand", band=2,
      hard="general route choice, but the driver stops 4 min inside the loop for his own errand -> the segment is the driver's errand, counts"),
    R("bl_negation", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.30, 0.50)}], consent="negation",
      hard="'No, I'm not okay with that, stay on X': a refusal, driver went anyway -> counts"),
    R("bl_named_singlish", ("Pasir Ris MRT", "Suntec City"), loops=[{"frac": (0.36, 0.54)}], consent="named_singlish", band=2,
      hard="'Can lah, go ahead' to a named road, nothing ties the driven segment to that road (G13) -> undetermined, a person decides"),
    R("bl_named_cn", ("Hougang Mall", "Changi Airport T3"), loops=[{"frac": (0.48, 0.66)}], consent="named_cn", band=2,
      hard="Chinese agreement to a named road ('可以，走 X 吧'), nothing ties the segment to it (G13) -> undetermined, a person decides"),
    R("bl_named_elsewhere", ("Compass One", "Kallang Wave Mall"), loops=[{"frac": (0.40, 0.58)}], consent="named_elsewhere", band=2,
      hard="agreed to road X; the driver's own account says he went by another road -> the agreement does not cover it, counts"),
    R("bl_gps_tail_missing", ("Sentosa Beach Station", "Clarke Quay"), loops=[{"frac": (0.55, 0.72)}], gps_tail_cut_s=240,
      hard="the trace ends 4 min before drop-off: the last stretch cannot be measured (G12) -> escalate"),
    N("bl_record_threshold_7m50", ("Junction 8", "Jurong Point"), by="driver", park_m=40, wait_s=490, here=True,
      policy={"free_wait_min": 5, "no_show_threshold_min": 8, "cancellation_fee": 5.0},
      hard="record states an 8-min no-show threshold; 7:50 does not reach it (free wait 5 min is not the threshold) -> refund_full $5.00"),
    N("bl_record_threshold_8m10", ("NEX Serangoon", "VivoCity"), by="driver", park_m=40, wait_s=510, here=True,
      policy={"free_wait_min": 5, "no_show_threshold_min": 8, "cancellation_fee": 5.0},
      hard="record states an 8-min no-show threshold; 8:10 reaches it -> no_action"),
    N("bl_hole_in_wait", ("Buona Vista MRT", "Suntec City"), by="driver", park_m=40, wait_s=300, here=True, gps_hole_s=200,
      hard="the trace has a 200 s hole during the wait: the time between two samples is not a measured wait (G12) -> escalate"),
    N("bl_cancelled_by_missing", ("Toa Payoh HDB Hub", "Pasir Ris MRT"), by="driver", park_m=40, wait_s=300, here=True, recorded_by=None,
      hard="cancelled_by is not on record: NS-1 and NS-4 cannot be told apart (G12) -> escalate"),
]


# ----------------------------------------------------------------------------------------------- main

# The reference answers follow the written policy AND the evidence rules frozen on this date. Bump when either changes
# and record every changed answer in data/bench/REFERENCE_CHANGES.md (what the gap is and why it moves the outcome).
REFERENCE_VERSION = "2026-10-10 v3: agreement to a named road needs a record tying the driven segment to it (G13); otherwise undetermined, and a person decides when it changes the outcome"

def validate_bench(case_dict: dict, spec: dict, rates, clauses) -> list[str]:
    validate.EXPECTED_DIR = EXPECTED_DIR
    if spec.get("gps_tail_cut_s"):
        return []        # the trace deliberately ends early; the format checks assume a complete trip
    errs = validate.check_case(case_dict, rates, clauses)
    if spec.get("policy"):
        errs = [e for e in errs if "policy_params" not in e and "cancellation fare" not in e]   # record-stated parameters (the organisers' format)
    if spec.get("gps_hole_s"):
        errs = [e for e in errs if "5 s grid" not in e]                                      # the hole IS the scenario
    if "recorded_by" in spec and spec["recorded_by"] is None:
        errs = [e for e in errs if "cancel fields" not in e]                                 # an unrecorded canceller IS the scenario
    if spec.get("stop") == "driver_errand":
        errs = [e for e in errs if "unexplained mid-trip stop" not in e]                     # the driver's own stop IS the scenario
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


def main(limit: int | None = None, blind: bool = False):
    global BENCH_DIR, CASES_DIR, EXPECTED_DIR
    seed, prefix, specs_all = (BLIND_SEED, "X-", BLIND_SCENARIOS) if blind else (SEED, "B-", SCENARIOS)
    if blind:
        BENCH_DIR = os.path.join(ROOT, "data", "bench", "blind")
        CASES_DIR, EXPECTED_DIR = os.path.join(BENCH_DIR, "cases"), os.path.join(BENCH_DIR, "expected")
    rng0 = random.Random(seed)
    rates = load_rates()
    clauses = validate.policy_clauses()
    rp = routes()
    for d in (CASES_DIR, EXPECTED_DIR):
        os.makedirs(d, exist_ok=True)
        for old in os.listdir(d):          # a renumbered scenario must not leave a stale case behind
            if old.startswith(prefix) and old.endswith(".json"):
                os.remove(os.path.join(d, old))
    # two cases a day; both sets end before 2026-10-10 (the day the reference rules were frozen and the sets were built)
    day0 = datetime(2026, 10, 3, 8, 0, 0, tzinfo=SGT) if blind else datetime(2026, 9, 1, 8, 0, 0, tzinfo=SGT)
    hours = [8, 9, 12, 14, 17, 18, 21, 22]
    manifest, failures = [], []
    specs = specs_all[:limit] if limit else specs_all
    for i, spec in enumerate(specs, 1):
        spec = dict(spec)
        spec["case_id"] = f"{prefix}{i:04d}"
        spec["seed"] = seed + i
        spec["day"] = (day0 + timedelta(days=i // 2)).replace(hour=hours[i % len(hours)], minute=(i * 7) % 60, second=0)
        rng = random.Random(seed * 7 + i)
        builder = {"route_deviation": build_route, "no_show": build_noshow, "safety": build_safety}[spec["kind"]]
        try:
            case, meta = builder(spec, rates, rp, i, rng)
            truth = derive_truth(case, spec, meta)
            expected = {k: v for k, v in truth.items() if not k.startswith("_")}
            # the gate: the record must tell the scenario's story and the label must promise the reference answer.
            # A case that fails is NOT written (no retry that changes the story); the run reports it and exits 1.
            broken = contract.check(case, contract.contract_for(spec, LOC)) + contract.check_label(spec["hard"], expected)
            if broken:
                raise contract.ContractError(f"{spec['case_id']} {spec['name']} refused: " + " | ".join(broken))
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
        json.dump({"seed": seed, "generated_by": "data/synth/scenarios.py" + (" --blind (held out: written after the 2026-10-10 prompt freeze, never used for tuning)" if blind else ""),
                   "reference_version": REFERENCE_VERSION, "cases": manifest}, f, indent=1, ensure_ascii=False)
    by_type = {}
    for m in manifest:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1
    print(f"\n{len(manifest)} cases written: {by_type}; {len(failures)} failure(s)")
    for cid, name, errs in failures:
        print(f"  {cid} {name}: {errs}")
    if OFFLINE_SKIPS:
        print("offline run: loop candidates skipped because their OneMap leg is not cached (a run with a token may choose one of them "
              "and produce different geometry): " + ", ".join(f"{k} x{v}" for k, v in sorted(OFFLINE_SKIPS.items())))
    return 1 if failures else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--blind"]
    sys.exit(main(int(args[0]) if args else None, blind="--blind" in sys.argv))
