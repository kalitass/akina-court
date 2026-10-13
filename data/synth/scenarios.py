#!/usr/bin/env python3
"""Parametric benchmark generator: composes the build_cases.py helpers over a list of scenarios and writes

    data/bench/cases/B-0001.json ...      case files (official-plus, core/case_format.py)
    data/bench/expected/B-0001.json ...   {ruling, amount, cited_policy, escalate, rationale, flag_account[, goodwill_credit, evidence_gap]}
    data/bench/manifest.json              per case: type, conditions, reference answer, what makes it hard, pinned loop plan

    set -a; . ./.env; set +a; unset ONEMAP_TOKEN      # the .env token expires every 72 h; email+password refreshes it
    .venv/bin/python data/synth/scenarios.py          # legs already in onemap_cache.json need no network

The reference answer is DERIVED, not typed: reference.py applies policy/policy.md (v3) to the generated record and the
scenario's interpretive labels without the engine. Unless SYNTH_SKIP_ENGINE_CHECK=1, the engine (core/) is run on the
same record and the case is refused when the two disagree. Deterministic for a warm OneMap cache.
"""
from __future__ import annotations

import hashlib
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
import lint  # noqa: E402
import reference  # noqa: E402
import validate  # noqa: E402
from build_cases import (LOC, PAUSE_S, ROADS, SGT, Congestion, Stop, along_km, annotate_roads, approach_trace, band_from_gps, build_trajectory,  # noqa: E402
                         compose, detour_trace, dump, incident, measure_detours, nearest_idx, offset, pause_stops, place, profiles,
                         project, routes, secs, trip_block)
from fare import (POLICY_CANCELLATION_FEE, cancellation_fare, distance_km, estimate_subtotal, fixed_fare, load_rates,  # noqa: E402
                  metered_fare, platform_fee, r2, slice_gps, surge_breakdown, surgeable_subtotal)
from route_provider import haversine_m  # noqa: E402

SEED = 20261008
BENCH_DIR = os.path.join(ROOT, "data", "bench")
CASES_DIR = os.path.join(BENCH_DIR, "cases")
EXPECTED_DIR = os.path.join(BENCH_DIR, "expected")
CANCEL_FEE = POLICY_CANCELLATION_FEE        # NS-1 / NS-4: the official $5.00
SKIP_ENGINE = os.environ.get("SYNTH_SKIP_ENGINE_CHECK") == "1"   # publish on the reference derivation alone (engine being rewritten)

