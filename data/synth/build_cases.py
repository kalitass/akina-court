#!/usr/bin/env python3
"""Generate data/cases/C-0001..C-0006.json from the six spec 1.7 scripts on real OneMap routes.

    python3 data/synth/build_cases.py        # legs already in data/synth/onemap_cache.json need no token
    ONEMAP_TOKEN=... python3 data/synth/build_cases.py   # (or ONEMAP_EMAIL/ONEMAP_PASSWORD) to fetch new legs

Timeline, chat, profiles and statements are hand-written per script; routes come from OneMap, GPS, arrival
times and fares are computed. Every number that a fact tool will later compute is derived from the trace here too.

Detour cases share geometry with the optimal route: the driven polyline *is* the optimal polyline except for the
stretches replaced by a detour (`detour_trace`): OneMap routes optimal-vertex -> via points -> optimal-vertex on real
roads. The extra km of each detour is whatever the road network says; `data/expected/` amounts are km x rate.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fare import cancellation_fare, distance_km, fixed_fare, load_rates, metered_fare, slice_gps, stationary_windows  # noqa: E402
from route_provider import M_PER_DEG_LAT, OneMapRouteProvider, haversine_m, m_per_deg_lon, road_geometry  # noqa: E402
from trajectory import Congestion, Stop, build_trajectory  # noqa: E402

SGT = timezone(timedelta(hours=8))
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cases")
ARRIVAL_RADIUS_M = 200  # spec 1.3: driver_arrived_at = first sample within 200 m of pickup

# Thresholds mirrored from core/facts/tools.py so the synthetic loops are shaped for the fact tool.
OFF_ROUTE_M = 200       # a GPS point farther than this from the optimal polyline is off-route
DETOUR_MERGE_S = 120    # off-route runs separated by a shorter on-route gap are one detour
DETOUR_MIN_KM = 0.2     # detours adding less than this are polyline-matching noise
ROAD_NEAR_M = 300       # a speed-band road "is on" a trace / route if its geometry (or point) is within this

LOC = {  # real Singapore places, coordinates from common knowledge (~50 m)
    "Orchard Road": (1.30229, 103.83682),               # a OneMap vertex on Orchard Road itself (past Bideford Rd), not inside a block
    "Marina Bay Sands": (1.2839, 103.8607),
    "Bugis Junction": (1.2994, 103.8555),
    "Tanjong Pagar Centre": (1.2766, 103.8459),
    "Clarke Quay": (1.2906, 103.8465),
    "Bedok Mall": (1.3249, 103.9296),
    "7-Eleven Beach Road": (1.3025, 103.8637),         # the far store the C-0001 driver picked (Golden Mile stretch)
    "Stamford Road roadside bay (SMU)": (1.2958, 103.8495),   # where the C-0004 driver parked
}
# LTA DataMall v4 RoadCategory codes: 1 Expressway, 2 Major Arterial, 3 Arterial, 4 Minor Arterial,
# 5 Small roads, 6 Slip roads, 7 No category. link_id is a synthetic stable id (real LinkIDs are numeric).
# (lat, lon) is a representative point used only when no route in the case carries the road's geometry.
ROADS = {  # name: (lat, lon, road_category, link_id)
    "ORCHARD ROAD": (1.3040, 103.8335, "2", "SYN-0001"),
    "SCOTTS ROAD": (1.3070, 103.8323, "3", "SYN-0002"),
    "BRAS BASAH ROAD": (1.2960, 103.8510, "2", "SYN-0003"),
    "BAYFRONT AVENUE": (1.2870, 103.8608, "3", "SYN-0004"),
    "VICTORIA STREET": (1.2985, 103.8545, "2", "SYN-0005"),
    "NORTH BRIDGE ROAD": (1.2960, 103.8540, "2", "SYN-0006"),
    "CENTRAL EXPRESSWAY": (1.3150, 103.8480, "1", "SYN-0007"),
    "EAST COAST PARKWAY": (1.3000, 103.8900, "1", "SYN-0008"),
    "PAN ISLAND EXPRESSWAY": (1.3300, 103.8800, "1", "SYN-0009"),
    "PAYA LEBAR ROAD": (1.3180, 103.8930, "2", "SYN-0010"),
    "ANSON ROAD": (1.2764, 103.8469, "3", "SYN-0011"),
    "MARINA COASTAL EXPRESSWAY": (1.2740, 103.8600, "1", "SYN-0012"),
    "KALLANG PAYA LEBAR EXPRESSWAY": (1.3050, 103.8755, "1", "SYN-0013"),
    "BEACH ROAD": (1.3020, 103.8630, "3", "SYN-0014"),
}
SPEED_BANDS = {1: (0, 9), 2: (10, 19), 3: (20, 29), 4: (30, 39), 5: (40, 49), 6: (50, 59), 7: (60, 69), 8: (70, None)}
MOVING_KMH = 5.0        # samples slower than this are parked / creeping and do not describe the road's speed
EXPRESSWAY_KMH = 65.0   # cruising speed injected on expressway legs -> speed band 7 (60-69), review item 4


def T(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SGT)


def secs(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds())


def offset(p, bearing_deg: float, dist_m: float):
    b = math.radians(bearing_deg)
    return (round(p[0] + dist_m * math.cos(b) / M_PER_DEG_LAT, 6),
            round(p[1] + dist_m * math.sin(b) / m_per_deg_lon(p[0]), 6))


def routes(seed: int = 0):
    return OneMapRouteProvider()


# ----------------------------------------------------------------------------------------------- geometry

def along_km(poly):
    cum = [0.0]
    for a, b in zip(poly, poly[1:]):
        cum.append(cum[-1] + haversine_m(a, b) / 1000)
    return cum


def project(lat, lon, poly):
    """(distance m, along-track km) of the nearest point of `poly` — same maths as core/facts/tools._project."""
    kx, ky = 111_320 * math.cos(math.radians(lat)), 110_540
    best_d, best_along, cum = math.inf, 0.0, 0.0
    for (alat, alon), (blat, blon) in zip(poly, poly[1:]):
        ax, ay, bx, by = (alon - lon) * kx, (alat - lat) * ky, (blon - lon) * kx, (blat - lat) * ky
        vx, vy = bx - ax, by - ay
        seg = math.hypot(vx, vy)
        t = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * vx + ay * vy) / (seg * seg)))
        d = math.hypot(ax + t * vx, ay + t * vy)
        if d < best_d:
            best_d, best_along = d, cum + t * seg / 1000
        cum += seg / 1000
    return best_d, best_along


def measure_detours(gps, poly):
    """Off-route segments of a trace against the optimal polyline, the way core/facts/tools._detours sees them:
    [{"start", "end", "driven_km", "route_km", "extra_km", "max_off_route_m"}]."""
    pts = [(p["lat"], p["lon"]) for p in gps]
    tss = [datetime.fromisoformat(p["ts"]) for p in gps]
    proj = [project(la, lo, poly) for la, lo in pts]
    runs, i, n = [], 0, len(pts)
    while i < n:
        if proj[i][0] <= OFF_ROUTE_M:
            i += 1
            continue
        j = i
        while j < n and proj[j][0] > OFF_ROUTE_M:
            j += 1
        if runs and (tss[i] - tss[runs[-1][1] - 1]).total_seconds() <= DETOUR_MERGE_S:
            runs[-1] = (runs[-1][0], j)
        else:
            runs.append((i, j))
        i = j
    out = []
    for i, j in runs:
        entry, exit_ = max(i - 1, 0), min(j, n - 1)
        driven = sum(haversine_m(a, b) for a, b in zip(pts[entry:exit_], pts[entry + 1:exit_ + 1])) / 1000
        skipped = abs(proj[exit_][1] - proj[entry][1])
        if driven - skipped < DETOUR_MIN_KM:
            continue
        out.append({"start": gps[entry]["ts"], "end": gps[exit_]["ts"], "driven_km": round(driven, 2),
                    "route_km": round(skipped, 2), "extra_km": round(driven - skipped, 2),
                    "max_off_route_m": round(max(proj[k][0] for k in range(i, j))), "_raw": driven - skipped})
    return out


def nearest_idx(poly, pt):
    return min(range(len(poly)), key=lambda k: haversine_m(poly[k], pt))


def compose(rp, opt, loops):
    """Optimal polyline with stretches replaced by real-road detours. loops: [{"leave", "via", "rejoin"}] where
    leave / rejoin are points on (or near) the optimal route and via the real places the driver went through.
    Returns (polyline, [(loop_start_km, loop_end_km) along the composed polyline], [leg route dicts])."""
    poly, spans, legs, i_prev = [], [], [], 0
    for lp in loops:
        i1, i2 = nearest_idx(opt, lp["leave"]), nearest_idx(opt, lp["rejoin"])
        assert i_prev <= i1 < i2, f"loop {lp} out of order on the optimal route ({i_prev}, {i1}, {i2})"
        leg = rp.route([opt[i1], *lp["via"], opt[i2]])
        legs.append(leg)
        seg = [tuple(p) for p in leg["polyline"]]
        poly.extend(opt[i_prev:i1])
        start_km = along_km(poly + [seg[0]])[-1] if poly else 0.0
        poly.extend(seg)
        spans.append((start_km, along_km(poly)[-1]))
        i_prev = i2 + 1
    poly.extend(opt[i_prev:])
    return [list(p) for p in poly], spans, legs


def detour_trace(rp, opt, loops, start, total_s, stops=(), zones=(), loop_zones=None, seed=0):
    """Trip trace over `opt` with real-road detour loops. Stops are snapped to the nearest vertex of the driven
    polyline. loop_zones = {loop_idx: (margin_km, kmh)} injects a cruising speed inside a loop (expressway legs).
    Returns (polyline, gps, measured detours as core/facts/tools sees them, leg route dicts)."""
    opt = [tuple(p) for p in opt]
    poly, spans, legs = compose(rp, opt, loops)
    snapped = [Stop(*poly[nearest_idx(poly, (st.lat, st.lon))], st.start_s, st.duration_s, st.jitter_m, st.anchor_s, st.away_from)
               for st in stops]
    cz = list(zones) + [Congestion(spans[k][0] + m, spans[k][1] - m, v) for k, (m, v) in (loop_zones or {}).items()]
    gps = build_trajectory(poly, start, total_s, stops=snapped, congestion=cz, seed=seed)
    found = measure_detours(gps, opt)
    if len(found) != len(loops):
        raise ValueError(f"expected {len(loops)} detour(s), fact-tool logic finds {len(found)}: {found}")
    for f in found:
        f.pop("_raw")
    return poly, gps, found, legs


def road_km(route, name, which="from"):
    """km along a route where road `name` starts ("from") or ends ("to")."""
    runs = [r for r in route["roads"] if r["name"] == name]
    m = min(r["from_m"] for r in runs) if which == "from" else max(r["to_m"] for r in runs)
    return m / 1000


# ----------------------------------------------------------------------------------------------- records

def approach_trace(rp, start_pt, pickup, accepted: datetime, pickup_at: datetime, wait_s: int, seed: int):
    """Driver drives to the pickup point, parks there `wait_s` seconds before the rider boards."""
    total = secs(accepted, pickup_at)
    poly = rp.route([start_pt, pickup])["polyline"]
    return build_trajectory(poly, accepted, total, stops=[Stop(*pickup, start_s=total - wait_s, duration_s=wait_s)], seed=seed)


def first_within(gps, pt, radius_m=ARRIVAL_RADIUS_M):
    return next((p["ts"] for p in gps if haversine_m((p["lat"], p["lon"]), pt) <= radius_m), None)


def min_dist(gps, pt):
    return min(gps, key=lambda p: haversine_m((p["lat"], p["lon"]), pt))


# ----------------------------------------------------------------------------------------------- records

def geometry_of(road, routes_, trim_start_m=0.0):
    """Polyline of `road` from the first route (optimal first, then driven legs) that carries it; None if none does.
    trim_start_m drops the first metres (a closed road's junction that the open road next to it shares)."""
    for r in routes_:
        if any(x["name"] == road for x in r.get("roads", [])):
            geom = road_geometry(r, road)
            if trim_start_m:
                cum, out = 0.0, []
                for a, b in zip(geom, geom[1:]):
                    cum += haversine_m(tuple(a), tuple(b))
                    if cum >= trim_start_m:
                        out.append(b)
                geom = out if len(out) >= 2 else geom[-2:]
            return geom
    return None


def near_road(p, road, geom):
    pts = geom or [ROADS[road][:2]]
    return min(haversine_m((p["lat"], p["lon"]), tuple(q)) for q in pts) <= ROAD_NEAR_M


def band(road, level, start: datetime, end: datetime, routes_=(), trim_start_m=0.0):
    """Hand-set speed band (roads on the optimal route that the driver did not actually drive)."""
    lat, lon, cat, link = ROADS[road]
    return {"link_id": link, "road_name": road, "road_category": cat, "speed_band": level,
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "geometry": geometry_of(road, routes_, trim_start_m)}


def band_from_gps(road, gps, start: datetime, end: datetime, routes_=()):
    """Speed band derived from the trace: median speed of the moving samples within ROAD_NEAR_M of the road's
    geometry during the window, mapped to the LTA band. Keeps traffic evidence consistent with the GPS (review 4)."""
    geom = geometry_of(road, routes_)
    near = [p["speed_kmh"] for p in gps if start.isoformat() <= p["ts"] <= end.isoformat()
            and p["speed_kmh"] >= MOVING_KMH and near_road(p, road, geom)]
    if not near:
        raise ValueError(f"{road}: trace never passes within {ROAD_NEAR_M} m, hand-set the band instead")
    med = statistics.median(near)
    level = next(k for k, (lo, hi) in SPEED_BANDS.items() if hi is None or med <= hi + 0.999)
    return band(road, level, start, end, routes_)


def incident(kind, lat, lon, at: datetime, text):
    return {"type": kind, "lat": lat, "lon": lon, "message": f"({at.day}/{at.month}){at:%H:%M} {text}",
            "reported_at": at.isoformat()}


def place(name, pt=None):
    lat, lon = pt or LOC[name]
    return {"lat": lat, "lon": lon, "name": name}


def trip_block(trip_id, service_type, pickup, dropoff, route, requested, accepted, gps, pressed_here,
               pickup_at=None, dropoff_at=None, cancelled_at=None, cancelled_by=None):
    return {
        "trip_id": trip_id, "service_type": service_type,
        "pickup": pickup, "dropoff": dropoff,
        "estimated_km": route["total_km"], "estimated_min": route["total_min"],
        "requested_at": requested.isoformat(), "accepted_at": accepted.isoformat(),
        "driver_arrived_at": first_within(gps, (pickup["lat"], pickup["lon"])),
        "driver_pressed_here_at": pressed_here.isoformat() if pressed_here else None,
        "pickup_at": pickup_at.isoformat() if pickup_at else None,
        "dropoff_at": dropoff_at.isoformat() if dropoff_at else None,
        "cancelled_at": cancelled_at.isoformat() if cancelled_at else None,
        "cancelled_by": cancelled_by,
    }


def chat(*lines):
    return [{"ts": T(ts).isoformat(), "from": who, "text": text} for ts, who, text in lines]


def profiles(rider, driver):
    """rider = (age, rating, disputes, upheld, route_upheld, no_show_upheld); driver adds trips_90d after rating.
    Per-type upheld counts feed RD-6 (route) and never exceed disputes_upheld_90d."""
    keys_r = ("account_age_days", "rating", "disputes_90d", "disputes_upheld_90d",
              "route_disputes_upheld_90d", "no_show_disputes_upheld_90d")
    keys_d = ("account_age_days", "rating", "trips_90d", "disputes_90d", "disputes_upheld_90d",
              "route_disputes_upheld_90d", "no_show_disputes_upheld_90d")
    out = {"rider": dict(zip(keys_r, rider)), "driver": dict(zip(keys_d, driver))}
    for who, p in out.items():
        assert p["route_disputes_upheld_90d"] + p["no_show_disputes_upheld_90d"] <= p["disputes_upheld_90d"] <= p["disputes_90d"], who
    return out


# ----------------------------------------------------------------------------------------------- cases

# ----------------------------------------------------------------------------------------------- cases

def c0001(rates):
    """Detour in three parts: (1) Orchard jammed after an accident, driver asks to go round by Cavenagh and the
    rider agrees (RD-4/RD-5 exempt); (2) the rider asks for a 7-Eleven stop; (3) the driver drives to a store on
    Beach Road, ~1.5 km off the route, without saying so (not exempt -> RD-2 partial refund)."""
    rp = routes(1)
    P, D, store = LOC["Orchard Road"], LOC["Marina Bay Sands"], LOC["7-Eleven Beach Road"]
    route = rp.route([P, D])                                                     # Scotts Rd -> Orchard -> Bras Basah -> Raffles Blvd -> Bayfront
    accepted, pickup_at, dropoff_at = T("2026-09-20 14:00:40"), T("2026-09-20 14:05:10"), T("2026-09-20 14:31:40")
    stop_at, stop_s = T("2026-09-20 14:20:20"), 250
    opt = [tuple(p) for p in route["polyline"]]
    loops = [{"leave": P, "via": [(1.3075, 103.8425)], "rejoin": (1.2987, 103.8475)},                    # Orchard Rd -> Cavenagh Rd (parallel) -> back to Orchard -> Bras Basah
             {"leave": (1.2932, 103.8558), "via": [store], "rejoin": D}]                                  # Raffles Blvd -> Beach Rd store -> MBS
    _, trip_gps, detours, legs = detour_trace(
        rp, opt, loops, pickup_at, secs(pickup_at, dropoff_at),
        stops=[Stop(*store, start_s=secs(pickup_at, stop_at), duration_s=stop_s)],
        zones=[Congestion(0.0, 0.5, 8.0)], seed=1)                             # Scotts/Orchard jam: first 500 m at 8 km/h
    gps = approach_trace(rp, offset(P, 250, 1300), P, accepted, pickup_at, wait_s=10, seed=1) + trip_gps[1:]
    trip = trip_block("T-1042", "RydeTAXI", place("Orchard Road"), place("Marina Bay Sands"), route,
                      T("2026-09-20 14:00:00"), accepted, gps, T("2026-09-20 14:05:00"), pickup_at, dropoff_at)
    w0, w1 = T("2026-09-20 14:00:00"), T("2026-09-20 14:35:00")
    R = [route, *legs]
    return {
        "case_id": "C-0001",
        "dispute": {"type": "route_deviation", "filed_by": "rider", "filed_at": T("2026-09-20 15:10:00").isoformat(),
                    "statement": "The driver took a longer route and I was overcharged. I only asked for a quick 7-Eleven "
                                 "stop on the way, not a drive out to Beach Road."},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {
            "speed_bands": [band("ORCHARD ROAD", 1, w0, T("2026-09-20 14:10:00"), R),                     # jammed, avoided via Cavenagh
                            band_from_gps("BRAS BASAH ROAD", trip_gps, w0, w1, R),
                            band_from_gps("BAYFRONT AVENUE", trip_gps, T("2026-09-20 14:20:00"), T("2026-09-20 14:40:00"), R)],
            "incidents": [incident("Accident", 1.3002, 103.8415, T("2026-09-20 13:52:00"),
                                   "Accident on Orchard Road (towards Bras Basah) after Cavenagh Road, two lanes closed.")],
        },
        "weather": {"rain_mm": 0, "description": "Fair"},
        "fare": metered_fare(slice_gps(gps, trip["pickup_at"], trip["dropoff_at"]), rates),
        "chat": chat(("2026-09-20 14:01:00", "driver", "Hi, traffic on Orchard is bad, ok if I go round by Cavenagh?"),
                     ("2026-09-20 14:02:00", "rider", "Sure. Can you stop at a 7-Eleven on the way?"),
                     ("2026-09-20 14:03:00", "driver", "Ok")),
        "driver_statement": "Orchard was jammed after an accident, rider agreed to go round by Cavenagh and asked for a stop. "
                            "I stopped at the 7-Eleven I know on Beach Road.",
        "profiles": profiles((610, 4.9, 0, 0, 0, 0), (1450, 4.7, 812, 3, 1, 0, 1)),
        "_detours": detours,
    }


def c0002(rates):
    """Detour: leaves the PIE at Paya Lebar and goes through Sims Avenue for no reason, no chat, repeat-offender
    driver (3 route disputes upheld)."""
    rp = routes(2)
    P, D = LOC["Clarke Quay"], LOC["Bedok Mall"]
    route = rp.route([P, D])                                                     # Clemenceau -> CTE -> PIE -> Bedok North
    accepted, pickup_at, dropoff_at = T("2026-09-21 12:30:35"), T("2026-09-21 12:34:15"), T("2026-09-21 13:08:15")
    opt = [tuple(p) for p in route["polyline"]]
    loops = [{"leave": (1.3300, 103.8800), "via": [(1.3180, 103.8930), (1.3210, 103.9060), (1.3130, 103.9180)],
              "rejoin": D}]                                                      # PIE exit -> Paya Lebar Rd -> Sims Ave -> Bedok Mall
    cte_km = road_km(route, "CENTRAL EXPRESSWAY")
    _, trip_gps, detours, legs = detour_trace(rp, opt, loops, pickup_at, secs(pickup_at, dropoff_at),
                                              zones=[Congestion(cte_km + 0.3, project(1.3300, 103.8800, opt)[1] - 0.5, EXPRESSWAY_KMH)],
                                              seed=2)
    gps = approach_trace(rp, offset(P, 300, 1100), P, accepted, pickup_at, wait_s=10, seed=2) + trip_gps[1:]
    trip = trip_block("T-1057", "RydeTAXI", place("Clarke Quay"), place("Bedok Mall"), route,
                      T("2026-09-21 12:30:00"), accepted, gps, T("2026-09-21 12:34:05"), pickup_at, dropoff_at)
    R = [route, *legs]
    return {
        "case_id": "C-0002",
        "dispute": {"type": "route_deviation", "filed_by": "rider", "filed_at": T("2026-09-21 13:40:00").isoformat(),
                    "statement": "The app estimated about 15 km but the driver came off the PIE at Paya Lebar and the meter "
                                 "showed almost 20 km. He never asked me. I want the extra distance refunded."},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {
            "speed_bands": [band_from_gps("CENTRAL EXPRESSWAY", trip_gps, T("2026-09-21 12:30:00"), T("2026-09-21 13:15:00"), R),
                            band_from_gps("PAN ISLAND EXPRESSWAY", trip_gps, T("2026-09-21 12:30:00"), T("2026-09-21 12:46:00"), R),
                            band_from_gps("PAYA LEBAR ROAD", trip_gps, T("2026-09-21 12:45:00"), T("2026-09-21 13:15:00"), R)],
            "incidents": [],
        },
        "weather": {"rain_mm": 0, "description": "Fair"},
        "fare": metered_fare(slice_gps(gps, trip["pickup_at"], trip["dropoff_at"]), rates),
        "chat": [],
        "driver_statement": "I followed my GPS, it took me off at Paya Lebar. Nothing wrong with the fare.",
        "profiles": profiles((400, 4.8, 1, 0, 0, 0), (980, 4.5, 640, 5, 3, 3, 0)),
        "_detours": detours,
    }


def c0003(rates):
    """Detour fully explained by a KPE closure; the driver told the rider before leaving the planned route and took
    the ECP instead."""
    rp = routes(3)
    P, D = LOC["Tanjong Pagar Centre"], LOC["Bedok Mall"]
    route = rp.route([P, D])                                                     # Straits Blvd -> MCE -> KPE -> PIE -> Bedok North
    accepted, pickup_at, dropoff_at = T("2026-09-21 18:06:00"), T("2026-09-21 18:10:00"), T("2026-09-21 18:42:30")
    opt = [tuple(p) for p in route["polyline"]]
    loops = [{"leave": (1.2729, 103.8536), "via": [(1.2985, 103.8880), (1.3160, 103.9290)], "rejoin": D}]   # MCE -> ECP -> Bedok South
    _, trip_gps, detours, legs = detour_trace(rp, opt, loops, pickup_at, secs(pickup_at, dropoff_at),
                                              loop_zones={0: (1.0, EXPRESSWAY_KMH)}, seed=3)
    gps = approach_trace(rp, (1.2840, 103.8500), P, accepted, pickup_at, wait_s=10, seed=3) + trip_gps[1:]   # from Cecil St
    trip = trip_block("T-1063", "RydeTAXI", place("Tanjong Pagar Centre"), place("Bedok Mall"), route,
                      T("2026-09-21 18:05:20"), accepted, gps, T("2026-09-21 18:09:50"), pickup_at, dropoff_at)
    R = [route, *legs]
    return {
        "case_id": "C-0003",
        "dispute": {"type": "route_deviation", "filed_by": "rider", "filed_at": T("2026-09-21 19:05:00").isoformat(),
                    "statement": "Fare was about $2 more than the estimate. The driver went the long way round via the ECP."},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {
            "speed_bands": [band("KALLANG PAYA LEBAR EXPRESSWAY", 1, T("2026-09-21 18:00:00"), T("2026-09-21 18:45:00"), R, trim_start_m=700),   # closed, not taken; geometry past the shared junction
                            band_from_gps("EAST COAST PARKWAY", trip_gps, T("2026-09-21 18:00:00"), T("2026-09-21 18:45:00"), R),
                            band_from_gps("MARINA COASTAL EXPRESSWAY", trip_gps, T("2026-09-21 18:00:00"), T("2026-09-21 18:30:00"), R)],
            "incidents": [incident("Accident", 1.2952, 103.8760, T("2026-09-21 18:02:00"),
                                   "Accident on KPE (towards TPE) at the MCE tunnel entrance. All lanes closed. Avoid KPE.")],
        },
        "weather": {"rain_mm": 1.2, "description": "Light rain"},
        "fare": metered_fare(slice_gps(gps, trip["pickup_at"], trip["dropoff_at"]), rates),
        "chat": chat(("2026-09-21 18:10:20", "driver", "KPE is closed at the tunnel entrance because of an accident. I'll go by ECP instead, ok?"),
                     ("2026-09-21 18:10:50", "rider", "Ok, thanks for telling me.")),
        "driver_statement": "KPE was fully closed after an accident at the tunnel entrance. I told the rider and went by ECP, "
                            "which was the fastest open route.",
        "profiles": profiles((150, 4.6, 2, 1, 1, 0), (2200, 4.9, 910, 1, 0, 0, 0)),
        "_detours": detours,
    }


def c0004(rates):
    """No-show, driver-initiated: the driver parks 612 m from the pickup, taps 'I'm Here' there at 08:16:00,
    waits 3.5 min and cancels the trip as a rider no-show; the rider is charged $6.61 (NS-0 -> NS-2 refund)."""
    rp = routes(4)
    spot = LOC["Stamford Road roadside bay (SMU)"]
    bj = LOC["Bugis Junction"]
    f = 612 / haversine_m(spot, bj)  # pickup = 612 m from the parking spot, on the line towards Bugis Junction
    P = (round(spot[0] + (bj[0] - spot[0]) * f, 6), round(spot[1] + (bj[1] - spot[1]) * f, 6))
    route = rp.route([P, LOC["Tanjong Pagar Centre"]])
    accepted, pressed, cancelled = T("2026-09-22 08:10:05"), T("2026-09-22 08:16:00"), T("2026-09-22 08:19:30")
    park_at = secs(accepted, T("2026-09-22 08:13:10"))
    approach = rp.route([offset(spot, 240, 1000), spot])
    poly = approach["polyline"]
    gps = build_trajectory(poly, accepted, secs(accepted, cancelled),
                           stops=[Stop(*spot, start_s=park_at, duration_s=secs(accepted, cancelled) - park_at,
                                       jitter_m=2.5, anchor_s=secs(T("2026-09-22 08:13:10"), T("2026-09-22 08:15:30")),
                                       away_from=P)], seed=4)
    trip = trip_block("T-1071", "RydeX", place("Bugis Junction (Victoria St entrance)", P), place("Tanjong Pagar Centre"),
                      route, T("2026-09-22 08:09:30"), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by="driver")
    return {
        "case_id": "C-0004",
        "dispute": {"type": "no_show", "filed_by": "rider", "filed_at": T("2026-09-22 08:25:00").isoformat(),
                    "statement": "The driver marked 'arrived' but he was never at the Victoria St entrance. I waited there "
                                 "the whole time, then he cancelled on me as a no-show and I was charged $6.61."},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {
            "speed_bands": [band("VICTORIA STREET", 5, T("2026-09-22 08:00:00"), T("2026-09-22 08:30:00"), [route, approach]),
                            band("NORTH BRIDGE ROAD", 5, T("2026-09-22 08:00:00"), T("2026-09-22 08:30:00"), [route, approach])],
            "incidents": [],
        },
        "weather": {"rain_mm": 0, "description": "Fair"},
        "fare": cancellation_fare(rates),
        "chat": chat(("2026-09-22 08:14:00", "rider", "Hi, where are you? I'm waiting at the Victoria St entrance of Bugis Junction."),
                     ("2026-09-22 08:16:10", "driver", "I'm here already, please come out"),
                     ("2026-09-22 08:17:30", "rider", "I'm at the entrance and I don't see any car. What's your plate?"),
                     ("2026-09-22 08:19:20", "driver", "Waited more than 3 min, cancelling")),
        "driver_statement": "I pressed I'm Here at 08:16 and waited more than 3 minutes. The rider never showed up, "
                            "so I cancelled as a no-show. Victoria Street was too jammed to get closer.",
        "profiles": profiles((820, 4.9, 0, 0, 0, 0), (700, 4.6, 540, 2, 2, 0, 2)),
    }


def c0005(rates):
    """No-show: driver waits 6 min within 50 m, rider says 'two more minutes', never shows, rider cancels."""
    rp = routes(5)
    P = LOC["Tanjong Pagar Centre"]
    stand = offset(P, 60, 40)  # taxi stand 40 m from the pin
    route = rp.route([P, LOC["Orchard Road"]])
    accepted, cancelled, pressed = T("2026-09-23 09:00:10"), T("2026-09-23 09:09:10"), T("2026-09-23 09:03:00")
    approach = rp.route([(1.2840, 103.8500), stand])                            # from Cecil St
    poly = approach["polyline"]
    park_at = secs(accepted, pressed)
    gps = build_trajectory(poly, accepted, secs(accepted, cancelled),
                           stops=[Stop(*stand, start_s=park_at, duration_s=secs(accepted, cancelled) - park_at, jitter_m=1.5)],
                           seed=5)
    trip = trip_block("T-1088", "RydeX", place("Tanjong Pagar Centre"), place("Orchard Road"), route,
                      T("2026-09-23 08:59:30"), accepted, gps, pressed, cancelled_at=cancelled, cancelled_by="rider")
    return {
        "case_id": "C-0005",
        "dispute": {"type": "no_show", "filed_by": "rider", "filed_at": T("2026-09-23 09:30:00").isoformat(),
                    "statement": "I told the driver I was two minutes away and he still charged me $6.61 for cancelling. "
                                 "I want it refunded."},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {"speed_bands": [band_from_gps("ANSON ROAD", gps, T("2026-09-23 09:00:00"), T("2026-09-23 09:15:00"), [approach, route])],
                    "incidents": []},
        "weather": {"rain_mm": 0, "description": "Fair"},
        "fare": cancellation_fare(rates),
        "chat": chat(("2026-09-23 09:03:30", "driver", "I'm here at the Tanjong Pagar Centre taxi stand, silver Toyota Altis."),
                     ("2026-09-23 09:05:00", "rider", "Coming down, give me 2 more minutes"),
                     ("2026-09-23 09:08:00", "driver", "Called you twice, no answer. Waited 5 min already.")),
        "driver_statement": "I waited more than 6 minutes at the stand and called twice. The rider never came down.",
        "profiles": profiles((300, 4.5, 3, 0, 0, 0), (1600, 4.9, 700, 0, 0, 0, 0)),
    }


def c0006(rates):
    """Safety: rider asks to get out, driver threatens to lock the doors, trip continues to the destination."""
    rp = routes(6)
    P, D = LOC["Clarke Quay"], LOC["Bedok Mall"]
    route = rp.route([P, D])                                                     # Clemenceau -> CTE -> PIE -> Bedok North
    accepted, pickup_at, dropoff_at = T("2026-09-24 21:29:30"), T("2026-09-24 21:34:20"), T("2026-09-24 21:55:00")
    gps = approach_trace(rp, offset(P, 20, 1200), P, accepted, pickup_at, wait_s=10, seed=6)
    trip_gps = build_trajectory(route["polyline"], pickup_at, secs(pickup_at, dropoff_at),
                                congestion=[Congestion(road_km(route, "CENTRAL EXPRESSWAY") + 0.3,
                                                       road_km(route, "PAN ISLAND EXPRESSWAY", "to") - 0.3, EXPRESSWAY_KMH)], seed=6)
    gps += trip_gps[1:]
    trip = trip_block("T-1095", "RydeX", place("Clarke Quay"), place("Bedok Mall"), route,
                      T("2026-09-24 21:28:50"), accepted, gps, T("2026-09-24 21:34:10"), pickup_at, dropoff_at)
    return {
        "case_id": "C-0006",
        "dispute": {"type": "safety", "filed_by": "rider", "filed_at": T("2026-09-24 22:05:00").isoformat(),
                    "statement": "The driver threatened to lock me in when I asked to get out. I felt unsafe for the whole ride."},
        "trip": trip, "route": route, "gps": gps,
        "traffic": {
            "speed_bands": [band_from_gps("CENTRAL EXPRESSWAY", trip_gps, T("2026-09-24 21:30:00"), T("2026-09-24 21:45:00"), [route]),
                            band_from_gps("PAN ISLAND EXPRESSWAY", trip_gps, T("2026-09-24 21:30:00"), T("2026-09-24 22:00:00"), [route])],
            "incidents": [],
        },
        "weather": {"rain_mm": 0, "description": "Cloudy"},
        "fare": fixed_fare(route, rates),
        "chat": chat(("2026-09-24 21:42:00", "rider", "Please stop the car, I want to get out here."),
                     ("2026-09-24 21:43:00", "driver", "Sit down or I lock the doors.")),
        "driver_statement": "The rider was drunk and tried to open the door on the expressway. I told her to sit down "
                            "for her own safety and did not stop until the destination.",
        "profiles": profiles((520, 4.8, 0, 0, 0, 0), (2100, 4.9, 1204, 0, 0, 0, 0)),
    }


# ----------------------------------------------------------------------------------------------- output

def dump(case: dict, path: str):
    text = json.dumps(case, indent=2, ensure_ascii=False)
    flat = r'\{\n\s+((?:"[^"\n]*": [^\n{}\[\]]*\n\s+)*"[^"\n]*": [^\n{}\[\]]*)\n\s+\}'
    text = re.sub(flat, lambda m: "{" + re.sub(r"\n\s+", " ", m.group(1)) + "}", text)  # flat objects -> one line
    text = re.sub(r"\[\n\s+(-?[\d.]+),\n\s+(-?[\d.]+)\n\s+\]", r"[\1, \2]", text)         # [lat, lon] -> one line
    assert json.loads(text) == case
    with open(path, "w") as f:
        f.write(text + "\n")


def describe(c: dict, detours):
    t, fare, gps = c["trip"], c["fare"], c["gps"]
    P = (t["pickup"]["lat"], t["pickup"]["lon"])
    near = min_dist(gps, P)
    line = f'{c["case_id"]} {c["dispute"]["type"]:16} {t["service_type"]:9} optimal {t["estimated_km"]:.2f} km/{t["estimated_min"]} min'
    if t["pickup_at"]:
        trip_gps = slice_gps(gps, t["pickup_at"], t["dropoff_at"])
        stops = stationary_windows(trip_gps)
        line += f' | actual {fare["distance_km"]:.2f} km/{fare["time_min"]} min moving total ${fare["total"]:.2f}'
        line += f' (+{fare["distance_km"] - t["estimated_km"]:.2f} km, wait {fare["waiting_min"]} min ${fare["waiting_fee"]:.2f})'
        for s, e, sec, la, lo in stops:
            off_route = project(la, lo, c["route"]["polyline"])[0]
            line += f'\n       stop {s[11:19]}-{e[11:19]} {sec} s at ({la},{lo}) {off_route:.0f} m off optimal route'
        for d in detours or []:
            line += (f'\n       detour {d["start"][11:19]}-{d["end"][11:19]} driven {d["driven_km"]:.2f} km for '
                     f'{d["route_km"]:.2f} km of route: +{d["extra_km"]:.2f} km (max {d["max_off_route_m"]} m off route)')
    else:
        line += f' | cancelled by {t["cancelled_by"]} at {t["cancelled_at"][11:19]}, fee ${fare["cancellation_fee"]}'
    line += f'\n       closest to pickup {haversine_m((near["lat"], near["lon"]), P):.0f} m at {near["ts"][11:19]}, ' \
            f'arrived_at {t["driver_arrived_at"] and t["driver_arrived_at"][11:19]}, pressed_here {t["driver_pressed_here_at"] and t["driver_pressed_here_at"][11:19]}'
    bands = ", ".join(f'{b["road_name"].title()} {b["speed_band"]}' for b in c["traffic"]["speed_bands"])
    print(line + f"\n       bands: {bands}")


def main():
    rates = load_rates()
    os.makedirs(OUT_DIR, exist_ok=True)
    for build in (c0001, c0002, c0003, c0004, c0005, c0006):
        case = build(rates)
        detours = case.pop("_detours", None)
        dump(case, os.path.join(OUT_DIR, f'{case["case_id"]}.json'))
        describe(case, detours)


if __name__ == "__main__":
    main()