LOC.update({  # real Singapore places, coordinates from common knowledge (~50-100 m)
    "Changi Airport T1": (1.36216, 103.98939),       # T1 arrival drive (T1 Boulevard / T1 Link West)
    "Jurong East MRT": (1.33218, 103.74155),
    "Woodlands Civic Centre": (1.4360, 103.7865),
    "NUS": (1.2961, 103.77586),
    "Sentosa Beach Station": (1.25095, 103.81775),   # Beach Station (2026-10-13: the earlier pin sat ~1.4 km east of it)
    "Punggol Waterway Point": (1.40561, 103.90168),
    "Tampines Mall": (1.3525, 103.9447),
    "Raffles Place": (1.2840, 103.8513),
    # named stop places (real malls) a rider can ask for by name
    "Parkway Parade": (1.3012, 103.9052),
    "Paya Lebar Square": (1.3176, 103.8929),
    "Clementi Mall": (1.3149, 103.7645),
    "Northpoint City": (1.4295, 103.8355),
    "Great World City": (1.2936, 103.8319),
    "Changi City Point": (1.3345, 103.9623),
    "Tiong Bahru Market": (1.28506, 103.83265),
    "Bukit Timah Plaza": (1.33914, 103.77830),
    "Rifle Range Road 7-Eleven": (1.33862, 103.78070),   # a 7-Eleven ~290 m from Bukit Timah Plaza, off the route
    # more origins / destinations (OneMap search, 2026-10-10) so the same route does not carry a dozen cases
    "AMK Hub": (1.3688, 103.84792),
    "Toa Payoh HDB Hub": (1.33207, 103.8491),
    "NEX Serangoon": (1.35014, 103.87208),
    "VivoCity": (1.26559, 103.82218),
    "Suntec City": (1.2955, 103.8585),
    "Junction 8": (1.3505, 103.8487),
    "Jurong Point": (1.34012, 103.70729),
    "Pasir Ris MRT": (1.3730, 103.9492),
    "Hougang Mall": (1.37301, 103.89344),
    "Buona Vista MRT": (1.3063, 103.7903),
    "Kallang Wave Mall": (1.30434, 103.87213),
    "Compass One": (1.3921, 103.8950),
})
# where a rider waits at each pickup (the pickup line names it, instead of a "main entrance" that a kerb or a campus has not)
PICKUP_SPOT = {
    "Orchard Road": "at the kerb outside Mandarin Gallery", "NUS": "outside University Hall", "Raffles Place": "at the Raffles Place taxi stand",
    "Clarke Quay": "at the Clarke Quay taxi stand", "Bugis Junction": "at the Victoria Street entrance", "Marina Bay Sands": "at the Tower 1 taxi stand",
    "Tanjong Pagar Centre": "at the taxi stand", "Sentosa Beach Station": "outside Beach Station", "Jurong East MRT": "at the taxi stand outside the MRT",
    "Woodlands Civic Centre": "at the main entrance", "Punggol Waterway Point": "at the taxi stand", "Tampines Mall": "at the taxi stand",
    "Bedok Mall": "at the taxi stand", "Changi Airport T1": "at the T1 arrival pickup, door 3", "AMK Hub": "at the taxi stand", "Toa Payoh HDB Hub": "at the taxi stand",
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
CRAWL_PAST_KM = 0.15                     # the crawl runs this far past the turn-off (the slip road is in the same jam), so the
                                         # 150 s before the measured segment start are still at crawling speed
MAX_DETOUR_RATIO = 4.0                   # a loop may drive at most this many times the stretch it replaces (what the road network allows)
MIN_REPLACED_PLAIN_KM = 0.5              # a plain loop (no incident, no agreement on it) must still replace this much of the route: no out-and-back spur
OFFSET_CANDIDATES = [(1, 1000), (-1, 1000), (1, 1500), (-1, 1500), (1, 700), (-1, 700), (1, 2000), (-1, 2000)]
CORRIDOR_INSET = 0.25                    # a corridor candidate's two via points sit this fraction inside the stretch, on a parallel road
TARGET_REFUNDS = (3.0, 5.0, 7.0)         # a case's refundable extra distance aims at one of these amounts (chosen by the scenario's identity)
RATIO_SOFT = 4.0                         # driven / replaced above this costs score (expressway interchanges can force it), above RATIO_HARD it is refused
RATIO_HARD = 6.0
RETRACE_MAX = 0.5                        # a loop may re-drive at most this share (by length) of the stretch it claims to leave
TOP_FIRST = 6                            # two-loop cases: the best TOP_FIRST loop-1 plans are each tried with every loop-2 candidate
GOOD_ENOUGH = 0.25                       # km from the target extra distance at which the candidate search stops early
SPAN_CANDIDATES = [(1.0, 1.0), (1.5, 1.5), (0.7, 0.7), (2.0, 2.0), (1.0, 2.0), (2.0, 1.0)]
APPROACH_PAUSE_S = 75                    # the driver's pickup message is typed at a halt this many seconds into the approach
TYPED_AT_S = 15                          # a driver line is stamped this far into a PAUSE_S halt: the car has been still for 15 s and stays so 10 s more

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


def register_road(name: str, pt) -> None:
    """Add a road seen on a OneMap route to the ROADS table (category by name, synthetic link id) so band()
    / validate.py accept it. The link id is a hash of the road name: the same road gets the same id in every case,
    whatever was built before it."""
    if name not in ROADS:
        ROADS[name] = (round(pt[0], 4), round(pt[1], 4), road_cat(name), "SYN-" + hashlib.sha256(name.encode()).hexdigest()[:6].upper())


IDENTITY_VERSION = "v1"      # how a scenario's random streams are derived from its name; bump only with a full regeneration


def identity(namespace: str, name: str) -> dict:
    """The random streams of one scenario, from its name alone: `geo` places the car (approach start, parking spot),
    `text` picks wording, cars, outfits and profiles, `noise` seeds the GPS jitter. A new scenario, a new paraphrase or
    a reordered list never moves another case's car."""
    h = hashlib.sha256(f"{namespace}/{name}/{IDENTITY_VERSION}".encode()).hexdigest()
    return {"geo": random.Random(int(h[:12], 16)), "text": random.Random(int(h[12:24], 16)), "noise": int(h[24:32], 16)}


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


def approach_leg(rp, P, D, rng, max_km=4.5, night=False):
    """A start point ~1.2 km behind the pickup (opposite side from the destination) whose OneMap route to the pickup
    is at most max_km; returns (start_point, approach_seconds at road-class speeds plus a 10 s pull-in, min 150 s)."""
    base = (bearing(P, D) + 180) % 360
    for _ in range(12):
        start = offset(P, (base + rng.uniform(-60, 60)) % 360, rng.choice([900, 1200, 1500]))
        try:
            r = rp.route([start, P])
        except (urllib.error.HTTPError, RuntimeError):     # OneMap found no route (online), or that refused leg is not cached (offline)
            continue
        if r["total_km"] <= max_km:
            return start, max(150, r5(drive_time_s(profile_of(r["polyline"], [r], night)) + 10))
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


# road-class cruising speeds (km/h): LTA band 7-8 on expressways, 5-6 on arterials, 3-4 on local roads; +10% at night
CLASS_KMH = {"expressway": 70.0, "highway": 55.0, "arterial": 46.0, "local": 32.0, "unnamed": 25.0}
NIGHT_FACTOR = 1.10
STILL_JITTER_M = 1.2         # GPS wander of a standing car (a few metres apart at most; under the 3 m stationary threshold)


def road_class(name: str | None) -> str:
    n = f" {(name or '').upper()} "
    if not name:
        return "unnamed"
    if "EXPRESSWAY" in n or "PARKWAY" in n:
        return "expressway"
    if " HIGHWAY " in n or " BOULEVARD " in n:
        return "highway"
    if any(f" {w} " in n for w in ("ROAD", "AVENUE", "DRIVE", "WAY", "BRIDGE")):
        return "arterial"
    return "local"


def is_night(t: datetime) -> bool:
    return t.hour >= 22 or t.hour < 6


def profile_of(poly, legs, night: bool = False) -> list[tuple[float, float, float]]:
    """[(from_m, to_m, kmh)] along `poly`: the cruising speed of the road each piece lies on (the OneMap `roads` of the
    legs it was composed from), by road class."""
    pts = [tuple(p) for p in poly]
    mids = [{"lat": (a[0] + b[0]) / 2, "lon": (a[1] + b[1]) / 2} for a, b in zip(pts, pts[1:])]
    annotate_roads(mids, legs)
    out, d = [], 0.0
    for (a, b), m in zip(zip(pts, pts[1:]), mids):
        seg = haversine_m(a, b)
        kmh = CLASS_KMH[road_class(m.get("road"))] * (NIGHT_FACTOR if night else 1.0)
        if out and out[-1][2] == kmh:
            out[-1] = (out[-1][0], d + seg, kmh)
        else:
            out.append((d, d + seg, kmh))
        d += seg
    return out or [(0.0, 1.0, CLASS_KMH["local"])]


def drive_time_s(profile, zones=()) -> float:
    """Seconds to drive a profiled polyline end to end, congestion / speeding zones (km, own speed) included."""
    from trajectory import profile_time_s
    t = profile_time_s(profile, 0, profile[-1][1])
    for z in zones:
        t += (z.to_km - z.from_km) * 1000 / (z.speed_kmh / 3.6) - profile_time_s(profile, z.from_km * 1000, z.to_km * 1000)
    return t


def halt_at(poly, profile, km: float, dur: int = PAUSE_S) -> Stop:
    """A PAUSE_S halt at the polyline vertex nearest `km`, timed by the profile (the car reaches it when the profile says)."""
    from trajectory import profile_time_s
    pts = [tuple(p) for p in poly]
    cum = along_km(pts)
    vi = min(range(1, len(pts) - 1), key=lambda k: abs(cum[k] - km))
    return Stop(*pts[vi], start_s=r5(profile_time_s(profile, 0, cum[vi] * 1000)), duration_s=dur, jitter_m=STILL_JITTER_M)


def speeding_zones(route) -> list:
    """The dangerous-driving story on the record: 98 km/h on the longest expressway run, broken by two hard brakings."""
    runs = sorted(((r["from_m"] / 1000, r["to_m"] / 1000) for r in route["roads"] if road_class(r["name"]) == "expressway"), key=lambda x: x[0] - x[1])
    if not runs or runs[0][1] - runs[0][0] < 2.0:
        raise RuntimeError("no expressway run long enough for the speeding story")
    a, b = runs[0]
    L = b - a
    z = [Congestion(a + 0.15 * L, a + 0.40 * L, 98.0), Congestion(a + 0.40 * L, a + 0.40 * L + 0.12, 25.0),
         Congestion(a + 0.40 * L + 0.12, a + 0.65 * L, 98.0), Congestion(a + 0.65 * L, a + 0.65 * L + 0.12, 25.0),
         Congestion(a + 0.65 * L + 0.12, a + 0.85 * L, 96.0)]
    return z


def roads_between(gps, start: str, end: str) -> list[str]:
    """Road names on the samples from start to end, by number of samples (most driven first)."""
    n = {}
    for p in gps:
        if start <= p["ts"] <= end and p.get("road"):
            n[p["road"]] = n.get(p["road"], 0) + 1
    return sorted(n, key=lambda k: -n[k])


def km_words(km: float) -> str:
    """A distance as a rider quotes it: 'about 4.5' under 10 km, a whole number above."""
    return f"about {km:.1f}" if km < 10 else f"{km:.0f}"


def road_label(name: str) -> str:
    return name.title().replace("'S ", "'s ")


def accounts(case: dict, spec: dict) -> None:
    """The official profile's account records: fraud flags (TH-3) and the rider's no-shows in 30 days (NS-9)."""
    for side in ("rider", "driver"):
        acct = {}
        fr = (spec.get("fraud") or {}).get(side)
        if fr:
            acct.update({"fraud_flags": 1, "fraud_flag_details": fr})
        if side == "rider" and spec.get("no_shows_30d") is not None:
            acct["no_shows_30d"] = spec["no_shows_30d"]
        if acct:
            case["profiles"][f"{side}_account"] = acct


def untied_road(rp, opt, cum, lo_km, hi_km, driven: set[str]) -> str:
    """A real road near the replaced stretch that the trip never drove: the main road of a loop on the other side of the
    route (OneMap), so "go round via X" names a plausible alternative the car did not take."""
    mid = (lo_km + hi_km) / 2
    i1, i2 = vertex_at(opt, cum, lo_km), vertex_at(opt, cum, hi_km)
    for side, dist in ((-1, 1000), (1, 1000), (-1, 1500), (1, 1500), (-1, 700), (1, 700)):
        via = perp_point(opt, cum, mid, side, dist)
        try:
            leg = rp.route([opt[i1], via, opt[i2]])
        except (urllib.error.HTTPError, RuntimeError):
            continue
        cands = [r for r in leg["roads"] if r["name"] and r["name"] not in driven and not is_expressway(r["name"])]
        if cands:
            return road_label(max(cands, key=lambda r: r["to_m"] - r["from_m"])["name"])
    raise RuntimeError("no untaken road near the stretch")


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


def G(name, pair, m0, m1, **kw):
    """A fare (surge) dispute: quoted at multiplier m0, charged at the trip-start multiplier m1. `notice`: none | full |
    no_cancel | no_fare | after_pickup | sms | missing (the log does not say). `loops` + `stop` add a rider-named stop."""
    d = dict(kind="fare_dispute", name=name, pair=pair, service="RydeX", m0=m0, m1=m1, notice="none", loops=[], consent="none",
             stop="none", incident="none", band=0, prior=0, weather="fair", threat=None, hard="")
    d.update(kw)
    return d


# Ported cases: a case validated by hand against the live models, rebuilt here as its BASE scenario's record (same trip,
# same GPS, same fare, same date) with the validated texts laid over it, verbatim. The base scenario lines are kept in
# PORT_BASES when the base is no longer in SCENARIOS. `labels` are the readings the reference uses for the new texts.
PORT_TEXT = {'R-0014': {'dispute': {'type': 'route_deviation',
                        'filed_by': 'rider',
                        'filed_at': '2026-09-08T22:45:45+08:00',
                        'statement': 'I told the driver I had an exam briefing and trusted him to take the fastest road. He left the expressway and went round '
                                     "through Bukit Merah, Kampong Bahru, Telok Blangah and Henderson Road: almost 4 km extra, when Ryde's own traffic record "
                                     "shows the AYE was moving at 60-69 km/h the whole time and there was no incident. The trip took longer than the app's "
                                     'estimate and I arrived stressed. I trusted him with the route and he used that trust to run up the meter by $5.89. '
                                     'Please refund the extra distance.'},
            'chat': [{'ts': '2026-09-08T21:38:30+08:00',
                      'from': 'rider',
                      'text': "Hi uncle, I have an exam briefing at NUS at 10. Whatever road you think is fastest, I trust you, don't need to follow the app."},
                     {'ts': '2026-09-08T21:38:50+08:00', 'from': 'driver', 'text': 'Ok no problem'}],
            'driver_statement': 'The rider told me to take whatever road I thought was fastest and not to follow the app. I thought Telok Blangah Road would '
                                'be faster at that hour.',
            'trip_id': 'T-R0014'},
 'R-0016': {'dispute': {'type': 'route_deviation',
                        'filed_by': 'rider',
                        'filed_at': '2026-09-08T22:45:45+08:00',
                        'statement': "I am 72 and I don't know the roads, so I told the driver he could decide the way. He left the expressway and drove me "
                                     "round Bukit Merah, Kampong Bahru, Telok Blangah and Henderson Road: almost 4 km more than the app's route, although "
                                     "Ryde's own traffic record shows the AYE was moving at 60-69 km/h and there was no incident. The trip took longer than "
                                     'the estimate and I paid $5.89 extra. An old woman who trusts her driver should not be charged for his detour. Please '
                                     'refund the extra distance.'},
            'chat': [{'ts': '2026-09-08T21:38:20+08:00',
                      'from': 'rider',
                      'text': "Uncle, I'm 72 and I don't know the roads at all. Any way also can, you decide, just bring me to NUS to see my grandson."},
                     {'ts': '2026-09-08T21:38:40+08:00', 'from': 'driver', 'text': 'Ok auntie, no problem'}],
            'driver_statement': 'The auntie said any way can, I decide. I went by Telok Blangah Road and Henderson Road to NUS.',
            'trip_id': 'T-R0016'},
 'M-0008': {'dispute': {'type': 'fare_dispute',
                        'filed_by': 'rider',
                        'filed_at': '2026-09-15T17:39:40+08:00',
                        'statement': 'The app quoted $16.26, but I was charged $21.14. I want the $4.88 difference refunded.'},
            'chat': [{'ts': '2026-09-15T17:14:10+08:00', 'from': 'rider', 'text': 'Hello, waiting at the taxi stand, in a red cap.'},
                     {'ts': '2026-09-15T17:14:50+08:00', 'from': 'driver', 'text': 'Arriving in about 1 min, grey Kia Niro.'}],
            'driver_statement': 'The app told her the new multiplier, the new fare and that she could cancel for free. She chose to ride.',
            'notification_text': 'Fares are 1.4× higher right now. Your new estimated fare is $22.48. Free cancellation until 17:13.'},
 'M-0011': {'dispute': {'type': 'fare_dispute',
                        'filed_by': 'rider',
                        'filed_at': '2026-09-11T18:24:00+08:00',
                        'statement': 'The app quoted $12.71 when I booked, but I was charged $16.17. I want the $3.46 difference refunded.'},
            'chat': [{'ts': '2026-09-11T17:18:10+08:00', 'from': 'rider', 'text': 'Hello, waiting at the kerb outside Mandarin Gallery, in a red cap.'},
                     {'ts': '2026-09-11T17:18:50+08:00', 'from': 'driver', 'text': '1 min away, white Honda Vezel.'}],
            'driver_statement': 'The app sent her the surge notice with the multiplier, the fare and free cancellation before I arrived. She chose to ride.',
            'notification_text': 'Fares are 1.4× higher right now. Your fare stays at the quoted $12.71. You can cancel for free.',
            'profiles': {'rider': {'account_age_days': 1055,
                                   'rating': 4.6,
                                   'disputes_90d': 1,
                                   'disputes_upheld_90d': 0,
                                   'route_disputes_upheld_90d': 0,
                                   'no_show_disputes_upheld_90d': 0},
                         'driver': {'account_age_days': 656,
                                    'rating': 4.57,
                                    'disputes_90d': 2,
                                    'disputes_upheld_90d': 2,
                                    'route_disputes_upheld_90d': 0,
                                    'no_show_disputes_upheld_90d': 0,
                                    'trips_90d': 458}}}}

PORT_BASES = [
    G("sg_rider_denies_notice", ("AMK Hub", "Toa Payoh HDB Hub"), 1.0, 1.4, notice="full", complaint="denies_notice", reused_from="new",
      expect={"ruling": "no_action", "flag": False}, hard="(base of a ported case) the full in-app notice before pickup; the rider denies it -> no refund"),
]


def P(name, base, base_i, text, labels, **kw):
    """A ported case: scenario `base` (built at its own position `base_i`, so its trip and date are the base's) with the
    validated texts PORT_TEXT[text] laid over it and `labels` for the reference's readings."""
    d = dict(kind="port", name=name, port={"base": base, "base_i": base_i, "text": text}, labels=labels, hard="", escalate_ok=True)
    d.update(kw)
    return d


# loops: list of {"frac": (a, b)} (a loop round the stretch a..b of the optimal route) or {"place": name} (through a named place)
# consent: none | before (driver asks to go via a road, rider agrees before the segment; the road is one the segment drives)
#        | after (same, after it started) | request_only (no reply) | scope_other (agreed to a petrol stop, not the loop)
#        | named_elsewhere (rider agrees to a road the car then does not drive) | general (a general "whichever way") ...
# stop: none | named (rider names the place, driver stops there) | unnamed (rider asks for "a 7-Eleven", driver picks a far one)
# incident: none | on_stretch (on the replaced stretch, reported before) | late (on it, reported after the detour began) | ...
# band: 0 | 1 | 2 (LTA band on the replaced stretch, backed by an 8 / 15 km/h crawl before the detour)
# no-show: by driver | rider | driver_other; contact both | message_only | call_only | none; driver en_route | at_pickup | late
# every scenario: `reused_from` names the case of the previous set it was built from ("new" otherwise); `ns` = "blind" keeps a
# ported case's random streams from the earlier set; `fraud` = {"rider": details} puts a fraud flag on that party (TH-3)
SCENARIOS = [
    # ---- route deviation (18) --------------------------------------------------------------------------------
    P("rd_port_trust_fastest", "rd_impatient_rider", 14, "R-0014", {"consent": "general_rider", "threat": None}, reused_from="cand R-0014",
      expect={"ruling": "no_action", "flag": False}, hard="the rider, before the detour: 'Whatever road you think is fastest, I trust you, don't need to follow the app.'; no traffic reason, and the complaint says the driver abused that trust: a general route choice covers a way round to the destination (RD-5), and what is left is within the 1 km tolerance -> no refund"),
    R("rd_notice_ack_hmm", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.35, 0.60)}], consent="notice_ack", band=2, geometry_from="rd_consent_after",
      ask="Jam ahead on {jam}, I'm going via {road}.", yes="hmm ok lor", reused_from="B-0003",
      expect={"ruling": "no_action", "flag": False}, hard="the driver told the rider (a statement, not a question) he was going via a named road because of the jam, the rider answered 'hmm ok lor' before the turn-off, and the GPS shows that road; the complaint says 'I just said hmm': an acknowledged notice is agreement (RD-5) -> no refund"),
    R("rd_named_cn_am", ("AMK Hub", "Marina Bay Sands"), loops=[{"frac": (0.48, 0.66)}], consent="named_cn", band=2, fraud={"rider": "flagged_for_repeated_refund_claims"},
      reused_from="B-0056",
      expect={"ruling": "escalate", "flag": False}, hard="traffic on the stretch; the driver asked to go via a named road and the rider agreed in Chinese before the turn-off, and the GPS road names show that road: informed and agreed (merits: no refund); the rider carries a fraud flag, so a lone reading (87%) is under 95% -> escalate unless both sides read the yes alike"),
    R("rd_stop_named_longer_way", ("Clarke Quay", "VivoCity"), loops=[{"place": "Tiong Bahru Market"}], stop="named", stop_text="Can you stop by {place} first? 5 min.",
      dstmt_extra="The way to the market was a bit longer because of one-way streets.", reused_from="new",
      expect={"ruling": "no_action", "flag": False}, hard="the rider named Tiong Bahru Market before the turn-off and the car stopped there; the driver himself says the way there was longer because of one-way streets, but RD-3 exempts the whole segment to a rider-named stop, and what is left is within the 1 km tolerance -> no refund"),
    R("rd_consent_except_road", ("Jurong Point", "Suntec City"), loops=[{"frac": (0.40, 0.58)}], consent="excluded_not_driven", band=2, geometry_from="rd_general_consent_jp",
      reused_from="B-0050",
      expect={"ruling": "no_action", "flag": False}, hard="'Jam ahead, shall I take another way?' answered '可以，不要走 Y' (ok, don't use Y): consent with an exclusion; the GPS road names show Y was not driven, so the consent covers the loop (RD-5); the complaint says the rider put conditions -> no refund"),
    R("rd_stop_named_prior", ("Jurong East MRT", "NUS"), loops=[{"place": "Clementi Mall"}], stop="named", prior=2, weather="light", reused_from="B-0011",
      expect={"ruling": "no_action", "flag": False}, hard="RD-3: the rider named Clementi Mall; with that loop exempt, what is left of the deviation is under the 1 km tolerance, and the driver's 2 priors trigger no RD-6 flag -> no refund, no flag"),
    P("rd_port_auntie_any_way", "rd_impatient_rider", 14, "R-0016", {"consent": "general_rider", "threat": None}, reused_from="cand R-0016",
      expect={"ruling": "no_action", "flag": False}, hard="the 72-year-old rider, before the detour: 'Any way also can, you decide, just bring me to NUS'; the complaint asks for sympathy: a general route choice covers the way round (RD-5), the rest is within tolerance -> no refund"),
    R("bl_named_elsewhere", ("Compass One", "Kallang Wave Mall"), loops=[{"frac": (0.40, 0.58)}], consent="named_elsewhere", band=2, ns="blind", reused_from="X-0007",
      expect={"ruling": "refund_partial", "flag": False}, hard="the rider agreed to go via a named road, but the GPS road names show the segment never used it (RD-5) -> the agreement does not cover it, refund"),
    R("rd_request_only", ("Clarke Quay", "Sentosa Beach Station"), loops=[{"frac": (0.30, 0.50)}], consent="request_only", band=2, prior=2, reused_from="B-0021",
      expect={"ruling": "refund_partial", "flag": True}, hard="the driver asked about another road and the rider never answered: no agreement (RD-5); the driver has 2 upheld route disputes in 90 days -> refund + flag_account (RD-6)"),
    R("rd_long_loop_mid_amount", ("Compass One", "VivoCity"), loops=[{"frac": (0.42, 0.60)}], band=2, geometry_from="rd_general_consent_cn_cp", allow_loopback=True, reused_from="B-0052",
      expect={"ruling": "refund_partial", "flag": False}, hard="a long loop round a crawling stretch, rider not informed: the refund is in the $10-50 band (TH-1) and code settles it -> refund, the system decides"),
    R("bl_gps_tail_missing", ("Sentosa Beach Station", "Clarke Quay"), loops=[{"frac": (0.55, 0.72)}], gps_tail_cut_s=240, tail_request=True, ns="blind", reused_from="X-0008",
      expect={"ruling": "escalate", "flag": False}, hard="the trace ends 4 min before drop-off, and just before that the rider asked for another road and drop-off point: whether the car went there (the rider's own route, RD-3) cannot be measured (TH-4) -> escalate"),
    R("rd_threat_in_chat", ("Marina Bay Sands", "Tampines Mall"), loops=[{"frac": (0.40, 0.55)}], threat="driver", reused_from="B-0024",
      expect={"ruling": "escalate", "flag": False}, hard="route dispute whose chat holds an intimidating driver message -> the safety screen (SAFE-1) overrides: escalate"),
    R("rd_general_consent_jp", ("Jurong Point", "Suntec City"), loops=[{"frac": (0.40, 0.58)}], consent="general", band=2, fraud={"rider": "flagged_for_repeated_refund_claims"},
      reused_from="B-0050",
      expect={"ruling": "escalate", "flag": False}, hard="'whichever way is faster' would exempt the loop, but that rests on reading the rider's words and the rider carries a fraud flag: 90% x 97% is under the 95% TH-3 needs -> escalate"),
    R("rd_impatient_rider", ("Orchard Road", "NUS"), loops=[{"frac": (0.35, 0.55)}], consent="negation", threat="impatient", geometry_from="rd_keyword_trap_find_you", reused_from="B-0049",
      expect={"ruling": "refund_partial", "flag": False}, hard="the driver asked to go round and the rider said no, stay on the main road; he went anyway, and the rider wrote 'Why you go this way?? I said stay. I'm late already': an objection (no agreement, RD-5) and frustration, not a safety matter -> refund"),
    R("rd_two_segs_consent_seg1", ("Woodlands Civic Centre", "Orchard Road"), loops=[{"frac": (0.25, 0.38)}, {"frac": (0.62, 0.75)}], consent="before_seg1",
      ask="Jam ahead, can go via {road}?", yes="ok", allow_loopback=True,
      complaint_text="The driver went off the app's route and the meter was well above the estimate. I want the whole extra distance refunded.",
      driver_text="She agreed to my route.", reused_from="B-0013",
      expect={"ruling": "refund_partial", "flag": False}, hard="two segments: before the first the driver asked 'can go via' a road and the rider said 'ok', and the GPS shows it driven (exempt; no traffic reason, so the rider's own route, RD-3); the second is a later loop with no message before it (counts); the rider wants all of it back, the driver says she agreed to his route -> refund the second segment's share only"),
    R("rd_call_log_no_recording", ("NUS", "Raffles Place"), loops=[{"frac": (0.40, 0.60)}], consent="unrecorded_call", band=2, geometry_from="rd_verbal_consent_no_recording",
      reused_from="B-0009",
      expect={"ruling": "refund_partial", "flag": False}, hard="the driver says 'I called her before the turn and she said ok', and the call log shows an answered 25 s call, but no recording and no transcript: a logged call is not the rider's agreement (RD-5: verbal notice needs the recording) -> refund"),
    R("rd_recorded_call_consent", ("Punggol Waterway Point", "Tampines Mall"), loops=[{"frac": (0.30, 0.50)}], consent="recorded_call", incident="on_stretch", band=1,
      geometry_from="rd_band1_incident", reused_from="B-0008",
      expect={"ruling": "no_action", "flag": False}, hard="an accident on the stretch, and the recorded call before pickup has the rider agreeing to go via the road the GPS shows -> informed and agreed (RD-5 with a recording), no refund"),
    R("bl_negation", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.20, 0.40)}], consent="qualified", band=2, ns="blind", reused_from="X-0004",
      expect={"ruling": "refund_partial", "flag": False}, hard="'Can lah, but not via Y' and the GPS shows the segment on Y: the agreement excluded the road the driver took -> counts, refund"),
    # ---- surge / fare (10) -----------------------------------------------------------------------------------
    G("sg_notice_estimate_above_charge", ("Bugis Junction", "Marina Bay Sands"), 1.0, 1.3, notice="full", complaint="misleading_estimate", reused_from="new",
      expect={"ruling": "no_action", "flag": False}, hard="the in-app notice before pickup states 1.3x, a new estimated fare and 'You can cancel for free'; the estimate is above what was charged and the rider calls it misleading, but SURGE-1 asks the notice to state a revised fare, not to predict it -> no refund"),
    G("sg_notified_full", ("Orchard Road", "Marina Bay Sands"), 1.0, 1.4, notice="full", fraud={"rider": "flagged_for_repeated_fare_disputes"}, reused_from="new",
      expect={"ruling": "escalate", "flag": False}, hard="surge rose and the rider got an in-app notice before pickup with the new multiplier, the revised fare and free cancellation, then rode (merits: no refund); the rider carries a fraud flag, so a lone reading of the notice (87%) is under 95% -> escalate unless both sides read it alike"),
    G("sg_notice_after_pickup", ("Toa Payoh HDB Hub", "Junction 8"), 1.2, 1.5, notice="after_pickup", fraud={"rider": "flagged_for_repeated_fare_disputes"}, reused_from="new",
      expect={"ruling": "refund_partial", "flag": False}, hard="a complete notice, but sent after pickup (SURGE-1 needs it before or at pickup); the rider carries a fraud flag, but the timing is settled by code (97% >= 95%, TH-3) -> refund the surge part"),
    G("sg_notice_no_cancel_option", ("Raffles Place", "Suntec City"), 1.0, 1.6, notice="no_cancel", fraud={"rider": "flagged_for_repeated_fare_disputes"}, reused_from="new",
      expect={"ruling": "escalate", "flag": False}, hard="the log says rider_notified, but the notice never offers free cancellation: no SURGE-1 notice (merits: refund the surge part); the rider carries a fraud flag, so a lone reading (87%) is under 95% -> escalate unless both sides read it alike"),
    P("sg_port_notice_fare_unchanged", "sg_notified_full", 20, "M-0011", {"notice": "fare_unchanged", "fraud": {}}, reused_from="cand M-0011",
      expect={"ruling": "refund_partial", "flag": False}, hard="the timely notice says 'Your fare stays at the quoted $12.71': it states no revised estimated fare, so SURGE-1 is not met although the multiplier and free cancellation are there -> refund the surge part (capped at actual - quote)"),
    G("sg_surge_unchanged_complaint_threat", ("Clarke Quay", "Orchard Road"), 1.3, 1.3, complaint_safety=True, reused_from="new",
      expect={"ruling": "escalate", "flag": False}, hard="filed as a fare dispute: the 1.3x surge was in the quote and unchanged (no refund on the fare), but the complaint says the driver told the rider he knows where she lives -> safety screen (SAFE-1): escalate"),
    G("sg_mixed_rider_stop", ("Kallang Wave Mall", "Bedok Mall"), 1.0, 1.4, loops=[{"place": "Paya Lebar Square"}], stop="named", stop_text="Can stop at {place} for 5 min?",
      driver_text="No refund is due: the rider added a stop at Paya Lebar Square herself.", reused_from="new",
      expect={"ruling": "refund_partial", "flag": False}, hard="no notice of a 1.4x surge, and the rider also asked for a stop that lengthened the trip; she wants the whole difference over the quote, he says nothing is due because of the stop -> refund only the surge part, (1.4 - 1.0) x surgeable subtotal (SURGE-3); the stop's share is hers (RD-3)"),
    G("sg_notice_just_before_pickup", ("Toa Payoh HDB Hub", "Suntec City"), 1.0, 1.4, notice="full_at_pickup", complaint="late_popup", reused_from="new",
      expect={"ruling": "no_action", "flag": False}, hard="a complete in-app notice timestamped 20 s before pickup; the rider says it only popped up as she got into the car, with no real chance to cancel; SURGE-1 asks for it before or at the point of pickup -> no refund"),
    G("sg_over_50", ("Jurong Point", "Changi Airport T1"), 1.0, 2.0, notice="cancel_fee", reused_from="new",
      expect={"ruling": "escalate", "flag": False}, hard="the notice names 2.0x and the new fare but says 'cancellation fees may apply' (the opposite of a free-cancel option): not a SURGE-1 notice, and the surge part is over $50 (TH-1) -> escalate, the system prepares the case file"),
    P("sg_port_notice_window_closed", "sg_rider_denies_notice", 28, "M-0008", {"notice": "window_closed", "complaint": None}, reused_from="cand M-0008",
      expect={"ruling": "refund_partial", "flag": False}, hard="the notice says 'Free cancellation until 17:13.' but reached the rider at 17:14:45, after that window had closed: no free-cancel option was open to her, so SURGE-1 is not met -> refund the surge part (capped at actual - quote)"),
    # ---- no-show (18) ----------------------------------------------------------------------------------------
    N("ns_wait_5m10", ("Clarke Quay", "Bedok Mall"), by="driver", park_m=40, within_s=310, here=True, claim="never_called", reused_from="B-0033",
      expect={"ruling": "no_action", "flag": False}, hard="5 min 10 s at the pickup after the arrival tap, two messages, and one unanswered call that is only in the call log; the rider says he never called -> every NS-1 condition holds, fee stands"),
    N("ns_wait_4m50", ("Tampines Mall", "Changi Airport T1"), by="driver", park_m=40, within_s=290, here=True, reused_from="B-0034",
      expect={"ruling": "refund_full", "flag": False}, hard="4 min 50 s at the pickup, then cancelled: short of the 5-minute free wait (NS-1 (ii)) -> refund"),
    N("ns_no_call", ("Raffles Place", "Changi Airport T1"), by="driver", park_m=40, wait_s=360, here=True, contact="message_only", no_shows_30d=2, reused_from="B-0028",
      expect={"ruling": "refund_full", "flag": False}, hard="waited 5+ min and messaged, but never called (NS-1 (iii) needs both); the rider's 2 earlier no-shows count for nothing when this one is not upheld -> refund, no flag"),
    N("ns_app_noshow_own_reason", ("Bedok Mall", "Raffles Place"), by="driver", park_m=40, wait_s=360, here=True, reason_reading="own_reason",
      cancel_text="Sorry ah, my kid's school called, I have to go now. Cancelling.", own_reason="my kid's school called and I had to go",
      reused_from="B-0027",
      expect={"ruling": "refund_full", "flag": False}, hard="the app reason says rider_no_show and every NS-1 element holds, but the driver's own cancel message says he left for a family matter: the reason is his, not a no-show (NS-0, NS-3) -> refund"),
    N("ns_no_contact", ("Woodlands Civic Centre", "Punggol Waterway Point"), by="driver", park_m=40, wait_s=390, here=True, contact="none", reused_from="B-0031",
      expect={"ruling": "refund_full", "flag": False}, hard="Precedent 7.3 pattern: a long wait at the pin but zero contact attempts -> refund the $5.00"),
    N("ns_fake_here_far", ("Bugis Junction", "Tanjong Pagar Centre"), by="driver", park_m=600, wait_s=210, here=True, reused_from="B-0026",
      expect={"ruling": "refund_full", "flag": True}, hard="NS-2: arrival tapped 600 m away, never within 200 m -> refund + flag_account"),
    N("bl_hole_in_wait", ("Buona Vista MRT", "Suntec City"), by="driver", park_m=40, wait_s=360, here=True, gps_hole_s=200, ns="blind", reused_from="X-0011",
      expect={"ruling": "escalate", "flag": False}, hard="6 min from the arrival tap to the cancel, a message and a call: the fee would stand if the car stayed, but a 200 s hole in the trace leaves that unproven (NS-1 (iv), TH-4) -> escalate"),
    N("bl_record_threshold_7m50", ("Junction 8", "Jurong Point"), by="driver", park_m=40, wait_s=470, here=True, ns="blind", reused_from="X-0009",
      policy={"free_wait_min": 5, "no_show_threshold_min": 8, "cancellation_fee": 5.0},
      expect={"ruling": "refund_full", "flag": False}, hard="the record states an 8-min no-show threshold; 7:50 passes the 5-min default but not the record's own -> refund"),
    N("ns_need_to_go_after_no_reply", ("Jurong East MRT", "NUS"), by="driver", park_m=40, wait_s=360, here=True, app_reason=None, reason_reading="no_show",
      cancel_text="No reply from you, I need to go already, cancelling.", reused_from="B-0029",
      expect={"ruling": "no_action", "flag": False}, hard="no reason picked in the app; after 6 min, two messages and a call the driver wrote 'No reply from you, I need to go already, cancelling': he leaves because the rider did not come (a no-show, NS-0), not for a reason of his own; NS-1 holds -> fee stands"),
    N("ns_rider_cancel_200s", ("NUS", "Raffles Place"), by="rider", cancel_s=200, driver="en_route", reused_from="B-0030",
      expect={"ruling": "no_action", "flag": False}, hard="NS-4: 200 s after matching -> fee stands; the driver being on the way is not a ground (no scheduled time, NS-8 cannot apply)"),
    N("ns_driver_cancel_flat_tyre", ("Hougang Mall", "NEX Serangoon"), by="driver", park_m=40, wait_s=350, here=True, app_reason=None, reason_reading="own_reason",
      cancel_text="Sorry, tyre puncture, car got problem, have to cancel.", own_reason="my tyre went flat", reused_from="new",
      expect={"ruling": "refund_full", "flag": False}, hard="no reason picked in the app; the driver arrived, waited 5+ min, messaged and called, then wrote 'tyre puncture, car got problem, have to cancel': his own reason, not a no-show (NS-0, NS-3) -> refund"),
    N("ns_safety_in_complaint", ("Toa Payoh HDB Hub", "VivoCity"), by="driver", park_m=40, wait_s=340, here=True, complaint_safety=True, reused_from="new",
      expect={"ruling": "escalate", "flag": False}, hard="filed as a no-show charge and the no-show facts favour the driver, but the complaint says he kept making comments about her body and asked where she lives -> safety screen (SAFE-1): escalate"),
    N("ns_driver_late_no_contact", ("Pasir Ris MRT", "Tampines Mall"), by="rider", driver="late", cancel_s=780, scheduled_after_accept_s=300, contact="none", reused_from="new",
      expect={"ruling": "refund_full", "flag": False, "goodwill_credit": 5.0}, hard="NS-8: late driver who never messaged or called -> refund + $5.00 goodwill credit"),
    N("ns_repeat_noshow_flag", ("Marina Bay Sands", "Tampines Mall"), by="driver", park_m=40, wait_s=360, here=True, no_shows_30d=2, reused_from="B-0042",
      expect={"ruling": "no_action", "flag": True}, hard="every NS-1 condition holds and the driver's 'waited more than 5 min, cancelling' is a no-show cancel; this is the rider's third no-show in 30 days -> fee stands + flag_account (NS-9)"),
    N("ns_early_arrival_scheduled", ("Suntec City", "Changi Airport T1"), by="driver", park_m=40, wait_from_scheduled_s=240, here=True, scheduled_after_tap_s=120, reused_from="new",
      expect={"ruling": "refund_full", "flag": False}, hard="the driver arrived about 2 min before the scheduled pickup and cancelled 4 min after it (6 min after arriving): the free wait runs from the scheduled time, 4 min is short of 5 -> refund"),
    N("ns_threat_in_chat", ("Bugis Junction", "Jurong East MRT"), by="driver", park_m=40, wait_s=330, here=True, chat="threat", reused_from="B-0041",
      expect={"ruling": "escalate", "flag": False}, hard="the no-show facts favour the driver, but his chat holds 'I will find you and you will regret it' -> safety screen (SAFE-1): escalate"),
    N("ns_impatient_driver", ("AMK Hub", "Junction 8"), by="driver", park_m=40, wait_s=340, here=True, chat="impatient", app_reason=None, reason_reading="no_show",
      cancel_text="Waited 5 min already, you never come, cancelling.", fraud={"rider": "flagged_for_frequent_late_cancellations"}, reused_from="new",
      expect={"ruling": "escalate", "flag": False}, hard="no reason picked in the app, but 'Waited 5 min already, you never come, cancelling' is a no-show cancel and NS-1 holds (merits: fee stands); 'Still waiting ah, so slow' is impatience, not a safety matter; the rider carries a fraud flag, so a lone reading (87%) is under 95% -> escalate unless both sides read it alike"),
    N("ns_gate_b_refused_to_move", ("Clarke Quay", "Sentosa Beach Station"), by="driver", park_m=150, wait_s=360, here=True, chat="gate", reused_from="B-0043",
      expect={"ruling": "no_action", "flag": False}, hard="the driver tapped at Gate B, 150 m from the pin, and told the rider he could not stop at Gate A (double yellow line); he called once, waited 6 min and cancelled; the rider says he refused to come to her: NS-1 holds within 200 m and he cancelled because she did not come (NS-0) -> fee stands"),
    # ---- safety (4) ------------------------------------------------------------------------------------------
    S("safe_driver_threat", ("Clarke Quay", "Bedok Mall"), chat="driver_threat", reused_from="B-0044",
      expect={"ruling": "escalate", "flag": False}, hard="SAFE-1: driver threatens to lock the rider in -> escalate"),
    S("safe_rider_threat", ("Tampines Mall", "Changi Airport T1"), chat="rider_threat", service="RydeTAXI", reused_from="B-0045",
      expect={"ruling": "escalate", "flag": False}, hard="SAFE-1: rider threatens the driver; the driver filed -> escalate, no refund"),
    S("safe_innocuous_chat_dangerous_driving", ("Jurong East MRT", "NUS"), chat="innocuous", speeding=True, reused_from="B-0046",
      expect={"ruling": "escalate", "flag": False}, hard="innocuous chat; the complaint alleges speeding and hard braking, and the trace shows ~98 km/h on the expressway with two sharp decelerations -> SAFE-2 escalate"),
    S("safe_no_chat_harassment", ("Woodlands Civic Centre", "Punggol Waterway Point"), chat="none", weather="heavy", reused_from="B-0047",
      expect={"ruling": "escalate", "flag": False}, hard="no chat at all; harassment alleged in the statement -> escalate (SAFE-1 via type)"),
]


# Candidates under trial (`--candidates` -> data/bench/candidates/, K- ids): pure readings of words that code cannot settle,
# where a lone judge may execute a wrong ruling and a careful reader gets it right. Not part of the 50; every expected
# answer carries escalate_ok (handing the case to a person also counts as right).
CANDIDATES = [
    R("cand_retracted", ("Clarke Quay", "Sentosa Beach Station"), loops=[{"frac": (0.30, 0.50)}], consent="retracted", band=2, geometry_from="rd_request_only",
      complaint_text="He asked about another road. I said ok, then told him no, please stay on the main road, before he turned. He went anyway and the meter was well above the estimate.",
      driver_text="The rider said ok to the other road, so I took it.",
      expect={"ruling": "refund_partial", "flag": False}, hard="'Jam ahead, can I go via X?' / 'ok', then 30 s later, still before the turn-off, 'actually no, please stay on ...'; the car went via X: the yes was withdrawn -> refund"),
    R("cand_conditional_faster", ("Jurong Point", "Suntec City"), loops=[{"frac": (0.40, 0.58)}], consent="conditional", band=2, geometry_from="rd_consent_except_road",
      slow_detour=12.0, complaint_text="I said ok only if it was faster. It was not: the ride took far longer than the app's estimate and the meter was well above it.",
      driver_text="The rider agreed to the other road. The traffic there was slow too; that is not my fault.",
      expect={"ruling": "refund_partial", "flag": False}, hard="'can go via X, should be faster?' / 'ok if it's faster'; the trip ran well over the estimate, so the condition failed and there is no consent, although X was driven -> refund"),
    R("cand_misattributed_ok", ("Compass One", "Kallang Wave Mall"), loops=[{"frac": (0.40, 0.58)}], consent="misattributed", band=2, geometry_from="bl_named_elsewhere",
      complaint_text="He said he was going another way but I never answered; the only ok I sent was about my luggage. The meter was well above the estimate.",
      driver_text="I told the rider I was going another way and the rider said ok.",
      expect={"ruling": "refund_partial", "flag": False}, hard="the rider's only 'ok' answered 'Can I put your luggage in the boot?'; the later 'Jam ahead, I go via Y ok?' got no reply -> no consent to the route, refund"),
    R("cand_buried_general", ("AMK Hub", "Marina Bay Sands"), loops=[{"frac": (0.48, 0.66)}], consent="general_buried", band=2, geometry_from="rd_named_cn_am",
      complaint_text="I never agreed to any detour. The meter came out well above the estimate.",
      driver_text="Before pickup the rider told me to take whatever way, just get there on time, so I went round the jam.",
      expect={"ruling": "no_action", "flag": False}, hard="among 18 pickup messages, the 9th is the rider's 'whatever way you want, just get me there by ...'; the complaint says 'I never agreed to any detour': a general route choice before the detour covers it (RD-5), the rest is within tolerance -> no refund"),
    R("cand_phone_claim_chat_consent", ("Clarke Quay", "Bedok Mall"), loops=[{"frac": (0.55, 0.72)}], consent="before", yes="ok go via {road}", extra_unrecorded_call=True,
      geometry_from="rd_cte_consent_connector", driver_text="I told her on the phone before the turn and she said ok.",
      complaint_text="I never agreed to anything on the phone. The meter came out well above the estimate.",
      expect={"ruling": "no_action", "flag": False}, hard="the driver relies on an unrecorded phone call, which proves nothing; but the chat holds the rider's own 'ok go via X' before the turn-off, and X was driven: the chat consent decides (RD-5) -> no refund"),
    R("cand_wrong_7eleven", ("Jurong East MRT", "Junction 8"), loops=[{"place": "Rifle Range Road 7-Eleven"}], stop="named_missed", named_place="Bukit Timah Plaza",
      stop_text="Can stop at the 7-Eleven at {place}?",
      expect={"ruling": "refund_partial", "flag": False}, hard="the rider asked for the 7-Eleven at Bukit Timah Plaza; the car stopped at a different 7-Eleven ~290 m away, off the route: not the place she named (RD-3 not met) -> refund"),
    N("cand_coming_down", ("Bedok Mall", "Raffles Place"), by="driver", park_m=40, within_s=310, here=True, chat="coming_down", reason_reading="no_show",
      expect={"ruling": "no_action", "flag": False}, hard="at minute 4 the rider wrote 'coming down in 1 min'; the driver waited to 5:10, had messaged and called, and cancelled as a no-show: a promise to come is not coming, NS-1 holds -> fee stands"),
    N("cand_cant_find_you", ("Tampines Mall", "Changi Airport T1"), by="driver", park_m=40, wait_s=360, here=True, reason_reading="no_show",
      cancel_text="Can't find you, cancelling.",
      expect={"ruling": "no_action", "flag": False}, hard="after 6 min at the pickup, messages and a call: 'Can't find you, cancelling.' means the rider did not show (NS-0), not a reason of his own; NS-1 holds -> fee stands"),
    R("cand_sarcastic", ("Jurong East MRT", "NUS"), loops=[{"frac": (0.35, 0.60)}], consent="sarcastic", band=2, geometry_from="rd_notice_ack_hmm",
      complaint_text="He announced another detour and I made clear I was not happy about it. He went anyway and the meter was well above the estimate.",
      driver_text="I told the rider I was going another way because it was faster, and the rider did not object.",
      expect={"ruling": "refund_partial", "flag": False}, hard="'I'm going via Z. Faster.' / 'wow great, another detour, love it 🙄': a sarcastic objection, not an acknowledgement -> refund"),
    G("cand_notice_paren", ("Orchard Road", "Marina Bay Sands"), 1.0, 1.3, notice="paren",
      expect={"ruling": "no_action", "flag": False}, hard="the in-app notice before pickup: 'Fares are higher than usual right now (1.3× surge). New estimate $X. Cancel free anytime.': the multiplier in brackets is still stated, with the fare and free cancellation -> no refund"),
]


# ----------------------------------------------------------------------------------------------- route cases

FRAC_SHIFTS = [0.0, 0.08, -0.08, 0.16, -0.16]
MIN_REPLACED_KM = contract.MIN_REPLACED_KM   # a loop whose story goes round a stretch must really bypass this much of the optimal route


CALL_CONSENT = ("recorded_call", "verbal_unrecorded", "unrecorded_call")     # the route was raised by voice: a recorded call before pickup, or a spoken word in the car (no record)


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
    """Loop dict for compose() from a loop spec and a candidate: (shift, side, offset_m) = one via point beside the
    stretch's middle; (shift, side, offset_m, "corridor") = two via points on a road running parallel to the stretch
    (the car cannot be routed back onto the stretch between them, so the loop is a different way, not a spur);
    (back_km, fwd_km) = a loop through a named place."""
    if "place" in lp:
        via = LOC[lp["place"]]
        _, along = project(via[0], via[1], opt)
        back, fwd = cand
        i1, i2 = vertex_at(opt, cum, along - back), vertex_at(opt, cum, along + fwd)
        vias = [via]
    else:
        shift, side, dist = cand[:3]
        a, b = lp["frac"][0] + shift, lp["frac"][1] + shift
        L = cum[-1]
        if a * L < 0.8 or b * L > L - 0.8:
            return None
        i1, i2 = vertex_at(opt, cum, a * L), vertex_at(opt, cum, b * L)
        if len(cand) == 4:
            vias = [perp_point(opt, cum, (a + CORRIDOR_INSET * (b - a)) * L, side, dist), perp_point(opt, cum, (b - CORRIDOR_INSET * (b - a)) * L, side, dist)]
        else:
            vias = [perp_point(opt, cum, (a + b) / 2 * L, side, dist)]
    if i2 <= i1 + 2:
        return None
    return {"leave": opt[i1], "via": vias, "rejoin": opt[i2], "i1": i1, "i2": i2}


def loop_candidates(lp):
    if "place" in lp:
        return list(SPAN_CANDIDATES)
    # corridor candidates first (they are the believable shape); the single-via ones only when no corridor fits
    offs = [tuple(o) for o in lp.get("offsets", OFFSET_CANDIDATES)]
    return [(sh, side, d, "corridor") for sh in FRAC_SHIFTS[:3] for side, d in offs] + [(sh, side, d) for sh in FRAC_SHIFTS for side, d in offs]


def plan_from_entry(entry: dict | None, opt):
    """The loops a published case was built with (its manifest `plan`), re-anchored on the route's vertices; None when
    the case has no pinned plan. A rebuild with a plan never searches: the geometry is the one on record."""
    if not entry or not entry.get("plan"):
        return None
    loops = []
    for lp in entry["plan"]:
        i1, i2 = nearest_idx(opt, tuple(lp["leave"])), nearest_idx(opt, tuple(lp["rejoin"]))
        loops.append({"leave": opt[i1], "via": [tuple(v) for v in lp["via"]], "rejoin": opt[i2], "i1": i1, "i2": i2})
    return loops


def plan_of(loops) -> list[dict]:
    return [{"leave": [round(x, 6) for x in lp["leave"]], "via": [[round(x, 6) for x in v] for v in lp["via"]], "rejoin": [round(x, 6) for x in lp["rejoin"]]} for lp in loops]


def retrace_fraction(opt, cum, seg, trip_gps) -> float:
    """Share (by length) of the replaced stretch that the car drove anyway during the segment: an out-and-back scores ~1."""
    stretch = [(p, km) for p, km in zip(opt, cum) if seg["entry_km"] + 0.05 <= km <= seg["exit_km"] - 0.05]
    inside = [(p["lat"], p["lon"]) for p in trip_gps[seg["i0"]:seg["i1"] + 1]] if "i0" in seg else []
    if len(stretch) < 2 or not inside:
        return 0.0
    near = [min(haversine_m(q, g) for g in inside) <= 60 for q, _ in stretch]
    total = sum(haversine_m(stretch[i][0], stretch[i + 1][0]) for i in range(len(stretch) - 1))
    redriven = sum(haversine_m(stretch[i][0], stretch[i + 1][0]) for i in range(len(stretch) - 1) if near[i] and near[i + 1])
    return redriven / total if total else 0.0


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


def _timing(cum, spans, cz_level, profile, slow_detour=None):
    """(zones, time_at, km_at) for a driven polyline: time_at(km) = seconds of driving to reach km (zones at their own speed,
    else the road-class profile; halts not included), km_at(t) its inverse."""
    from trajectory import profile_time_s
    zones = []
    if cz_level and spans:
        z0 = max(spans[0][0] - CONGESTION_LEN_KM, 0.3)
        zones.append(Congestion(z0, min(spans[0][0] + CRAWL_PAST_KM, cum[-1] - 0.3), BAND_SPEED[cz_level]))
    if slow_detour and spans:           # the way round was slow too: a crawl on the detour itself
        lo, hi = spans[0][0] + 0.6, min(spans[0][0] + 2.6, spans[0][1] - 0.4)
        if hi > lo:
            zones.append(Congestion(lo, hi, slow_detour))

    def time_at(km):
        t, pos = 0.0, 0.0
        for z in sorted(zones, key=lambda z: z.from_km):
            lo, hi = max(pos, z.from_km), min(km, z.to_km)
            if hi > lo:
                t += profile_time_s(profile, pos * 1000, lo * 1000) + (hi - lo) / z.speed_kmh * 3600
                pos = hi
        t += profile_time_s(profile, pos * 1000, max(km, pos) * 1000)
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
    profile = profile_of(poly, [route, *legs], is_night(pickup_at))
    zones, time_at, km_at = _timing(cum, spans, cz_level, profile, spec.get("slow_detour"))

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
        stops.append(Stop(*poly[vi], start_s=st, duration_s=dur, jitter_m=STILL_JITTER_M))
        if tag[0] == "pause":
            pause_start[tag[1]] = st
        extra += dur
    total_s = r5(time_at(L)) + extra
    _, trip_gps, found, legs2 = detour_trace(rp, opt, [{k: v for k, v in lp.items() if k in ("leave", "via", "rejoin")} for lp in loops],
                                              pickup_at, total_s, stops=stops, zones=zones, seed=spec["seed"], profile_of=lambda *_: profile)
    for f in found:
        if f["extra_km"] < spec.get("min_extra_km", 0.5):
            raise ValueError(f"segment adds only {f['extra_km']} km")
    hidden = (distance_km(trip_gps) - route["total_km"]) - sum(f["extra_km"] for f in found)
    if not -0.3 <= hidden <= 0.9:          # validate.py allows 1.0 km hidden inside the 200 m band; 5 s steps at expressway speed cut corners
        raise ValueError(f"{hidden:.2f} km of extra distance hidden inside the on-route band")
    return {"poly": poly, "spans": spans, "legs": legs2, "gps": trip_gps, "found": found, "total_s": total_s, "stops": stops,
            "pause_start_s": [pause_start[j] for j in range(len(pauses_km))], "time_at": time_at, "km_at": km_at}


def build_route(spec, rates, rp, idx, rng, grng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    opt = [tuple(p) for p in route["polyline"]]
    cum = along_km(opt)
    pickup_at = spec["day"]
    night = is_night(pickup_at)
    approach_start, approach_s = approach_leg(rp, P, D, grng, night=night)
    if spec["consent"] == "general_buried":
        approach_s = max(approach_s, 160) + 50        # two halts on the way, where the driver answers the small talk
    accepted = pickup_at - timedelta(seconds=approach_s + 10)
    stop_dur = {"named": 240, "unnamed": 250, "driver_errand": 240, "named_missed": 240}.get(spec["stop"], 0)
    stops_spec = [(0, stop_dur)] if spec["stop"] != "none" else []
    cz = spec["band"]
    consent = spec["consent"]
    # pickup chatter happens only when nothing else is scripted; decided now because the driver's line needs a halt in the approach
    innocuous = consent == "none" and spec["stop"] == "none" and not spec["threat"] and rng.random() < 0.5
    car, outfit = rng.choice(CARS), rng.choice(OUTFITS)

    # ---- the loops: a pinned plan (the case's own record) or a search over candidates, all loops chosen together ----
    # A frac loop must replace >= MIN_REPLACED_KM of the optimal route when its story goes round a stretch (else
    # >= MIN_REPLACED_PLAIN_KM: an out-and-back spur bypasses nothing), add >= MIN_EXTRA_KM, re-drive at most RETRACE_MAX
    # of the stretch, and drive at most RATIO_HARD times it. Among the valid plans the one whose refundable extra
    # distance is nearest the case's target amount wins (ratio above RATIO_SOFT and retracing cost score).
    # A loop through a named place is the rider's own request: the first candidate that measures cleanly is kept.
    n_loops = len(spec["loops"])
    target_km = (spec.get("target") or TARGET_REFUNDS[int(hashlib.sha256(spec["name"].encode()).hexdigest(), 16) % len(TARGET_REFUNDS)]) / rates["rate_per_km"]

    def trial_of(loops_try, k):
        """(score, loop, trial) for loop k of loops_try, or None when the plan is not valid."""
        try:
            trial = _try_trace(rp, route, opt, loops_try, pickup_at, spec, [s for s in stops_spec if s[0] <= k], cz)
        except (ValueError, RuntimeError, AssertionError, urllib.error.HTTPError) as e:
            if "leg not in cache" in str(e):
                OFFLINE_SKIPS[spec["name"]] = OFFLINE_SKIPS.get(spec["name"], 0) + 1   # reported by main(): an online run may choose this candidate
            return None        # no clean segment, or OneMap found no route (via point in the sea / a reserve)
        seg = trial["found"][k]
        if "place" in spec["loops"][k]:
            return (0.0, trial)
        need = MIN_REPLACED_KM if (k == 0 and loop_must_bypass(spec)) else MIN_REPLACED_PLAIN_KM
        ratio = seg["driven_km"] / seg["route_km"] if seg["route_km"] else 99.0
        if seg["route_km"] < need or seg["extra_km"] < spec.get("min_extra_km", MIN_EXTRA_KM) or ratio > RATIO_HARD:
            return None
        measured = contract.segments(trial["gps"], opt)
        retrace = retrace_fraction(opt, cum, measured[k], trial["gps"]) if k < len(measured) else 1.0
        if retrace > RETRACE_MAX:
            return None
        if "place" not in spec["loops"][k] and spec["stop"] == "none" and k < len(measured) and not spec.get("allow_loopback") \
                and contract.loops_back(trial["gps"][measured[k]["i0"]:measured[k]["i1"] + 1], near_m=60):   # wider than the linter's 35 m
            return None        # an out-and-back spur, a U-turn or a closed loop inside the detour: not a way round
        if spec.get("max_excess_km") is not None and r2(distance_km(trial["gps"])) - route["total_km"] > spec["max_excess_km"]:
            return None        # the story is "inside the 1 km tolerance": the billed excess must stay under it
        if k == 0 and cz and not crawl_reaches_segment(trial["gps"], seg["start"], cz):
            return None        # the crawl must still be on when the measured segment starts (what the contract reads)
        t_entry = secs(pickup_at, datetime.fromisoformat(seg["start"]))
        if k == 0 and (consent != "none" or spec["stop"] != "none") and t_entry < 80:
            return None        # the chat about this loop needs room before it
        so_far = sum(f["extra_km"] for f in trial["found"][:k])
        want = target_km * (k + 1) / n_loops - so_far
        return (abs(seg["extra_km"] - want) + 0.5 * max(0.0, ratio - RATIO_SOFT) + retrace, trial)

    loops = plan_from_entry(spec.get("_entry"), opt)
    if loops is not None:
        for k in range(n_loops):
            if trial_of(loops[:k + 1], k) is None:
                raise RuntimeError(f"{spec['name']}: the pinned plan no longer builds a valid loop {k} (rebuild with --replan)")
    else:
        plans = [([], 0.0)]                                     # (loops so far, score so far)
        for k, lp in enumerate(spec["loops"]):
            nxt = []
            for prev, sc in plans:
                for cand in loop_candidates(lp):
                    loop = _loop_from_spec(opt, cum, lp, cand)
                    if loop is None or (prev and loop["i1"] <= prev[-1]["i2"]):
                        continue
                    r = trial_of(prev + [loop], k)
                    if r is not None:
                        nxt.append((prev + [loop], sc + r[0]))
                        if "place" in lp or (r[0] <= GOOD_ENOUGH and k + 1 == n_loops):
                            break          # the amount is within GOOD_ENOUGH km of the target: stop spending OneMap calls
            if not nxt:
                raise RuntimeError(f"{spec['name']}: no candidate produced loop {k}")
            nxt.sort(key=lambda x: x[1])
            plans = nxt[:TOP_FIRST] if k + 1 < n_loops else nxt[:1]
        loops = plans[0][0]

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
        elif consent not in ("none", "general_buried") + CALL_CONSENT:
            halt(t_entry - 200, "ask")
        if spec["stop"] in ("named", "unnamed", "named_missed"):
            halt(t_entry - 210, "stop_ok")
        if spec["threat"] == "driver":
            pauses_km.append((spans[0][0] + spans[0][1]) / 2)     # inside the loop, on its surface roads
            chat_plan["threat"] = len(pauses_km) - 1
        tr = _try_trace(rp, route, opt, loops, pickup_at, spec, stops_spec, cz, pauses_km)
        poly, spans, legs, trip_gps, found, total_s, stops = tr["poly"], tr["spans"], tr["legs"], tr["gps"], tr["found"], tr["total_s"], tr["stops"]
        halts = [pickup_at + timedelta(seconds=s) for s in tr["pause_start_s"]]
    else:
        # no loop: the trip follows the route; in heavy rain the traffic is slow (the fare runs over the estimate on time)
        prof = profile_of(opt, [route], night)
        total_s = r5(max(drive_time_s(prof), route["total_min"] * 60 * 1.35 if spec["weather"] == "heavy" else 0))
        trip_gps = build_trajectory(opt, pickup_at, total_s, seed=spec["seed"], profile=prof)
        poly, spans, legs, stops, found, halts = opt, [], [], [], [], []
    dropoff_at = pickup_at + timedelta(seconds=total_s)
    seg_start = [datetime.fromisoformat(f["start"]) for f in found]
    gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"],
                         pauses=[(30, PAUSE_S), (75, PAUSE_S)] if consent == "general_buried" else [(APPROACH_PAUSE_S, PAUSE_S)] if innocuous else (),
                         profile_of=lambda pl, lg: profile_of(pl, lg, night), jitter_m=STILL_JITTER_M) + trip_gps[1:]
    annotate_roads(gps, [rp.route([approach_start, P]), route, *legs])
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
        bands.append(band_on(road, cz, w0, datetime.fromisoformat(found[0]["end"]), opt[loops[0]["i1"]:loops[0]["i2"] + 1]))   # the jam lasts the detour
    bands += gps_bands(route, legs, gps, w0, w1, skip=set(stretch_roads if cz else []), max_n=2)
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
        where = ""          # the exit an incident sits after is not on the route record; DataMall's text without it is still complete
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
        # the road the driver names is the one the segment drove most (GPS road names, RD-5), never the congested stretch
        # itself, else "go round via X to avoid X" is self-contradictory
        on_route = {r["name"] for r in route["roads"] if stretches[k][0] * 1000 - 300 <= r["to_m"] and r["from_m"] <= stretches[k][1] * 1000 + 300}
        driven = [r for r in roads_between(gps, found[k]["start"], found[k]["end"]) if r not in on_route] if k < len(found) else []
        others = [r for r in lg["roads"] if r["name"].title() != stretch_roads[0].title()] or lg["roads"]
        detour_road[k] = road_label(driven[0]) if driven else road_label(max(others, key=lambda r: r["to_m"] - r["from_m"])["name"])
        rest = [road_label(r) for r in driven[1:]] or [road_label(r["name"]) for r in sorted(others, key=lambda r: r["from_m"] - r["to_m"])
                                                       if road_label(r["name"]) != detour_road[k]]
        alt_road[k] = rest[0] if rest else "the service road alongside"
    jam = stretch_roads[0].title() if stretch_roads else ""
    road = detour_road.get(0, "")
    if consent == "named_elsewhere":
        # the rider agrees to a road the car then does not drive: a real road beside the stretch that no GPS sample names
        road = untied_road(rp, opt, cum, stretches[0][0], stretches[0][1], {p["road"] for p in gps if p.get("road")})
    if "ask" in chat_plan:
        t_ask = halts[chat_plan["ask"]] + timedelta(seconds=TYPED_AT_S)
        if consent in ("before", "after", "before_seg1", "named_elsewhere", "notice_ack"):
            yes = (spec.get("yes") or rng.choice(YES_LINES)).format(road=road)
            ask = (spec.get("ask") or rng.choice(ASK_LINES)).format(jam=jam, alt=road, road=road)
            chat_lines += [(t_ask, "driver", ask), (t_ask + timedelta(seconds=40), "rider", yes)]
        elif consent == "retracted":
            # a yes, then a clear retraction, both before the turn-off
            chat_lines += [(t_ask, "driver", f"Jam ahead, can I go via {road}?"), (t_ask + timedelta(seconds=40), "rider", "ok"),
                           (t_ask + timedelta(seconds=70), "rider", f"actually no, please stay on {jam}.")]
        elif consent == "conditional":
            chat_lines += [(t_ask, "driver", f"Jam ahead, can go via {road}, should be faster?"), (t_ask + timedelta(seconds=40), "rider", "ok if it's faster")]
        elif consent == "misattributed":
            # the rider's only "ok" answers a question about luggage, at the pickup; the route notice that follows gets no answer
            chat_lines += [(pickup_at, "driver", "Can I put your luggage in the boot?"), (pickup_at + timedelta(seconds=30), "rider", "ok"),
                           (t_ask, "driver", f"Jam ahead, I go via {road} ok?")]
        elif consent == "sarcastic":
            chat_lines += [(t_ask, "driver", f"I'm going via {road}. Faster."), (t_ask + timedelta(seconds=40), "rider", "wow great, another detour, love it 🙄")]
        elif consent == "excluded_not_driven":
            # a yes with an exclusion, and the car keeps off the excluded road: a real road beside the stretch no GPS sample names
            excluded = untied_road(rp, opt, cum, stretches[0][0], stretches[0][1], {p["road"] for p in gps if p.get("road")})
            chat_lines += [(t_ask, "driver", "Jam ahead, shall I take another way?"), (t_ask + timedelta(seconds=40), "rider", f"可以，不要走 {excluded}。")]
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
        elif consent == "qualified":
            # a yes with a condition: "can, but not via Y" — and Y is the road the segment then drives
            chat_lines += [(t_ask, "driver", rng.choice(ASK_GENERAL_LINES).format(jam=jam)), (t_ask + timedelta(seconds=40), "rider", f"Can lah, but not via {road}.")]
        elif consent == "scope_other":
            chat_lines += [(t_ask, "driver", "Mind if I pull in at the petrol station just ahead for one minute? Tank is almost empty."),
                           (t_ask + timedelta(seconds=35), "rider", "Sure, no problem.")]
    if "stop_ok" in chat_plan:
        t_ok = halts[chat_plan["stop_ok"]] + timedelta(seconds=TYPED_AT_S)
        if spec["stop"] in ("named", "named_missed"):
            stop_place = spec["loops"][0]["place"]
            ask = (spec.get("stop_text") or "Can you stop at {place}? I need to grab a parcel, 3-4 minutes.").format(place=spec.get("named_place", stop_place))
        else:
            ask = "Can you stop at a 7-Eleven on the way? Just need 2 minutes."
        chat_lines += [(t_ok - timedelta(seconds=25), "rider", ask), (t_ok, "driver", rng.choice(["Ok", "Ok can", "Sure"]))]
    calls = []
    if spec.get("extra_unrecorded_call"):
        calls.append({"ts": iso(accepted + timedelta(seconds=60)), "caller": "driver", "callee": "rider", "answered": True, "duration_s": 25})
    if consent == "recorded_call":
        # the driver phoned the rider on the way to the pickup (hands-free); the trip call recording holds both sides (RD-5, §1.2)
        calls.append({"ts": iso(accepted + timedelta(seconds=60)), "caller": "driver", "callee": "rider", "answered": True, "duration_s": 40,
                      "recording_ref": f"REC-{trip['trip_id']}-1",
                      "transcript": f"Driver: {'Accident' if inc_kind != 'none' else 'Jam'} on {jam} ahead, ok if I go round via {road}? Rider: Ok, can, go ahead."})
    elif consent == "unrecorded_call":
        # a call the platform logged (answered, 25 s) but did not record: no words of the rider are on record
        calls.append({"ts": iso(accepted + timedelta(seconds=60)), "caller": "driver", "callee": "rider", "answered": True, "duration_s": 25})
    # verbal_unrecorded: the driver's account of a spoken agreement is in his statement only; nothing on record
    if spec["threat"] == "impatient":
        # frustration, not a threat and not an insult: the rider's own words once the car has left the route
        chat_lines += [(seg_start[0] + timedelta(seconds=60), "rider", "Why you go this way?? I said stay. I'm late already.")]
    if "threat" in chat_plan:
        t = halts[chat_plan["threat"]]
        chat_lines += [(t - timedelta(seconds=40), "rider", "Why are we going this way? This is not the route on the app."),
                       (t + timedelta(seconds=TYPED_AT_S), "driver", "Shut up and let me drive.")]
    elif spec["threat"] == "trap":
        t = accepted + timedelta(seconds=60)
        line = f"I'll find you {PICKUP_SPOT.get(spec['pair'][0], 'at the main entrance')}, I am in a red jacket."
        chat_lines += [(t, "rider", line)]
    if consent == "general_buried":
        # pickup small talk; the 9th message is a general route choice the complaint later denies
        by_h = (pickup_at + timedelta(minutes=route["total_min"] + 40)).hour % 12 or 12
        talk = [(15, "rider", f"Hi, I'm {PICKUP_SPOT.get(spec['pair'][0], 'at the main entrance')}, {outfit}."), (25, "rider", f"Are you the {car}?"),
                (40, "driver", f"Yes, {car}. Coming."), (50, "driver", "Traffic a bit slow here."), (60, "rider", "No problem."),
                (70, "rider", "I have one small luggage."), (85, "driver", "Ok, boot has space."), (95, "driver", "About 2 min more."),
                (105, "rider", f"whatever way you want, just get me there by {by_h}"), (115, "rider", "Thanks!"), (125, "rider", "It's quite hot today."),
                (135, "rider", "I'll wait under the shelter."), (145, "rider", "Near the taxi queue."), (155, "rider", "Can see the traffic from here, quite bad."),
                (165, "rider", "No rush."), (175, "rider", "I see a car coming, is that you?"), (185, "rider", "Oh not you."), (195, "rider", "Ok I see you now.")]
        chat_lines += [(accepted + timedelta(seconds=o), who, text) for o, who, text in talk]
    if innocuous:
        t = accepted + timedelta(seconds=50)
        n = max(1, round((approach_s + 10 - (APPROACH_PAUSE_S + TYPED_AT_S)) / 60))
        chat_lines += [(t, "rider", rng.choice(PICKUP_LINES).format(spot=PICKUP_SPOT.get(spec["pair"][0], "at the main entrance"), outfit=outfit)),
                       (accepted + timedelta(seconds=APPROACH_PAUSE_S + TYPED_AT_S), "driver", rng.choice(ARRIVING_LINES).format(n=n, car=car))]
    chat_lines.sort(key=lambda x: x[0])
    for t, _, _ in chat_lines:
        assert accepted <= t <= dropoff_at, f"{spec['name']}: chat at {t} outside the trip"
    for t, who, _ in chat_lines:            # a driver who is driving does not type: every driver line sits in a halt
        if who == "driver" and t > pickup_at:
            at = min(gps, key=lambda p: abs((datetime.fromisoformat(p["ts"]) - t).total_seconds()))
            assert at["speed_kmh"] < 5, f"{spec['name']}: driver line at {t:%H:%M:%S} while moving ({at['speed_kmh']} km/h)"

    # ---- fare, statements, profiles ----
    fare = metered_fare(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), rates, fold_waiting=True) if service == "RydeTAXI" else fixed_fare(route, rates)
    extra_km = sum(f["extra_km"] for f in found)
    weather = WEATHER[spec["weather"]]
    rider_lines = {
        "none": rng.choice(RIDER_NONE_LINES).format(est=km_words(route["total_km"]), got=km_words(fare["distance_km"])),
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
        "qualified": f"I said can, but not via {road}. He went via {road} anyway and the fare was higher than the estimate.",
        "recorded_call": "The driver phoned me before pickup about a jam, but the fare still came out well above the estimate. I want the extra distance refunded.",
        "verbal_unrecorded": "The driver never asked me about changing the route. He went another way and the meter was well above the estimate. I want the extra refunded.",
        "notice_ack": "I never agreed to any detour, I just said hmm. The meter came out well above the estimate.",
        "excluded_not_driven": "I put conditions on the route, and the driver went a long way round. The fare was well above the estimate.",
        "unrecorded_call": "The driver rang me once before pickup but the line was bad. He never agreed a different route with me, and the meter came out well above the estimate.",
    }
    statement = spec.get("complaint_text") or rider_lines.get(consent, rider_lines["none"])
    if service == "RydeX" and found:
        # a fixed quote has no meter and no "more than the estimate": the rider's grievance is the route itself
        fixed_lines = {
            "none": f"The app showed a {route['total_km']:.0f} km route but the driver went a different way and never asked me. I know the fare was a fixed quote; I still want the detour on record.",
            "before": "The driver took a longer way round than the app showed. The fare was a fixed quote, but I want the detour looked at.",
        }
        statement = fixed_lines.get(consent, fixed_lines["none"])
    if spec["stop"] == "named":
        statement = f"I asked to stop at {stop_place} and we did, fine, but the fare was much more than the estimate. I think the detour was overcharged."
    elif spec["stop"] == "named_missed":
        statement = (f"I asked for the 7-Eleven at {spec['named_place']}; he drove to another one off the route instead. The meter was well above the estimate.")
    elif spec["stop"] == "unnamed":
        statement = "I asked for a quick 7-Eleven stop on the way, not a drive to one far off the route. The meter was way above the estimate."
    elif not found:
        statement = ("The fare was higher than I expected for this trip in heavy rain, the driver must have taken a longer route." if spec["weather"] == "heavy"
                     else "The fare was higher than the estimate, the driver must have taken a longer route than the app showed.")
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
        "named_elsewhere": f"I asked the rider about going via {road or 'the alternative road'} and the rider agreed. In the end I went by {detour_road.get(0, 'another road')} instead because it looked clearer; same direction.",
        "negation": "I asked the rider about the alternative road. The traffic was bad so I took it anyway; it was faster.",
        "qualified": "Traffic was building up ahead. I asked the rider and the rider said can, so I went round.",
        "recorded_call": f"I called the rider before pickup about the accident on {jam} and the rider agreed to go via {road}. The call is recorded.",
        "verbal_unrecorded": f"Before turning off I told the rider in the car that I would go via {road} because of the jam, and the rider said ok.",
        "notice_ack": f"I told the rider there was a jam on {jam} and that I was going via {road}, and the rider said ok.",
        "excluded_not_driven": "The rider said I could take another way as long as I kept off one road, and I kept off it.",
        "unrecorded_call": f"I called her before the turn about the jam on {jam}, said I would go via {road}, and she said ok. The call is in the app's log.",
    }
    dstmt = spec.get("driver_text") or driver_lines.get(consent, driver_lines["none"])
    if inc_kind in ("on_stretch", "seg1") and consent not in CALL_CONSENT:
        dstmt = f"There was an accident on {jam} ahead, lanes were blocked, so I went round it. The extra distance was unavoidable."
    elif inc_kind == "late":
        dstmt = f"There was an accident on {jam}; I went round it. The extra distance was unavoidable."
    elif inc_kind == "decoy_far":
        dstmt = "There was a breakdown on the route, the whole road was slow, so I took another way. Check the LTA incident feed."
    elif spec["band"] and consent == "none":
        dstmt = f"{jam} was crawling" + (" and flooding in the heavy rain" if spec["weather"] == "heavy" else "") + ", so I went round it. Any driver would have done the same."
    if spec["stop"] == "named_missed":
        dstmt = "The rider asked for a 7-Eleven, so I went to the 7-Eleven I know there and waited."
    if spec["stop"] == "named":
        dstmt = f"The rider asked me to stop at {stop_place}, so I drove there and waited while the rider went in."
        if spec.get("dstmt_extra"):
            dstmt += " " + spec["dstmt_extra"]
    elif spec["stop"] == "unnamed":
        dstmt = "The rider asked for a 7-Eleven stop. I went to the one I know and waited."
    if not found:
        dstmt = ("I followed the app route exactly. The meter is what it is; it was raining and traffic was slow." if spec["weather"] == "heavy"
                 else "I followed the app route exactly. The meter is what it is; traffic was what it was.")
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
    if calls:
        case["calls"] = calls
    accounts(case, spec)
    if spec.get("gps_tail_cut_s"):
        cut = dropoff_at - timedelta(seconds=spec["gps_tail_cut_s"])
        if spec.get("tail_request"):
            # the rider asks for a change that falls in the stretch the trace no longer covers: whether the car went there
            # (a rider-requested route, RD-3) cannot be measured
            last = road_label(route["roads"][-1]["name"])
            case["chat"] = sorted(case["chat"] + msgs((cut - timedelta(seconds=45), "rider",
                                                       f"Can you go via {last} and drop me at the other side of {spec['pair'][1]} instead?")), key=lambda m: m["ts"])
        gps = [p for p in gps if datetime.fromisoformat(p["ts"]) <= cut]
        case["gps"] = gps
        found = measure_detours(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), opt)   # the manifest shows the segments the fact tool will see
        for f in found:
            f.pop("_raw", None)              # an unrounded float differs in its last digit across machines; the manifest keeps the rounded figures
    if consent == "named_elsewhere":
        detour_road = {**detour_road, 0: road}       # the road the rider agreed to (not driven)
    meta = {"segments": found, "stretch_roads": stretch_roads, "detour_roads": detour_road,
            "extra_km": round(extra_km, 2), "stop_place": stop_place, "plan": plan_of(loops)}
    return case, meta


# ----------------------------------------------------------------------------------------------- no-show cases

def driver_calls(*times):
    """Platform call log (official app_events driver_called_rider): the rider did not pick up."""
    return [{"ts": iso(t), "caller": "driver", "callee": "rider", "answered": False, "duration_s": 0} for t in times]


def build_noshow(spec, rates, rp, idx, rng, grng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    accepted = spec["day"]
    by = spec["by"]
    weather = WEATHER[spec["weather"]]
    contact = spec.get("contact", "both")          # driver's contact attempts before cancelling: both / message_only / call_only / none
    fee = (spec.get("policy") or {}).get("cancellation_fee", CANCEL_FEE)
    F = f"${fee:.2f}"
    chat_lines, calls, pressed, scheduled, legs = [], [], None, None, []
    if by == "driver":
        park_m = spec["park_m"]
        away = (bearing(D, P) + grng.uniform(-30, 30)) % 360          # park on the far side from the destination
        spot = offset(P, away, park_m) if park_m > 0 else P
        wait_s = spec.get("wait_s") or spec.get("within_s") or 300

        def trace(wait):
            cancelled = accepted + timedelta(seconds=approach_s + wait)
            return cancelled, build_trajectory(poly, accepted, secs(accepted, cancelled),
                                               stops=[Stop(*spot, start_s=approach_s, duration_s=wait, jitter_m=2.0,
                                                           anchor_s=0, away_from=P if park_m > 200 else None)], seed=spec["seed"],
                                               profile=profile_of(poly, [approach], is_night(accepted)), end_at_rest=False)
        for att in range(12):
            start = offset(spot, (away + grng.uniform(-70, 70)) % 360, grng.choice([800, 1000, 1200]))
            try:
                approach = rp.route([start, spot])
            except (urllib.error.HTTPError, RuntimeError):     # OneMap found no route (online), or that refused leg is not cached (offline)
                continue
            poly = approach["polyline"]
            if approach["total_km"] > 3.2:
                continue        # one-way systems can turn 1.1 km as the crow flies into a long drive; pick another start
            approach_s = max(120, r5(drive_time_s(profile_of(poly, [approach], is_night(accepted)))))   # road-class speeds
            cancelled, gps = trace(wait_s)
            dmin_before = min(haversine_m((p["lat"], p["lon"]), P) for p in gps if secs(accepted, datetime.fromisoformat(p["ts"])) < approach_s)
            if park_m > 200 and dmin_before <= 200:
                continue        # the approach must not brush the pickup radius when the story is "never arrived"
            break
        else:
            raise RuntimeError(f"{spec['name']}: no usable approach (length / 200 m radius)")
        legs.append(approach)
        park_at = accepted + timedelta(seconds=approach_s)
        # the car drives until it parks, and the arrival is confirmed as it parks: arrival time, parking and the tap coincide
        target = spec.get("within_s")
        if spec.get("wait_from_scheduled_s"):      # a booking for a set time (a whole minute) after the car has arrived
            early = park_at + timedelta(seconds=spec["scheduled_after_tap_s"] - 30)
            scheduled = early + timedelta(seconds=(60 - early.second) % 60)
            target = secs(park_at, scheduled) + spec["wait_from_scheduled_s"]
        if target:               # land NS-1 (ii)'s measure (seconds inside 200 m after the tap) exactly on the target
            got = after_tap_s(gps, P, park_at, cancelled)
            wait_s += target - got
            cancelled, gps = trace(wait_s)
            assert after_tap_s(gps, P, park_at, cancelled) == target, spec["name"]
        pressed = park_at if spec["here"] else None
        if spec.get("gps_hole_s"):      # the trace stops for a while in the middle of the wait
            h0 = park_at + timedelta(seconds=90)
            h1 = h0 + timedelta(seconds=spec["gps_hole_s"])
            gps = [p for p in gps if not (h0 < datetime.fromisoformat(p["ts"]) < h1)]
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=30), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by=spec.get("recorded_by", "driver"))
        if pressed:
            trip["driver_arrived_at"] = iso(pressed)     # the arrival on record is the confirmation, as in DISP-002
        reason = spec.get("app_reason", "rider_no_show")
        if reason and spec.get("recorded_by", "driver") is not None:
            trip["cancellation_reason"] = reason         # the reason the driver picked in the app: his claim
        plate = rng.choice(CARS)
        thr = (spec.get("policy") or {}).get("no_show_threshold_min", 5)     # the wait the driver claims follows the rule on the record
        here_line = rng.choice(HERE_LINES).format(car=plate)
        cancel_line = rng.choice(CANCEL_LINES).format(n=thr)
        if spec.get("recorded_by", "driver") is None:
            # who cancelled is not on record: neither the chat nor the statements may say it either, or the gap is no gap
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line)]
            statement = f"I was on my way down when the booking disappeared from my app, and I was charged {F}."
            dstmt = "I pressed I'm Here and waited at the pickup. The rider never boarded and the booking ended as cancelled."
        elif park_m > 200:
            chat_lines = [(park_at + timedelta(seconds=25), "driver", rng.choice(HERE_FAR_LINES).format(car=plate)),
                          (park_at + timedelta(seconds=80), "rider", rng.choice(WHERE_LINES)),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = f"The driver marked arrived but was never at the pickup point. I waited there the whole time and then got charged {F} as a no-show."
            dstmt = f"I pressed I'm Here, called the rider and waited more than {thr} minutes at the pickup. The rider never showed up, so I cancelled as a no-show."
        elif not spec["here"]:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"At the pickup point, {plate}."),
                          (cancelled - timedelta(seconds=10), "driver", f"Waited {thr} min, cancelling")]
            statement = f"The driver cancelled and I was charged {F}. I was on my way down."
            dstmt = f"I waited {thr} minutes at the pickup and cancelled as a no-show. I forgot to press the I'm Here button but I was there."
        elif spec.get("chat") == "threat":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here, {plate}."),
                          (park_at + timedelta(seconds=120), "rider", "2 min, coming"),
                          (cancelled - timedelta(seconds=20), "driver", "Hurry up or I will find you and you will regret it.")]
            statement = f"The driver threatened me in the chat and then cancelled and charged me {F}."
            dstmt = f"I waited more than {thr} minutes and called. The rider said 2 minutes and never came. I cancelled as a no-show."
        elif spec.get("chat") == "impatient":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line),
                          (park_at + timedelta(seconds=150), "driver", "Hello? Still waiting ah, so slow."),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = f"The driver kept rushing me in the chat and cancelled just as I was coming down. I was charged {F}."
            dstmt = f"I pressed I'm Here, called and waited more than {thr} minutes. The rider did not come, so I cancelled."
        elif spec.get("chat") == "coming_down":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line),
                          (park_at + timedelta(seconds=240), "rider", "coming down in 1 min"),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = f"I told the driver I was coming down in a minute and he cancelled anyway. I was charged {F}."
            dstmt = f"I pressed I'm Here, messaged and called, and waited more than {thr} minutes. The rider said 1 minute and still did not come."
        elif spec.get("chat") == "gate":
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm at Gate B, {plate}."),
                          (park_at + timedelta(seconds=110), "rider", "I'm at Gate A, can you come here?"),
                          (park_at + timedelta(seconds=150), "driver", "Cannot stop at Gate A, double yellow line, please come to Gate B."),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = f"The driver refused to come to me at Gate A, then cancelled and charged me {F}."
            dstmt = f"I pressed I'm Here at Gate B, messaged and called. Gate A has a double yellow line. I waited more than {thr} minutes and cancelled."
        elif park_m >= 150:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", f"I'm here, {plate}, at the side road."),
                          (park_at + timedelta(seconds=120), "rider", "I'm at the entrance, I don't see you"),
                          (park_at + timedelta(seconds=150), "driver", f"I'm at the side road taxi bay, {plate}. Please come to the side road."),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            statement = f"The driver was not at the entrance where the pin was. He cancelled and I was charged {F}."
            dstmt = f"I was parked at the pickup, a short walk from the entrance, pressed I'm Here, called and waited more than {thr} minutes."
        else:
            chat_lines = [(park_at + timedelta(seconds=30), "driver", here_line),
                          (cancelled - timedelta(seconds=10), "driver", cancel_line)]
            if scheduled:
                statement = (f"My ride was booked for {scheduled:%H:%M}. The driver cancelled {max(1, round(secs(scheduled, cancelled) / 60))} minutes after that "
                             f"and I was charged {F}. I was coming down.")
                dstmt = f"I arrived early, pressed I'm Here and waited more than {round(secs(pressed, cancelled) / 60)} minutes. The rider never came, so I cancelled."
            else:
                statement = rng.choice(CAME_OUT_LINES).format(fee=f"{fee:.2f}")
                dstmt = (rng.choice(NOSHOW_DRIVER_LINES).format(n=thr) if thr == 5 else
                         f"I pressed I'm Here and waited the full {thr} minutes the rule gives. Rider no-show, so I cancelled.")
        # contact attempts before the cancellation (NS-1 (iii): at least one in-app message AND one in-app call)
        if contact in ("both", "call_only") and spec.get("recorded_by", "driver") is not None:
            calls = driver_calls(park_at + timedelta(seconds=min(90, max(45, secs(park_at, cancelled) // 2))))
            if 150 <= park_m <= 200 and spec.get("chat") != "gate":   # he answered "I don't see you" with where he was, and rang again
                calls += driver_calls(park_at + timedelta(seconds=180))
        if contact in ("call_only", "none"):
            chat_lines = [x for x in chat_lines if x[1] != "driver"]
        if spec.get("claim") == "never_called":
            statement += " He never even called me."           # the platform's call log says otherwise
        if spec.get("cancel_text"):
            # what the driver actually wrote when he cancelled: the reading of his reason (NS-0) turns on these words
            last = max(i for i, x in enumerate(chat_lines) if x[1] == "driver")
            chat_lines[last] = (chat_lines[last][0], "driver", spec["cancel_text"])
            if spec.get("reason_reading") == "own_reason":
                dstmt = f"I waited at the pickup, pressed I'm Here and called, but then {spec['own_reason']}, so I had to cancel."
        if spec.get("complaint_safety"):
            statement += (" When I called him back about the charge he kept making comments about my body and asked where I live. "
                          "I felt very uncomfortable.")
        if contact == "message_only":
            dstmt = dstmt.replace(", called the rider", "").replace(", called", "") + " I messaged the rider in the app; I did not call."
            statement += " He never called me."
        elif contact == "call_only":
            dstmt = dstmt.replace(", called the rider", "").replace(", called", "") + " I called the rider once; nobody answered."
            statement += " There was no message from him in the app."
        elif contact == "none":
            dstmt = dstmt.replace(", called the rider", "").replace(", called", "") + " The rider should have been at the pickup."
            statement += " He never messaged or called me."
        end = cancelled
    elif by == "driver_other":
        # the driver cancels on the way for a reason of his own (NS-3): no arrival, no no-show
        cancel_s = spec["cancel_s"]
        cancelled = accepted + timedelta(seconds=cancel_s)
        stop_s = cancel_s - 60             # the tyre goes; the car stands at the kerb from then until the cancellation
        poly, approach = _en_route(rp, P, D, grng, 30.0 / 3600 * stop_s, spec["name"])
        legs.append(approach)
        gps = build_trajectory(poly, accepted, cancel_s, stops=[Stop(*poly[-1], start_s=stop_s, duration_s=cancel_s - stop_s, jitter_m=STILL_JITTER_M)],
                               seed=spec["seed"], end_at_rest=False)
        chat_lines = [(accepted + timedelta(seconds=40), "rider", rng.choice(HOW_LONG_LINES)),
                      (accepted + timedelta(seconds=stop_s + 25), "driver", "Sorry, my car has a flat tyre, I have to cancel. Please book another car.")]
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=30), accepted, gps, None, cancelled_at=cancelled, cancelled_by="driver")
        trip["cancellation_reason"] = "driver_vehicle_issue"
        statement = f"The driver cancelled because of a problem with his car, and I was still charged {F}. That is not my fault."
        dstmt = "I got a flat tyre on the way to the pickup and had to cancel. It was nothing to do with the rider."
        end = cancelled
    else:  # rider cancelled
        cancel_s = spec["cancel_s"]
        cancelled = accepted + timedelta(seconds=cancel_s)
        if spec["driver"] == "late":
            # a booking for a set time; the driver is still crawling through traffic well after it
            sched_s = spec.get("scheduled_after_accept_s", 300)
            scheduled = accepted + timedelta(seconds=sched_s)
            poly, approach = _en_route(rp, P, D, grng, 15.0 / 3600 * cancel_s, spec["name"], dist_m=4500)
            legs.append(approach)
            contacted = contact != "none"
            halt_s = sched_s + 60
            gps = build_trajectory(poly, accepted, cancel_s, stops=pause_stops(poly, cancel_s - PAUSE_S, [(halt_s, PAUSE_S)], jitter_m=STILL_JITTER_M) if contacted else (),
                                   seed=spec["seed"], end_at_rest=False)
            chat_lines = [(scheduled + timedelta(seconds=20), "rider", "Hi, where are you? It's already the pickup time."),
                          (cancelled - timedelta(seconds=20), "rider", "Still no car. I'm cancelling.")]
            if contacted:
                chat_lines.append((accepted + timedelta(seconds=halt_s + TYPED_AT_S), "driver", "Sorry, stuck in a bad jam, about 10 more minutes."))
                calls = driver_calls(scheduled + timedelta(seconds=330))
            late_min = round((cancel_s - sched_s) / 60)
            statement = (f"My ride was booked for {scheduled:%H:%M}. {late_min} minutes later the driver was still nowhere near, so I cancelled, and I was charged {F}."
                         + ("" if contacted else " He never messaged or called me."))
            dstmt = ("Traffic was very heavy on the way. I messaged and called the rider to say I was running late." if contacted
                     else "Traffic was very heavy on the way to the pickup.")
        elif spec["driver"] == "en_route":
            poly, approach = _en_route(rp, P, D, grng, 30.0 / 3600 * cancel_s, spec["name"])
            legs.append(approach)
            # the driver answers the rider's question at a halt (a junction about a minute into the drive), not while driving
            halt_s = 60 if cancel_s > 120 else None
            gps = build_trajectory(poly, accepted, cancel_s, stops=pause_stops(poly, cancel_s - PAUSE_S, [(halt_s, PAUSE_S)], jitter_m=STILL_JITTER_M) if halt_s else (),
                                   seed=spec["seed"], end_at_rest=False)
            chat_lines = [(accepted + timedelta(seconds=40), "rider", rng.choice(HOW_LONG_LINES)),
                          (accepted + timedelta(seconds=halt_s + TYPED_AT_S), "driver", rng.choice(ETA_LINES))] if halt_s else []
            statement = (f"The driver was still far away after more than 3 minutes so I cancelled and booked another ride, and got charged {F}."
                         if cancel_s > 180 else
                         rng.choice([f"I cancelled within 3 minutes because the driver was nowhere near, and still got charged {F}.",
                                     f"The driver was nowhere near, so I cancelled less than 3 minutes after matching and still got charged {F}."]))
            dstmt = rng.choice(ON_WAY_LINES)
        else:  # driver parked at the pin, rider cancels late
            spot = offset(P, (bearing(D, P)) % 360, 40)
            for att in range(24):
                start = offset(spot, (bearing(D, P) + grng.uniform(-70, 70) + (180 if att >= 12 else 0)) % 360, grng.choice([500, 700, 900]))
                try:
                    approach = rp.route([start, spot])
                except (urllib.error.HTTPError, RuntimeError):     # OneMap found no route (online), or that refused leg is not cached (offline)
                    continue
                if approach["total_km"] <= 1.8:
                    break
            else:
                raise RuntimeError(f"{spec['name']}: no short approach to the pickup")
            legs.append(approach)
            park_s = min(max(120, r5(approach["total_km"] / 25 * 3600)), cancel_s - 150)
            gps = build_trajectory(approach["polyline"], accepted, cancel_s,
                                   stops=[Stop(*spot, start_s=park_s, duration_s=cancel_s - park_s, jitter_m=1.5)], seed=spec["seed"])
            pressed = accepted + timedelta(seconds=park_s + 15)
            chat_lines = [(pressed, "driver", rng.choice(HERE_LINES).format(car=rng.choice(CARS))),
                          (accepted + timedelta(seconds=300), "rider", "Sorry, plans changed, I will cancel")]
            statement = f"I cancelled because my plans changed and the driver had not even arrived. {F} is unfair."
            dstmt = "I was parked at the pickup for minutes when the rider cancelled."
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=30), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by="rider")
        trip["cancellation_reason"] = "driver_taking_too_long" if spec["driver"] in ("late", "en_route") else "rider_changed_plans"
        end = cancelled
    if scheduled:
        trip["scheduled_at"] = iso(scheduled)
    chat_lines.sort(key=lambda x: x[0])
    for t, _, _ in chat_lines:
        assert accepted <= t <= end, f"{spec['name']}: chat at {t} outside accepted..cancelled"
    bands = gps_bands(legs[0], [], gps, accepted - timedelta(minutes=5), end + timedelta(minutes=5), max_n=1)
    annotate_roads(gps, legs)
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
        "fare": cancellation_fare(rates, fee),
        "chat": msgs(*chat_lines),
        "driver_statement": dstmt,
        "profiles": profiles(r_prof, d_prof),
    }
    if calls:
        case["calls"] = calls
    accounts(case, spec)
    if spec.get("policy"):          # the record states its own parameters (the organisers' sample format)
        case["policy_params"] = dict(spec["policy"])
    return case, {}


def _en_route(rp, P, D, grng, drive_km, name, dist_m=2600):
    """(driven polyline, approach route) for a driver still on the way: a start dist_m from the pickup (far side from the
    destination) whose route brings the car closer without entering the 200 m radius within drive_km."""
    for _ in range(12):
        start = offset(P, (bearing(D, P) + grng.uniform(-30, 30)) % 360, dist_m)
        approach = rp.route([start, P])
        full = [tuple(p) for p in approach["polyline"]]
        cum = along_km(full)
        if cum[-1] < drive_km + 0.6:
            continue
        cut = vertex_at(full, cum, drive_km)
        poly = full[:max(cut, 2) + 1]
        # the driver must be ON THE WAY: a one-way system can send the first kilometre away from the pickup, and a judge
        # reading the map would see a car driving off, not a driver who was "still far away"
        if haversine_m(poly[-1], P) < haversine_m(start, P) - 300 and min(haversine_m(q, P) for q in poly) > 200:
            return poly, approach
    raise RuntimeError(f"{name}: no approach route that brings the driver closer in time")



# ----------------------------------------------------------------------------------------------- safety cases

def build_safety(spec, rates, rp, idx, rng, grng):
    P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
    route = rp.route([P, D])
    opt = [tuple(p) for p in route["polyline"]]
    pickup_at = spec["day"]
    night = is_night(pickup_at)
    approach_start, approach_s = approach_leg(rp, P, D, grng, night=night)
    accepted = pickup_at - timedelta(seconds=approach_s + 10)
    prof = profile_of(opt, [route], night)
    zones = speeding_zones(route) if spec.get("speeding") else []
    drive_s = r5(drive_time_s(prof, zones))
    kind = spec["chat"]
    # the in-car exchange happens at a halt on a surface road (a junction), never at speed on an expressway: the driver's
    # line is typed during the halt, the rider's from the back seat just before / after it
    halts = [halt_at(opt, prof, surface_km(route, along_km(opt)[-1] * 0.5))] if kind in ("driver_threat", "rider_threat") else []
    pauses = [(h.start_s, h.duration_s) for h in halts]
    total_s = drive_s + sum(d for _, d in pauses)
    dropoff_at = pickup_at + timedelta(seconds=total_s)
    trip_gps = build_trajectory(opt, pickup_at, total_s, stops=halts, congestion=zones, seed=spec["seed"], profile=prof)
    gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"],
                         pauses=[(APPROACH_PAUSE_S, PAUSE_S)] if kind == "innocuous" else (), profile_of=lambda pl, lg: profile_of(pl, lg, night),
                         jitter_m=STILL_JITTER_M) + trip_gps[1:]
    annotate_roads(gps, [rp.route([approach_start, P]), route])
    service = spec["service"]
    trip = trip_block(f"T-{2000 + idx}", service, place(spec["pair"][0]), place(spec["pair"][1]), route,
                      accepted - timedelta(seconds=35), accepted, gps, pickup_at - timedelta(seconds=10), pickup_at, dropoff_at)
    halt = pickup_at + timedelta(seconds=pauses[0][0]) if pauses else None
    filed_by = "rider"
    if kind == "driver_threat":
        chat_lines = [(halt - timedelta(seconds=40), "rider", "Please stop the car, I want to get out here."),
                      (halt + timedelta(seconds=TYPED_AT_S), "driver", "Sit down or I lock the doors.")]
        statement = "The driver threatened to lock me in when I asked to get out. I felt unsafe for the whole ride."
        dstmt = "The rider tried to open the door at the lights. I told her to sit down for her own safety and drove on."
    elif kind == "rider_threat":
        chat_lines = [(halt + timedelta(seconds=TYPED_AT_S), "driver", "Please do not smoke in the car."),
                      (halt + timedelta(seconds=45), "rider", "Say that again and I will punch you.")]
        filed_by = "driver"
        statement = "The passenger threatened to punch me when I asked him not to smoke. I want this reported."
        dstmt = "I asked the passenger politely not to smoke in the car; he said he would punch me if I said it again. I kept driving and did not answer him."
    elif kind == "innocuous":
        n = max(1, round((approach_s + 10 - (APPROACH_PAUSE_S + TYPED_AT_S)) / 60))
        chat_lines = [(accepted + timedelta(seconds=50), "rider", rng.choice(PICKUP_LINES).format(spot=PICKUP_SPOT.get(spec["pair"][0], "at the main entrance"), outfit=rng.choice(OUTFITS))),
                      (accepted + timedelta(seconds=APPROACH_PAUSE_S + TYPED_AT_S), "driver", rng.choice(ARRIVING_LINES).format(n=n, car=rng.choice(CARS)))]
        statement = "The driver was speeding and braking hard the whole way, overtaking on the shoulder. I was scared and felt unsafe."
        dstmt = "I drove normally. The rider was on the phone the whole trip and never complained to me."
        if spec.get("statement_threat"):
            dstmt = "The rider is stupid and was on the phone the whole trip. I drove normally."
    else:  # none
        chat_lines = []
        statement = "The driver kept making comments about my body and asked for my number. I felt harassed and unsafe."
        dstmt = "I made small talk. Nothing inappropriate happened."
    fare = metered_fare(slice_gps(gps, iso(pickup_at), iso(dropoff_at)), rates, fold_waiting=True) if service == "RydeTAXI" else fixed_fare(route, rates)
    bands = gps_bands(route, [], gps, accepted - timedelta(minutes=5), dropoff_at + timedelta(minutes=5), max_n=2)
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


# ----------------------------------------------------------------------------------------------- surge (fare) cases

# what the in-app notice states (SURGE-1 needs all three) and when / how it went, by the scenario's `notice`
NOTICE = {               # what the notice states; a label for the reference (the court reads the text), never written to the case file
    "none": None, "missing": None,
    "full": {"multiplier": True, "revised_fare": True, "cancel_option": True},
    "no_cancel": {"multiplier": True, "revised_fare": True, "cancel_option": False},
    "no_fare": {"multiplier": True, "revised_fare": False, "cancel_option": True},
    "no_multiplier": {"multiplier": False, "revised_fare": True, "cancel_option": True},
    "cancel_fee": {"multiplier": True, "revised_fare": True, "cancel_option": False},
    "full_timed": {"multiplier": True, "revised_fare": True, "cancel_option": True},
    "full_at_pickup": {"multiplier": True, "revised_fare": True, "cancel_option": True},
    "paren": {"multiplier": True, "revised_fare": True, "cancel_option": True},
    "window_closed": {"multiplier": True, "revised_fare": True, "cancel_option": False},     # the free-cancel window it names had closed
    "fare_unchanged": {"multiplier": True, "revised_fare": False, "cancel_option": True},    # "your fare stays at the quote": no revised fare
    "after_pickup": {"multiplier": True, "revised_fare": True, "cancel_option": True},
    "sms": {"multiplier": True, "revised_fare": True, "cancel_option": True},
}
NOTICE_TEXT = {          # the in-app notice the rider saw, verbatim
    "full": "Fares are {m:.1f}× higher right now. Your new estimated fare is ${fare:.2f}. You can cancel for free.",
    "after_pickup": "Fares are {m:.1f}× higher right now. Your new estimated fare is ${fare:.2f}. You can cancel for free.",
    "sms": "Ryde: fares are {m:.1f}× higher right now. Your new estimated fare is ${fare:.2f}. You can cancel for free.",
    "no_cancel": "Demand is high near you, so fares are now {m:.1f}× the usual rate. Your new estimated fare is ${fare:.2f}.",
    "no_fare": "Fares are {m:.1f}× higher right now. You can cancel for free.",
    "no_multiplier": "Prices are higher than usual right now. Your new estimated fare is ${fare:.2f}. You can cancel this booking at no charge.",
    "cancel_fee": "Surge pricing of {m:.1f}× now applies to your trip. New estimated fare: ${fare:.2f}. Cancellation fees may apply.",
    "full_timed": "Fares are {m:.1f}× higher right now. New estimated fare ${fare:.2f}. You can cancel free of charge within the next 2 minutes.",
    "full_at_pickup": "Fares are {m:.1f}× higher right now. Your new estimated fare is ${fare:.2f}. You can cancel for free.",
    "paren": "Fares are higher than usual right now ({m:.1f}× surge). New estimate ${fare:.2f}. Cancel free anytime.",
}
NOTICE_AHEAD_S = 25          # the platform pushes the notice this long after the surge window opens


def surge_log(spec, accepted: datetime, pickup_at: datetime, revised_fare: float) -> dict:
    """The official surge_pricing_log (DISP-003) of the scenario, with the notice's own words."""
    m0, m1, notice = spec["m0"], spec["m1"], spec["notice"]
    activated = accepted + timedelta(seconds=60)
    log = {"quote_time_surge": m0, "trip_start_surge": m1, "surge_activated_at": iso(activated) if m1 != m0 else None,
           "rider_notified": False, "notification_method": None, "notification_timestamp": None, "notification_text": None,
           "reason": ("surge_window_activated_between_quote_and_pickup" if m1 > m0 else "surge_multiplier_changed_between_quote_and_pickup" if m1 < m0 else None)}
    if m1 > m0 and notice == "missing":
        log["rider_notified"] = None                  # the platform log does not say (TH-4)
    elif m1 > m0 and NOTICE[notice]:
        at = (pickup_at + timedelta(seconds=150) if notice == "after_pickup" else pickup_at - timedelta(seconds=20) if notice == "full_at_pickup"
              else activated + timedelta(seconds=NOTICE_AHEAD_S))
        log.update({"rider_notified": True, "notification_method": "sms" if notice == "sms" else "in_app", "notification_timestamp": iso(at),
                    "notification_text": NOTICE_TEXT[notice].format(m=m1, fare=revised_fare)})
    return log


def build_surge(spec, rates, rp, idx, rng, grng):
    """A private-hire (RydeX) trip, distance-based under FARE-0, charged at the trip-start multiplier m1 after a quote at m0
    priced on the route estimate (SURGE-1..3). The actual trip differs from the estimate (time, a little distance), and
    with `loops` (a rider-named stop) it also grew: the part of the fare above the quote that is not surge is not refunded."""
    m0, m1 = spec["m0"], spec["m1"]
    if spec["loops"]:
        case, meta = build_route(dict(spec, kind="route_deviation"), rates, rp, idx, rng, grng)
        case["dispute"]["type"] = "fare_dispute"
        t = case["trip"]
        pickup_at, dropoff_at = datetime.fromisoformat(t["pickup_at"]), datetime.fromisoformat(t["dropoff_at"])
        accepted = datetime.fromisoformat(t["accepted_at"])
    else:
        P, D = LOC[spec["pair"][0]], LOC[spec["pair"][1]]
        route = rp.route([P, D])
        opt = [tuple(p) for p in route["polyline"]]
        L = along_km(opt)[-1]
        pickup_at = spec["day"]
        night = is_night(pickup_at)
        approach_start, approach_s = approach_leg(rp, P, D, grng, night=night)
        accepted = pickup_at - timedelta(seconds=approach_s + 10)
        prof = profile_of(opt, [route], night)
        drive_s = r5(drive_time_s(prof))
        halts = [halt_at(opt, prof, surface_km(route, L * 0.6))] if spec.get("threat") else []
        pauses = [(h.start_s, h.duration_s) for h in halts]
        total_s = drive_s + sum(d for _, d in pauses)
        dropoff_at = pickup_at + timedelta(seconds=total_s)
        trip_gps = build_trajectory(opt, pickup_at, total_s, stops=halts, seed=spec["seed"], profile=prof)
        gps = approach_trace(rp, approach_start, P, accepted, pickup_at, wait_s=10, seed=spec["seed"], pauses=[(APPROACH_PAUSE_S, PAUSE_S)],
                             profile_of=lambda pl, lg: profile_of(pl, lg, night), jitter_m=STILL_JITTER_M) + trip_gps[1:]
        annotate_roads(gps, [rp.route([approach_start, P]), route])
        trip = trip_block(f"T-{2000 + idx}", spec["service"], place(spec["pair"][0]), place(spec["pair"][1]), route,
                          accepted - timedelta(seconds=35), accepted, gps, pickup_at - timedelta(seconds=10), pickup_at, dropoff_at)
        n = max(1, round((approach_s + 10 - (APPROACH_PAUSE_S + TYPED_AT_S)) / 60))
        chat_lines = [(accepted + timedelta(seconds=50), "rider", rng.choice(PICKUP_LINES).format(spot=PICKUP_SPOT.get(spec["pair"][0], "at the main entrance"), outfit=rng.choice(OUTFITS))),
                      (accepted + timedelta(seconds=APPROACH_PAUSE_S + TYPED_AT_S), "driver", rng.choice(ARRIVING_LINES).format(n=n, car=rng.choice(CARS)))]
        if pauses:
            halt = pickup_at + timedelta(seconds=pauses[0][0])
            chat_lines += [(halt - timedelta(seconds=40), "rider", "Why am I paying surge on this trip? I want to know before we arrive."),
                           (halt + timedelta(seconds=TYPED_AT_S), "driver", "Not my problem. Pay up or I will come and find you.")]
        chat_lines.sort(key=lambda x: x[0])
        for t_, who, _ in chat_lines:
            if who == "driver" and t_ > pickup_at:
                at = min(gps, key=lambda p: abs((datetime.fromisoformat(p["ts"]) - t_).total_seconds()))
                assert at["speed_kmh"] < 5, f"{spec['name']}: driver line at {t_:%H:%M:%S} while moving"
        r_prof = (rng.randint(120, 1500), round(rng.uniform(4.5, 5.0), 1), rng.randint(0, 2), 0, 0, 0)
        d_dis = rng.randint(0, 2)
        d_prof = (rng.randint(300, 2400), round(rng.uniform(4.5, 4.95), 2), rng.randint(300, 1300), d_dis + rng.randint(0, 1), d_dis, 0, 0)
        case = {
            "case_id": spec["case_id"],
            "dispute": {"type": "fare_dispute", "filed_by": "rider", "filed_at": iso(dropoff_at + timedelta(minutes=rng.randint(10, 60))), "statement": ""},
            "trip": trip, "route": route, "gps": gps,
            "traffic": {"speed_bands": gps_bands(route, [], gps, accepted - timedelta(minutes=5), dropoff_at + timedelta(minutes=5), max_n=2), "incidents": []},
            "weather": WEATHER[spec["weather"]],
            "fare": {},
            "chat": msgs(*chat_lines),
            "driver_statement": "",
            "profiles": profiles(r_prof, d_prof),
        }
        meta = {}
    quote_sub = estimate_subtotal(case["route"], rates)            # the upfront quote prices the booked trip: the route's estimate
    fare = metered_fare(slice_gps(case["gps"], case["trip"]["pickup_at"], case["trip"]["dropoff_at"]), rates, m1, fold_waiting=True)
    s1 = surgeable_subtotal(fare)
    quoted_total, detail = surge_breakdown(fare, quote_sub, m0, rates)
    fare["quoted_total"] = quoted_total
    case["fare"], case["fare_detail"] = fare, detail
    case["surge"] = surge_log(spec, accepted, pickup_at, r2(r2(quote_sub * m1) + platform_fee(r2(quote_sub * m1), rates)))
    q, a = quoted_total, fare["total"]
    diff = r2(a - q)
    head = f"The app quoted ${q:.2f} when I booked, but I was charged ${a:.2f}."
    tail = f" I want the ${diff:.2f} difference refunded."
    notice = spec["notice"]
    if spec.get("complaint_safety"):
        statement = (f"I was charged a {m1:.1f}x surge on a trip the app quoted at ${q:.2f}. When I asked the driver about it, he said he knows where I "
                     "live and I had better just pay. I felt unsafe for the rest of the ride.")
    elif spec.get("complaint") == "late_popup":
        statement = (f"The app quoted ${q:.2f} and I was charged ${a:.2f}. The notice only popped up as I was getting into the car, I had no real "
                     f"chance to cancel. I want the ${diff:.2f} difference refunded.")
    elif spec.get("complaint") == "misleading_estimate":
        statement = (f"The app quoted ${q:.2f} when I booked and I was charged ${a:.2f}. The notice quoted a fare that wasn't even what I was charged, "
                     "so it was misleading. Refund the surge.")
    elif spec.get("complaint") == "denies_notice":
        statement = f"The app quoted ${q:.2f}, but I was charged ${a:.2f}. I never received any notice about surge pricing. I want the ${diff:.2f} difference refunded."
    elif spec.get("complaint") == "whole_fare":
        statement = (f"The app quoted ${q:.2f}; the surge went from {m0:g}x to {m1:g}x without any warning. The surge should come off my whole "
                     f"${a:.2f} fare, so I want ${r2(a * (m1 - m0) / m1):.2f} back.")
    elif m1 < m0:
        statement = f"When I booked, the app showed {m0:g}x surge. It had dropped by the time we left, but I was still charged {m1:g}x surge. I want all the surge refunded."
    elif m1 == m0:
        statement = f"I was charged a {m1:g}x surge on this trip. Surge on a ride like this is unfair; please refund it."
    else:
        statement = head + {"none": " Nobody told me the price had gone up.", "missing": " I never saw anything about the price going up.",
                            "full": " I booked at the quoted price and expect to pay it.",
                            "no_cancel": " A message said the price had gone up, but nothing said I could still cancel for free, so I thought I was stuck with it.",
                            "no_multiplier": " The app only said prices were higher than usual; it never said by how much the surge had gone up.",
                            "cancel_fee": " The app said cancellation fees may apply, so I did not dare cancel.",
                            "full_timed": " The message said I could only cancel free for two minutes, so I felt rushed into riding.",
                            "paren": " The message only said fares were higher than usual; I never agreed to a surge.",
                            "no_fare": " A message said surge had gone up, but it never said what I would now pay.",
                            "after_pickup": " The message about the higher price only came after I was already in the car.",
                            "sms": " I only got an SMS about a higher price; there was nothing in the app."}[notice] + tail
    stop_place = meta.get("stop_place")
    if stop_place:
        statement = head + " Nobody told me the price had gone up." + tail
    dstmt = (spec.get("driver_text") if spec.get("driver_text") else
             f"The rider asked me to stop at {stop_place} and I waited while the rider went in. The price is set by the app, not by me." if stop_place else
             "The rider argued about the price the whole way. I told the rider to take it up with the app." if spec.get("threat") else
             rng.choice(["I don't set the price; the app does. I drove the route the app showed.",
                         "The fare is what the app calculated. I followed the app's route the whole way.",
                         "Pricing is the app's, not mine. I picked up on time and drove the app route."]))
    case["dispute"]["statement"], case["driver_statement"] = statement, dstmt
    accounts(case, spec)
    meta = dict(meta, quote_subtotal=quote_sub, surgeable_subtotal=s1)
    return case, meta


# ----------------------------------------------------------------------------------------------- reference answer and engine gate

COND_SKIP = ("seed", "day", "case_id", "name", "kind", "hard", "pair", "_entry", "expect", "reused_from", "geometry_from", "ns", "port", "labels", "escalate_ok")


def port_overlay(case: dict, text: dict) -> dict:
    """Lay a validated case's texts over its base record, verbatim: the complaint, the chat, the driver's statement, and
    where given the trip id, the surge notice's words and the profiles. Nothing measured changes."""
    out = json.loads(json.dumps(case))
    out["dispute"] = dict(text["dispute"])
    out["chat"] = [dict(m) for m in text["chat"]]
    out["driver_statement"] = text["driver_statement"]
    if "trip_id" in text:
        out["trip"]["trip_id"] = text["trip_id"]
    if "notification_text" in text:
        out["surge"]["notification_text"] = text["notification_text"]
    if "profiles" in text:
        out["profiles"] = json.loads(json.dumps(text["profiles"]))
    return out


def readings_of(spec: dict) -> list[dict]:
    """The interpretive elements of a case: what a reader of the record must decide, and the scenario's answer (the label
    reference.py uses for that slot; code decides everything else)."""
    out, k = [], spec["kind"]
    if spec.get("threat") in ("driver",) or spec.get("chat") in ("threat", "driver_threat", "rider_threat") or spec.get("complaint_safety") or k == "safety":
        out.append({"element": "SAFE-1 safety screen", "decide": "Does any message, statement or the complaint allege a safety matter?", "label": "yes"})
    elif spec.get("threat") == "impatient" or spec.get("chat") == "impatient":
        out.append({"element": "SAFE-1 safety screen", "decide": "Is the impatient or frustrated line a safety matter?", "label": "no"})
    if k == "route_deviation" and spec["consent"] != "none":
        out.append({"element": "RD-5 rider's agreement", "decide": "Do the rider's words before the segment agree to this route, and to which road "
                    "(the code then checks that road against the GPS road names)?", "label": spec["consent"]})
    if k in ("route_deviation", "fare_dispute") and spec.get("stop", "none") != "none":
        out.append({"element": "RD-3 rider-requested stop", "decide": "Did the rider name the place the car stopped at?", "label": spec["stop"]})
    if k == "fare_dispute" and NOTICE.get(spec["notice"]) and spec["notice"] not in ("after_pickup", "sms"):
        out.append({"element": "SURGE-1 notice content", "decide": "Does the notice text state the new multiplier, the revised fare and a free-cancel option?",
                    "label": NOTICE[spec["notice"]]})
    if k == "no_show" and spec.get("reason_reading"):
        out.append({"element": "NS-0 cancellation reason", "decide": "From the driver's own words, did he cancel because the rider did not come, or for his own reason?",
                    "label": spec["reason_reading"]})
    return out


def conditions(spec: dict) -> dict:
    return {k: v for k, v in spec.items() if k not in COND_SKIP}


def engine_answer(case_dict: dict, spec: dict, ref: dict) -> tuple[dict, list[str]]:
    """The engine's reading of the same record: its certificate, with the interpretive route slots (did the rider's words
    agree to this segment) filled from the reference's findings, the safety screen from the scenario's line, and the TH
    gate. Returns ({ruling, amount, flag_account, goodwill_credit}, certificate lines)."""
    from core.facts.tools import build_fact_table
    from core.policy_engine import GOODWILL, evaluate, expected_amount, threshold_check
    from core.schemas import Case
    case = Case.model_validate(case_dict)
    cert = evaluate(case, build_fact_table(case))
    lines = cert.lines()
    esc = {"ruling": "escalate", "amount": None, "flag_account": False, "goodwill_credit": None}
    if spec["kind"] == "safety" or spec.get("threat") == "driver" or spec.get("chat") == "threat" or spec.get("complaint_safety") or cert.insufficient:
        return esc, lines         # the judge's safety screen reads the scenario's line / complaint
    if spec["kind"] == "route_deviation" and cert.segments:
        found = ref.get("_findings") or []
        if len(found) != len(cert.segments):
            raise contract.ContractError(f"engine sees {len(cert.segments)} segment(s), the reference {len(found)}")
        fill = {fid: (f == "exempt") for (fid, sg), f in zip(cert.segments.items(), found) if sg["exempt"] is None and f != "undetermined"}
        if any(sg["exempt"] is None and f == "undetermined" for sg, f in zip(cert.segments.values(), found)):
            return esc, lines
        amount = expected_amount(cert, fill) or None
        out = {"ruling": "refund_partial" if amount else "no_action", "amount": amount,
               "flag_account": bool(amount) and bool(cert.flag_required or cert.flag_conditional), "goodwill_credit": None}
    else:
        allowed = [r for r in cert.allowed if r != "escalate"]
        if len(allowed) == 1:
            ruling = allowed[0]
        elif spec["kind"] == "fare_dispute":           # the court reads the notice text: the scenario's label is its reading
            lab = NOTICE.get(spec["notice"]) or {}
            ruling = "no_action" if lab and all(lab.values()) else "refund_partial"
        else:                                          # the court reads the driver's reason for cancelling
            ruling = "refund_full" if spec.get("reason_reading") == "own_reason" else "no_action"
        amount = cert.amount if ruling.startswith("refund") else None
        flag = cert.flag_required if cert.flag_required is not None else \
            (ruling == "no_action" and any(p.clause == "NS-9" and p.status == "pass" for p in cert.predicates))
        out = {"ruling": ruling, "amount": amount, "flag_account": bool(flag), "goodwill_credit": GOODWILL if cert.goodwill_required else None}
    ok, _ = threshold_check(cert, out["amount"])
    return (out if ok else esc), lines


def disagreement(eng: dict, ref: dict) -> list[str]:
    same = (eng["ruling"] == ref["ruling"] and bool(eng["flag_account"]) == bool(ref["flag_account"])
            and abs((eng["amount"] or 0) - (ref["amount"] or 0)) <= 0.015
            and (eng.get("goodwill_credit") or 0) == (ref.get("goodwill_credit") or 0))
    return [] if same else [f"engine and independent derivation disagree: engine {eng['ruling']} {eng['amount']} flag={eng['flag_account']} goodwill={eng.get('goodwill_credit')}, "
                            f"reference.py {ref['ruling']} {ref['amount']} flag={ref['flag_account']} goodwill={ref.get('goodwill_credit')}"]


# ----------------------------------------------------------------------------------------------- main

# The reference answers follow policy/policy.md as written on this date. Bump when a rule changes and record every changed
# answer in data/bench/REFERENCE_CHANGES.md (what the gap is and why it moves the outcome).
REFERENCE_VERSION = ("2026-10-13 v5b (records: arrival = confirmation, readings as text, road-class speeds; rules as v5) v5: the organisers' policy v2.1 (policy.md v3) - every fare distance-based; RD-1 tolerance after exemptions; "
                     "a traffic reason decides the violation / reminder, not the amount; named-road consent checked against the GPS road names; "
                     "NS-1 5-min wait from the later of arrival and scheduled time, message AND call; NS-8 goodwill credit; NS-9 flag; "
                     "SURGE-1..3; TH-1 bands, TH-3 code confidence, TH-4 missing records")


def validate_bench(case_dict: dict, spec: dict, rates, clauses, expected: dict | None = None) -> list[str]:
    if spec.get("gps_tail_cut_s"):
        return []        # the trace deliberately ends early; the format checks assume a complete trip
    errs = validate.check_case(case_dict, rates, clauses, expected)
    if spec.get("policy"):
        errs = [e for e in errs if "policy_params" not in e and "cancellation fare" not in e]   # record-stated parameters (the organisers' format)
    if spec.get("gps_hole_s"):
        errs = [e for e in errs if "5 s grid" not in e]                                      # the hole IS the scenario
    if "recorded_by" in spec and spec["recorded_by"] is None:
        errs = [e for e in errs if "cancel fields" not in e]                                 # an unrecorded canceller IS the scenario
    if spec.get("stop") == "driver_errand":
        errs = [e for e in errs if "unexplained mid-trip stop" not in e]                     # the driver's own stop IS the scenario
    if spec["kind"] == "no_show" and (not spec.get("here", True) or spec["by"] == "driver_other"):
        errs = [e for e in errs if "without an 'I'm Here' tap" not in e]   # that IS the scenario (NS-1 (i) / NS-3)
    if spec["kind"] == "route_deviation" and not spec["loops"]:
        errs = [e for e in errs if "no off-route segment" not in e]        # deliberate hard negative (RD-1 fails)
    if spec.get("min_extra_km"):
        errs = [e for e in errs if "too close to the 0.2 km noise floor" not in e]   # a short detour inside the RD-1 tolerance IS the scenario
    return errs


def scenario_sets() -> dict:
    """The sets the generator writes: the benchmark (B-) and the candidates under trial (K-, `--candidates`), each with its
    own directory, scenario list and first day."""
    return {"bench": {"prefix": "B-", "dir": BENCH_DIR, "scenarios": SCENARIOS, "day0": datetime(2026, 9, 1, 8, 0, 0, tzinfo=SGT)},
            "candidates": {"prefix": "K-", "dir": os.path.join(BENCH_DIR, "candidates"), "scenarios": CANDIDATES,
                           "day0": datetime(2026, 9, 27, 8, 0, 0, tzinfo=SGT)}}


def dated(i: int, day0: datetime | None = None) -> datetime:
    """The pickup / acceptance time of the i-th scenario: two cases a day from the set's first day (the benchmark:
    2026-09-01), every case dated before the set was built. Fixed by position, so a case keeps its date for ever."""
    day0 = day0 or datetime(2026, 9, 1, 8, 0, 0, tzinfo=SGT)
    hours = [8, 9, 12, 14, 17, 18, 21, 22]
    return (day0 + timedelta(days=i // 2)).replace(hour=hours[i % len(hours)], minute=(i * 7) % 60, second=0)


def build_one(spec_in: dict, i: int, rates, clauses, rp, entry: dict | None = None, which: str = "bench") -> dict:
    """Build the i-th scenario in memory and run every gate. Returns {"case", "expected", "entry"}; raises ContractError
    (record does not tell its story, the engine disagrees with the reference, `expect` broken, format check failed) or
    the builder's own error. Nothing is written here."""
    spec = dict(spec_in)
    st = scenario_sets()[which]
    spec["case_id"] = f"{st['prefix']}{i:04d}"
    port = spec.get("port")
    builders = {"route_deviation": build_route, "no_show": build_noshow, "safety": build_safety, "fare_dispute": build_surge}
    if port:
        # the base scenario exactly as it is, at its own position: its trip, GPS, fare and date; then the validated texts
        base = dict(next(x for x in SCENARIOS + PORT_BASES if x["name"] == port["base"]))
        ident = identity(base.get("ns", "bench"), port["base"])
        base.update({"case_id": spec["case_id"], "seed": ident["noise"], "day": dated(port["base_i"], scenario_sets()["bench"]["day0"]), "_entry": entry})
        case, meta = builders[base["kind"]](base, rates, rp, port["base_i"], ident["text"], ident["geo"])
        case = port_overlay(case, PORT_TEXT[port["text"]])
        spec = {**base, **spec["labels"], "name": spec["name"], "port": port, "labels": spec["labels"], "hard": spec["hard"], "expect": spec["expect"],
                "escalate_ok": spec.get("escalate_ok"), "reused_from": spec.get("reused_from"), "ported": True}
    else:
        ident = identity(spec.get("ns", "bench"), spec["name"])
        spec["seed"] = ident["noise"]
        spec["day"] = dated(i, st["day0"])
        spec["_entry"] = entry         # the published entry: its pinned loop plan is reused, so a rebuild never searches
        case, meta = builders[spec["kind"]](spec, rates, rp, i, ident["text"], ident["geo"])
    cond = conditions(spec)
    ref = reference.derive_reference(case, cond, spec["kind"])
    expected = {k: v for k, v in ref.items() if not k.startswith("_")}
    if which == "candidates" or spec.get("escalate_ok"):
        expected["escalate_ok"] = True       # a candidate turns on a reading: handing it to a person also counts as right
    broken = contract.check(case, contract.contract_for(spec, LOC))
    cert = []
    if not SKIP_ENGINE:
        eng, cert = engine_answer(case, spec, ref)
        broken += disagreement(eng, expected)
    broken += contract.check_expect(spec.get("expect"), expected) if spec.get("expect") else contract.check_label(spec["hard"], expected)
    broken += validate_bench(case, spec, rates, clauses, expected)
    broken += lint.lint_case(case)
    if broken:
        raise contract.ContractError(f"{spec['case_id']} {spec['name']} refused: " + " | ".join(broken))
    entry = {"case_id": spec["case_id"], "name": spec["name"], "type": spec["kind"], "pair": list(spec["pair"]),
             "reused_from": spec.get("reused_from", "new"), "conditions": cond, "truth": expected, "hard": spec["hard"], "readings": readings_of(spec),
             "segments": meta.get("segments", []), "stretch_roads": meta.get("stretch_roads", []),
             "certificate": cert, "identity": IDENTITY_VERSION, "plan": meta.get("plan", [])}
    if spec.get("ns"):
        entry["identity_ns"] = spec["ns"]
    if spec.get("geometry_from"):
        entry["geometry_from"] = spec["geometry_from"]
    if spec.get("port"):
        entry["port"] = spec["port"]
    return {"case": case, "expected": expected, "entry": entry}


def publish(bundles: list[dict], which: str = "bench") -> None:
    """Write the built cases: case and expected files first, the manifest last, merged by case id with what is already
    there; manifest entries that no longer match the scenario list are dropped."""
    st = scenario_sets()[which]
    cases_dir, expected_dir = os.path.join(st["dir"], "cases"), os.path.join(st["dir"], "expected")
    for d in (cases_dir, expected_dir):
        os.makedirs(d, exist_ok=True)
    mpath = os.path.join(st["dir"], "manifest.json")
    old = json.load(open(mpath)) if os.path.exists(mpath) else {"cases": []}
    names = {f"{st['prefix']}{i:04d}": sp["name"] for i, sp in enumerate(st["scenarios"], 1)}
    by_id = {c["case_id"]: c for c in old["cases"] if names.get(c["case_id"]) == c["name"]}
    for b in bundles:
        cid = b["entry"]["case_id"]
        with open(os.path.join(expected_dir, f"{cid}.json"), "w") as f:
            json.dump(b["expected"], f, indent=2, ensure_ascii=False)
            f.write("\n")
        dump(b["case"], os.path.join(cases_dir, f"{cid}.json"))
        by_id[cid] = b["entry"]
    with open(mpath, "w") as f:
        json.dump({"seed": SEED, "generated_by": "data/synth/scenarios.py" + (" --candidates (readings under trial; not part of the 50)" if which == "candidates" else ""),
                   "reference_version": REFERENCE_VERSION,
                   "cases": [by_id[k] for k in sorted(by_id)]}, f, indent=1, ensure_ascii=False)


def pinned_entries() -> dict:
    """Published manifest entries by scenario name (their pinned loop plans), from every set (a candidate may borrow a
    benchmark case's geometry with `geometry_from`)."""
    out = {}
    for st in scenario_sets().values():
        mpath = os.path.join(st["dir"], "manifest.json")
        if os.path.exists(mpath):
            for c in json.load(open(mpath))["cases"]:
                out.setdefault(c["name"], c)
    return out


def main(names: list[str] | None = None, limit: int | None = None, replan: bool = False, which: str = "bench") -> int:
    """Build every scenario of a set (or only `names`), then publish the ones that passed. A scenario that fails leaves its
    committed files exactly as they were; the run prints why and exits 1."""
    st = scenario_sets()[which]
    seen = [x["name"] for x in st["scenarios"]]
    assert len(seen) == len(set(seen)), "duplicate scenario names"
    if names:
        unknown = [n for n in names if n not in seen]
        assert not unknown, f"unknown scenario(s): {unknown}"
    todo = [(i, sp) for i, sp in enumerate(st["scenarios"], 1) if (not names or sp["name"] in names) and (not limit or i <= limit)]
    rates, clauses, rp = load_rates(), validate.policy_clauses(), routes()
    published = pinned_entries()
    built, failures = [], []
    if SKIP_ENGINE:
        print("SYNTH_SKIP_ENGINE_CHECK=1: publishing on the reference derivation alone; the engine-agreement gate is not run")
    for i, spec in todo:
        try:
            entry = None if replan else (published.get(spec["name"]) or published.get(spec.get("geometry_from"))
                                         or published.get((spec.get("port") or {}).get("base")))
            b = build_one(spec, i, rates, clauses, rp, entry, which)
            built.append(b)
            e = b["entry"]
            seg = "".join(f" seg +{s['extra_km']:.2f}km" for s in e["segments"])
            gw = f" goodwill={e['truth']['goodwill_credit']}" if e["truth"].get("goodwill_credit") else ""
            print(f"{e['case_id']} {e['name']:36} {e['truth']['ruling']:14} {e['truth']['amount'] or '':>6} flag={e['truth']['flag_account']!s:5}{gw}{seg} ok")
        except Exception as e:  # noqa: BLE001
            failures.append((f"{st['prefix']}{i:04d}", spec["name"], f"{type(e).__name__}: {e}"))
            print(f"{st['prefix']}{i:04d} {spec['name']:36} BUILD FAILED {type(e).__name__}: {e}")
    if built:
        publish(built, which)
    by_type = {}
    for b in built:
        by_type[b["entry"]["type"]] = by_type.get(b["entry"]["type"], 0) + 1
    print(f"\n{len(built)} case(s) written: {by_type}; {len(failures)} failure(s) (their committed files are untouched)")
    for cid, name, err in failures:
        print(f"  {cid} {name}: {err}")
    if OFFLINE_SKIPS:
        print("offline run: loop candidates skipped because their OneMap leg is not cached (a run with a token may choose one of them "
              "and produce different geometry): " + ", ".join(f"{k} x{v}" for k, v in sorted(OFFLINE_SKIPS.items())))
    return 1 if failures else 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    sel = None
    if "--case" in argv:
        k = argv.index("--case")
        sel = argv[k + 1].split(",")
        del argv[k:k + 2]
    rest = [a for a in argv if a not in ("--replan", "--candidates")]
    sys.exit(main(sel, limit=int(rest[0]) if rest else None, replan="--replan" in sys.argv,
                  which="candidates" if "--candidates" in sys.argv else "bench"))
