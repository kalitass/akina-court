"""Scenario contract: the checkable facts a scenario's labels imply, and the checks of a case against them.

A scenario says "accident on the stretch the driver bypassed", "rider agreed to a named road 3 min before the
segment", "driver parked 600 m away and tapped I'm Here". Every such label is a claim about the generated record.
`contract_for(spec)` turns the scenario's conditions into a table of those claims, `check(case, contract)` measures the
record and returns every claim it does not meet, and `check_label(hard, truth)` compares the one-line `hard` label
with the reference answer. The generator refuses to write a case that fails either; the tests run the same checks
over every committed case file.

The measurements here are written against the raw record with this module's own geometry (nothing is imported from
core/), so a case that passes the contract tells its story on its own, whatever the engine does with it.
"""
from __future__ import annotations

import math
import os
import re
import statistics
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fare import fixed_fare, load_rates, metered_fare, slice_gps  # noqa: E402

OFF_ROUTE_M = 200           # mirrors core/facts/tools.py (a point farther than this from the optimal polyline is off-route)
DETOUR_MERGE_S = 120
DETOUR_MIN_KM = 0.2
STOP_MIN_S = 120
STOP_RADIUS_M = 30
ENDPOINT_RADIUS_M = 100
PICKUP_RADIUS_M = 200
INCIDENT_NEAR_M = 300       # RD-4: incident within this of the optimal route
STRETCH_TOL_KM = 0.3        # RD-4: along-track tolerance either side of the replaced stretch
MIN_REPLACED_KM = 1.0       # a loop that claims to go round a stretch (incident, named road, general consent) must bypass this much
STOP_PLACE_M = 150          # a named stop must be this close to the place the rider named
TAP_TOL_M = 25              # the tap distance may differ from park_m by GPS jitter / kerb snapping
SG_BOUNDS = (1.15, 1.48, 103.55, 104.1)

WEATHER = {"fair": {"rain_mm": 0, "description": "Fair"},
           "light": {"rain_mm": 1.8, "description": "Light rain"},
           "heavy": {"rain_mm": 18.5, "description": "Heavy rain, thundery showers"}}
ROAD_NAMING_CONSENT = ("before", "after", "before_seg1", "request_only", "named_singlish", "named_cn", "named_elsewhere", "negation")
GENERAL_CONSENT = ("general", "general_cn", "general_errand")


class ContractError(AssertionError):
    """A generated case does not tell its scenario's story; the generator refuses to write it."""


# ----------------------------------------------------------------------------------------------- geometry (own)

def hav_m(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def project(lat, lon, poly):
    """(distance m, along-track km) of the nearest point of `poly` to (lat, lon)."""
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


def along_km(poly):
    cum = [0.0]
    for a, b in zip(poly, poly[1:]):
        cum.append(cum[-1] + hav_m(a, b) / 1000)
    return cum


def ts(p) -> datetime:
    return datetime.fromisoformat(p["ts"])


def segments(gps, poly):
    """Off-route segments the way the fact tool sees them: [{"start", "end", "driven_km", "route_km", "extra_km",
    "max_off_route_m", "entry_km", "exit_km", "i0", "i1"}]."""
    pts = [(p["lat"], p["lon"]) for p in gps]
    proj = [project(la, lo, poly) for la, lo in pts]
    runs, i, n = [], 0, len(pts)
    while i < n:
        if proj[i][0] <= OFF_ROUTE_M:
            i += 1
            continue
        j = i
        while j < n and proj[j][0] > OFF_ROUTE_M:
            j += 1
        if runs and (ts(gps[i]) - ts(gps[runs[-1][1] - 1])).total_seconds() <= DETOUR_MERGE_S:
            runs[-1] = (runs[-1][0], j)
        else:
            runs.append((i, j))
        i = j
    out = []
    for i, j in runs:
        entry, exit_ = max(i - 1, 0), min(j, n - 1)
        driven = sum(hav_m(a, b) for a, b in zip(pts[entry:exit_], pts[entry + 1:exit_ + 1])) / 1000
        skipped = abs(proj[exit_][1] - proj[entry][1])
        if driven - skipped < DETOUR_MIN_KM:
            continue
        out.append({"start": gps[entry]["ts"], "end": gps[exit_]["ts"], "driven_km": round(driven, 2), "route_km": round(skipped, 2),
                    "extra_km": round(driven - skipped, 2), "max_off_route_m": round(max(proj[k][0] for k in range(i, j))),
                    "entry_km": min(proj[entry][1], proj[exit_][1]), "exit_km": max(proj[entry][1], proj[exit_][1]), "i0": entry, "i1": exit_})
    return out


def stops(gps, exclude=()):
    """Stationary runs (within STOP_RADIUS_M of their first point for >= STOP_MIN_S), skipping those within
    ENDPOINT_RADIUS_M of any point in `exclude` (pickup / drop-off)."""
    out, start = [], None
    pts = [(p["lat"], p["lon"]) for p in gps]
    runs = []
    for i, p in enumerate(pts):
        if start is not None and hav_m(p, pts[start]) > STOP_RADIUS_M:
            if (ts(gps[i - 1]) - ts(gps[start])).total_seconds() >= STOP_MIN_S:
                runs.append((start, i - 1))
            start = None
        if start is None:
            start = i
    if start is not None and (ts(gps[-1]) - ts(gps[start])).total_seconds() >= STOP_MIN_S:
        runs.append((start, len(pts) - 1))
    for a, b in runs:
        if any(hav_m(pts[a], e) <= ENDPOINT_RADIUS_M for e in exclude):
            continue
        out.append({"start": gps[a]["ts"], "end": gps[b]["ts"], "duration_s": int((ts(gps[b]) - ts(gps[a])).total_seconds()),
                    "lat": pts[a][0], "lon": pts[a][1]})
    return out


def continuous_after_tap_s(gps, P, tap: datetime) -> int:
    """Seconds inside PICKUP_RADIUS_M from the tap until the first exit (the NS-1 (iii) measure)."""
    after = [p for p in gps if ts(p) >= tap]
    t = 0
    for a, b in zip(after, after[1:]):
        if hav_m((a["lat"], a["lon"]), P) <= PICKUP_RADIUS_M and hav_m((b["lat"], b["lon"]), P) <= PICKUP_RADIUS_M:
            t += int((ts(b) - ts(a)).total_seconds())
        else:
            break
    return t


def road_runs(route, lo_km, hi_km):
    """[(road name, metres of it inside the along-track window lo..hi of the optimal route)], longest first."""
    tot = {}
    for r in route.get("roads", []):
        ov = min(r["to_m"], hi_km * 1000) - max(r["from_m"], lo_km * 1000)
        if ov > 0:
            tot[r["name"]] = tot.get(r["name"], 0) + ov
    return sorted(tot.items(), key=lambda x: -x[1])


# ----------------------------------------------------------------------------------------------- contracts

def contract_for(spec: dict, loc: dict | None = None) -> dict:
    """The checkable claims a scenario's conditions make about its record. Keys are check names, values parameters;
    `check()` knows every key. `loc` resolves a named stop place to coordinates."""
    c = {"kind": spec["kind"], "grid_s": 5, "chat_in_window": True, "estimate_equals_route": True, "fare_recomputed": True,
         "weather": WEATHER[spec.get("weather", "fair")], "templates": True}   # templates: the chat / incident / band texts follow scenarios.py
    if spec["kind"] == "route_deviation":
        n = len(spec["loops"])
        c.update({"segments": n, "pricing": "fixed" if spec["service"] == "RydeX" else "metered",
                  "prior": spec["prior"], "consent": spec["consent"], "stop": spec["stop"], "incident": spec["incident"],
                  "band": spec["band"], "threat": spec["threat"], "statement_consistent": True})
        if n == 0:
            c["no_stops"] = True
        if spec.get("gps_tail_cut_s"):
            c.update({"tail_cut_s": spec["gps_tail_cut_s"], "fare_recomputed": False})
        if n and (spec["incident"] in ("on_stretch", "seg1", "late") or spec["consent"] in ROAD_NAMING_CONSENT + ("general", "general_cn")):
            # the story says the loop goes ROUND a stretch (an accident on it, "go round via X", "take another way"):
            # an out-and-back spur bypasses nothing, and the car would still drive the whole stretch it claims to avoid
            c["route_km_min"] = {0: MIN_REPLACED_KM}
            c["stretch_driven_max"] = {0: 0.5}
        if spec["stop"] == "named":
            c["stop_place"] = (spec["loops"][0]["place"], (loc or {}).get(spec["loops"][0]["place"]))
    elif spec["kind"] == "no_show":
        c.update({"cancelled_by": spec.get("recorded_by", "driver") if spec["by"] == "driver" else "rider", "by": spec["by"],
                  "prior_ns": spec["prior_ns"], "fee_in_statement": True, "chat": spec.get("chat")})
        if spec["by"] == "driver":
            park = spec["park_m"]
            c["tap"] = spec["here"]
            if spec["here"]:
                c["tap_distance_m"] = (max(park - TAP_TOL_M, 0), park + TAP_TOL_M)
            if park > PICKUP_RADIUS_M:
                c["never_within_200m"] = True
                c["wait_after_tap_s"] = (0, 0)
            elif "within_s" in spec:
                c["wait_after_tap_s"] = (spec["within_s"], spec["within_s"])
            elif spec["here"]:
                c["wait_after_tap_s"] = (spec["wait_s"] - 30, spec["wait_s"] - 15)     # the tap comes 20 s after parking
            else:
                c["wait_at_pin_s"] = spec["wait_s"] - 10
            if spec.get("gps_hole_s"):
                c["gps_hole_s"] = spec["gps_hole_s"]
                c["grid_s"] = None
            if spec.get("policy"):
                c["policy"] = dict(spec["policy"])
        else:
            c["cancel_s"] = spec["cancel_s"]
            c["driver"] = spec["driver"]
            c["tap"] = spec["driver"] == "at_pickup"
    else:
        c.update({"chat": spec["chat"], "statement_threat": bool(spec.get("statement_threat")), "segments": 0, "no_stops": True,
                  "pricing": "fixed" if spec["service"] == "RydeX" else "metered"})
    return c


# ----------------------------------------------------------------------------------------------- checks

def check(case: dict, c: dict) -> list[str]:
    """Every claim of contract `c` the record `case` does not meet, as one line each (empty = the record tells its story)."""
    errs: list[str] = []
    bad = errs.append
    t, gps, route = case["trip"], case["gps"], case["route"]
    poly = [tuple(p) for p in route["polyline"]]
    P = (t["pickup"]["lat"], t["pickup"]["lon"])
    D = (t["dropoff"]["lat"], t["dropoff"]["lon"])
    acc, end = datetime.fromisoformat(t["accepted_at"]), datetime.fromisoformat(t["cancelled_at"] or t["dropoff_at"])
    chat = case["chat"]
    kind = c["kind"]
    if case["dispute"]["type"] != kind:
        bad(f"dispute.type {case['dispute']['type']} != {kind}")

    # ---- common
    tss = [ts(p) for p in gps]
    if any(b <= a for a, b in zip(tss, tss[1:])):
        bad("gps timestamps not strictly increasing")
    if c.get("grid_s"):
        steps = {int((b - a).total_seconds()) for a, b in zip(tss, tss[1:])}
        if steps != {c["grid_s"]}:
            bad(f"gps is not a {c['grid_s']} s grid (steps {sorted(steps)[:4]})")
    for s in [p["ts"] for p in gps] + [m["ts"] for m in chat if m.get("ts")] + [t["accepted_at"], case["dispute"]["filed_at"]]:
        if not s.endswith("+08:00"):
            bad(f"timestamp without +08:00: {s}")
            break
    if any(not (SG_BOUNDS[0] <= p["lat"] <= SG_BOUNDS[1] and SG_BOUNDS[2] <= p["lon"] <= SG_BOUNDS[3]) for p in gps):
        bad("gps outside Singapore")
    if c.get("estimate_equals_route") and (t["estimated_km"] != route["total_km"] or t["estimated_min"] != route["total_min"]):
        bad("trip.estimated_km / estimated_min differ from route.total_km / total_min")
    if c.get("chat_in_window"):
        for m in chat:
            if m.get("ts") and not (acc <= ts(m) <= end):
                bad(f"chat at {m['ts'][11:19]} outside accepted..end")
    if datetime.fromisoformat(case["dispute"]["filed_at"]) < end:
        bad("dispute filed before the trip ended")
    w = c.get("weather")
    if w and (case["weather"]["rain_mm"] != w["rain_mm"] or case["weather"]["description"] != w["description"]):
        bad(f"weather {case['weather']} != {w}")
    trip_gps = slice_gps(gps, t["pickup_at"], t["dropoff_at"]) if t["pickup_at"] else []
    if c.get("fare_recomputed") and t["pickup_at"]:
        rates = load_rates()
        f = case["fare"]
        want = metered_fare(trip_gps, rates, f["surge_multiplier"], f["discount"]) if f["pricing"] == "metered" else fixed_fare(route, rates, f["surge_multiplier"], f["discount"])
        if want != f:
            bad("fare does not recompute from the trace / rate card")
    if c.get("pricing") and case["fare"]["pricing"] != c["pricing"]:
        bad(f"fare.pricing {case['fare']['pricing']} != {c['pricing']}")

    if kind == "route_deviation":
        _check_route(case, c, errs, trip_gps, poly, P, D)
    elif kind == "no_show":
        _check_noshow(case, c, errs, P)
    else:
        _check_safety(case, c, errs, trip_gps, poly, P, D)
    return errs


def _check_route(case, c, errs, trip_gps, poly, P, D):
    bad = errs.append
    t, route, chat = case["trip"], case["route"], case["chat"]
    if c.get("tail_cut_s"):
        tail = (datetime.fromisoformat(t["dropoff_at"]) - ts(case["gps"][-1])).total_seconds()
        if abs(tail - c["tail_cut_s"]) > 5:
            bad(f"gps tail cut is {tail:.0f} s, scenario says {c['tail_cut_s']}")
    segs = segments(trip_gps, poly)
    if len(segs) != c["segments"]:
        bad(f"{len(segs)} off-route segment(s) measured, scenario has {c['segments']} loop(s): {[(s['route_km'], s['extra_km']) for s in segs]}")
        return
    st_all = stops(trip_gps, exclude=(P, D))
    seg_start = [ts({"ts": s["start"]}) for s in segs]
    for k, s in enumerate(segs):
        if s["extra_km"] < 0.5:
            bad(f"segment {k + 1} adds only {s['extra_km']} km (noise floor 0.2 km)")
    for k, s in zip(range(len(segs) - 1), segs):
        if ts({"ts": segs[k + 1]["start"]}) <= ts({"ts": s["end"]}):
            bad("segments overlap or are out of order")
    for k, lim in (c.get("route_km_min") or {}).items():
        if k < len(segs) and segs[k]["route_km"] < lim:
            bad(f"segment {k + 1} is an out-and-back spur: it bypasses {segs[k]['route_km']:.2f} km of the optimal route, the story needs >= {lim} km")
    cum = along_km(poly)
    for k, lim in (c.get("stretch_driven_max") or {}).items():
        if k >= len(segs):
            continue
        s = segs[k]
        stretch = [p for p, km in zip(poly, cum) if s["entry_km"] + 0.05 <= km <= s["exit_km"] - 0.05]
        inside = [(p["lat"], p["lon"]) for p in trip_gps[s["i0"]:s["i1"] + 1]]
        if stretch and inside:
            frac = sum(1 for q in stretch if min(hav_m(q, g) for g in inside) <= 60) / len(stretch)
            if frac > lim:
                bad(f"segment {k + 1}: the car drives {frac:.0%} of the stretch it claims to go round")

    # ---- consent: the exchange exists, is timed as the label says, and names the roads the geometry shows
    consent = c["consent"]
    asks = [m for m in chat if m["from"] == "driver" and re.search(r"go round via|another way|pull in at the petrol", m["text"])]
    replies = [m for m in chat if m["from"] == "rider" and re.search(r"Sure|Can lah|可以|随便|whichever way|No, I'm not", m["text"])]
    if consent == "none":
        if asks or replies:
            bad("consent=none but the chat holds a route exchange")
    else:
        if not asks:
            bad(f"consent={consent} but no driver route request in the chat")
        else:
            d = (ts(asks[0]) - seg_start[0]).total_seconds()
            if consent == "after" and d < 60:
                bad(f"consent=after but the request came {d:+.0f} s from the segment start (needs >= +60 s)")
            if consent != "after" and d > -60:
                bad(f"consent={consent} but the request came {d:+.0f} s from the segment start (needs <= -60 s)")
            m = re.search(r"on (.+?) is building", asks[0]["text"]) if c.get("templates") else None
            if m:
                jam = m.group(1).upper()
                runs = road_runs(route, segs[0]["entry_km"], segs[0]["exit_km"])
                if not runs:
                    bad(f"driver names {jam.title()} as jammed but the loop bypasses no road at all")
                elif runs[0][0] != jam:
                    bad(f"driver names {jam.title()} as jammed but the bypassed stretch is mostly {runs[0][0].title()}")
        if consent == "request_only":
            if any(m["from"] == "rider" and asks and ts(asks[0]) < ts(m) < seg_start[0] for m in chat):
                bad("consent=request_only but the rider replied before the segment")
        elif consent != "scope_other":
            if not replies:
                bad(f"consent={consent} but no rider reply in the chat")
            else:
                d = (ts(replies[0]) - seg_start[0]).total_seconds()
                if consent == "after" and d <= 0:
                    bad("consent=after but the rider's reply came before the segment")
                if consent != "after" and d >= 0:
                    bad(f"consent={consent} but the rider's reply came {d:+.0f} s after the segment start")
                if consent == "negation" and "No" not in replies[0]["text"]:
                    bad("consent=negation but the rider's reply is not a refusal")
        else:
            if any(s["start"] <= x["start"] <= s["end"] for s in segs for x in st_all):
                bad("consent=scope_other (petrol stop agreed) but the car did stop inside the segment")
    # ---- stop (inside the segment the story puts it in: the generator's loop 1, a hand-written case says which)
    stop = c["stop"]
    sk = min(c.get("stop_segment", 0), len(segs) - 1)
    in_seg = [x for x in st_all if segs[sk]["start"] <= x["start"] <= segs[sk]["end"]]
    if stop == "none":
        if st_all:
            bad(f"stop=none but the trace holds a stop: {[(x['duration_s'], x['start'][11:19]) for x in st_all]}")
    else:
        if not in_seg:
            bad(f"stop={stop} but no stop (>= {STOP_MIN_S} s) inside segment {sk + 1}; stops: {[(x['duration_s'], x['start'][11:19]) for x in st_all]}")
        req = [m for m in chat if m["from"] == "rider" and re.search(r"stop at", m["text"])]
        if stop in ("named", "unnamed"):
            if not req:
                bad(f"stop={stop} but the rider never asked for a stop")
            elif ts(req[0]) >= seg_start[0]:
                bad(f"stop={stop} but the rider's request came after the segment started")
        if stop == "named" and in_seg:
            name, latlon = c["stop_place"]
            if req and name not in req[0]["text"]:
                bad(f"stop=named but the rider's message does not name {name}")
            if latlon:
                d = hav_m((in_seg[0]["lat"], in_seg[0]["lon"]), latlon)
                if d > STOP_PLACE_M:
                    bad(f"stop=named: the car stopped {d:.0f} m from {name} (needs <= {STOP_PLACE_M} m)")
        if stop == "unnamed" and in_seg:
            d = project(in_seg[0]["lat"], in_seg[0]["lon"], poly)[0]
            if d < 500:
                bad(f"stop=unnamed: the 7-Eleven is only {d:.0f} m off the route; the story needs a far one")
        if stop == "driver_errand" and req:
            bad("stop=driver_errand but the rider asked for a stop")
    # ---- incident
    inc_kind = c["incident"]
    incs = case["traffic"]["incidents"]
    if inc_kind == "none" and incs:
        bad("incident=none but the record holds an incident")
    if inc_kind != "none" and len(incs) != 1:
        bad(f"incident={inc_kind} needs exactly one incident, record has {len(incs)}")
    if inc_kind != "none" and incs:
        inc = incs[0]
        d, along = project(inc["lat"], inc["lon"], poly)
        rep = datetime.fromisoformat(inc["reported_at"])
        s = segs[0]
        if d > INCIDENT_NEAR_M:
            bad(f"incident is {d:.0f} m from the optimal route")
        if inc_kind in ("on_stretch", "seg1", "late"):
            if not (s["entry_km"] - STRETCH_TOL_KM <= along <= s["exit_km"] + STRETCH_TOL_KM):
                bad(f"incident at optimal km {along:.2f} is not on the bypassed stretch {s['entry_km']:.2f}-{s['exit_km']:.2f}")
            if inc_kind == "late":
                if (rep - seg_start[0]).total_seconds() < 60:
                    bad("incident=late but it was reported before (or at) the segment start")
            elif rep >= ts({"ts": t["pickup_at"]}):
                bad("incident on the stretch must be reported before pickup")
            if inc_kind == "seg1" and len(segs) > 1 and segs[1]["entry_km"] - STRETCH_TOL_KM <= along <= segs[1]["exit_km"] + STRETCH_TOL_KM:
                bad("incident=seg1 but the incident also sits on segment 2's stretch")
            m = re.search(r"Accident on (.+?) \(", inc["message"]) if c.get("templates") else None
            runs = road_runs(route, s["entry_km"], s["exit_km"])
            if m and runs and m.group(1).upper() != runs[0][0]:
                bad(f"incident message names {m.group(1)} but the bypassed stretch is mostly {runs[0][0].title()}")
        elif inc_kind == "decoy_far":
            gap = min(abs(along - sg) for s2 in segs for sg in (s2["entry_km"], s2["exit_km"]))
            if any(s2["entry_km"] - STRETCH_TOL_KM <= along <= s2["exit_km"] + STRETCH_TOL_KM for s2 in segs) or gap < 2.0:
                bad(f"decoy incident is {gap:.2f} km from a bypassed stretch (needs >= 2 km, off every stretch)")
            if rep >= seg_start[0]:
                bad("decoy incident reported after the segment started")
    # ---- band
    band = c["band"]
    bands = case["traffic"]["speed_bands"]
    if band:
        hits = [b for b in bands if b["speed_band"] == band]
        runs = road_runs(route, segs[0]["entry_km"], segs[0]["exit_km"])
        if not hits:
            bad(f"band={band} but no speed band {band} record")
        else:
            b = hits[0]
            if runs and b["road_name"] not in [n for n, _ in runs]:
                bad(f"band {band} is on {b['road_name']}, which is not on the bypassed stretch ({', '.join(n for n, _ in runs[:3])})")
            if datetime.fromisoformat(b["window_end"]) < ts({"ts": t["pickup_at"]}) or datetime.fromisoformat(b["window_start"]) > seg_start[0]:
                bad(f"band window {b['window_start'][11:19]}..{b['window_end'][11:19]} does not overlap pickup..segment start")
            if c.get("templates"):      # scenarios.py puts the band on the stretch's main road and backs it with a crawl before the detour
                if runs and b["road_name"] != runs[0][0]:
                    bad(f"band {band} is on {b['road_name']} but the bypassed stretch is mostly {runs[0][0]}")
                if datetime.fromisoformat(b["window_end"]) > seg_start[0] + timedelta(seconds=5):
                    bad(f"band window ends {b['window_end'][11:19]}, after the segment start")
                pre = [p["speed_kmh"] for p in trip_gps if seg_start[0] - timedelta(seconds=150) <= ts(p) < seg_start[0] and p["speed_kmh"] >= 5]
                lo, hi = {1: (0, 9), 2: (10, 19)}[band]
                if pre and not lo <= statistics.median(pre) <= hi + 1:
                    bad(f"band {band} but the GPS median in the 150 s before the detour is {statistics.median(pre):.1f} km/h")
    elif any(b["speed_band"] <= 2 for b in bands):
        bad("band=0 but a speed band <= 2 record exists")
    # ---- prior, threat, statements
    got = case["profiles"]["driver"]["route_disputes_upheld_90d"]
    if got != c["prior"]:
        bad(f"prior={c['prior']} but driver.route_disputes_upheld_90d = {got}")
    th = c["threat"]
    lines = {"driver": "Shut up", "trap": "find you"}
    for key, needle in lines.items():
        has = any(needle in m["text"] for m in chat)
        if th == key and not has:
            bad(f"threat={key} but no '{needle}' line in the chat")
        if th != key and has:
            bad(f"chat holds '{needle}' but threat={th}")
    if c.get("statement_consistent"):
        st, ds = case["dispute"]["statement"], case["driver_statement"]
        m = re.search(r"estimated (\d+) km .*?(\d+) km", st)
        if m and (int(m.group(1)) != round(route["total_km"]) or int(m.group(2)) != round(case["fare"]["distance_km"])):
            bad(f"rider statement quotes {m.group(1)} / {m.group(2)} km, record has {route['total_km']:.0f} / {case['fare']['distance_km']:.0f}")
        if case["fare"]["pricing"] == "fixed" and re.search(r"\bmeter\b|than the estimate|above the estimate|difference back", st):
            bad("fixed-fare trip but the rider's statement talks about the meter / paying more than the estimate")
        if "agreed" in ds and consent in ("none", "request_only") and stop == "none" and inc_kind == "none":
            bad("driver statement claims the rider agreed but the scenario has no agreement")
        if not segs and "longer route" not in st:
            pass
        if "flooding" in ds and c["weather"]["rain_mm"] < 10:
            bad("driver blames flooding but the weather record is not heavy rain")
    if c.get("no_stops") and st_all:
        bad(f"no stop expected but the trace holds {len(st_all)}")


def _check_noshow(case, c, errs, P):
    bad = errs.append
    t, gps, chat = case["trip"], case["gps"], case["chat"]
    acc, canc = datetime.fromisoformat(t["accepted_at"]), datetime.fromisoformat(t["cancelled_at"])
    if t["cancelled_by"] != c["cancelled_by"]:
        bad(f"cancelled_by {t['cancelled_by']} != {c['cancelled_by']}")
    dists = [hav_m((p["lat"], p["lon"]), P) for p in gps]
    nearest = min(dists)
    tap = datetime.fromisoformat(t["driver_pressed_here_at"]) if t["driver_pressed_here_at"] else None
    if c.get("tap") and not tap:
        bad("the story has an I'm Here tap but driver_pressed_here_at is null")
    if not c.get("tap") and tap:
        bad("the story has no I'm Here tap but driver_pressed_here_at is set")
    if tap:
        at = min(gps, key=lambda p: abs((ts(p) - tap).total_seconds()))
        d_tap = hav_m((at["lat"], at["lon"]), P)
        lo, hi = c.get("tap_distance_m", (0, 10 ** 9))
        if not lo <= d_tap <= hi:
            bad(f"at the tap the car is {d_tap:.0f} m from the pickup, story says {lo}-{hi} m")
        if "wait_after_tap_s" in c:
            lo, hi = c["wait_after_tap_s"]
            got = continuous_after_tap_s(gps, P, tap)
            if not lo <= got <= hi:
                bad(f"{got} s continuously inside {PICKUP_RADIUS_M} m after the tap, story says {lo}-{hi} s")
        if not (acc <= tap <= canc):
            bad("tap outside accepted..cancelled")
    if c.get("never_within_200m") and nearest <= PICKUP_RADIUS_M:
        bad(f"story says the driver never arrived but the trace comes within {nearest:.0f} m")
    if "wait_at_pin_s" in c:
        inside = [d <= PICKUP_RADIUS_M for d in dists]
        within = sum(5 for a, b in zip(inside, inside[1:]) if a and b)
        if within < c["wait_at_pin_s"]:
            bad(f"{within} s within {PICKUP_RADIUS_M} m, story says >= {c['wait_at_pin_s']} s at the pin")
    if "cancel_s" in c:
        got = int((canc - acc).total_seconds())
        if got != c["cancel_s"]:
            bad(f"cancelled {got} s after acceptance, story says {c['cancel_s']}")
    st = stops(gps)
    if c.get("driver") == "en_route":
        d0, d1 = dists[0], dists[-1]
        driven = sum(hav_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(gps, gps[1:]))
        if nearest <= PICKUP_RADIUS_M:
            bad(f"driver=en_route but the trace comes within {nearest:.0f} m of the pickup")
        if st:
            bad(f"driver=en_route but the car stood still: {[(x['duration_s'], x['start'][11:19]) for x in st]}")
        if d1 >= d0:
            bad(f"driver=en_route but the car ends farther from the pickup ({d1:.0f} m) than it started ({d0:.0f} m): it is driving away")
        if driven < 0.6 * c["cancel_s"] * 30 / 3.6:
            bad(f"driver=en_route but only {driven:.0f} m driven in {c['cancel_s']} s")
    if c.get("driver") == "at_pickup":
        if not st or min(hav_m((x["lat"], x["lon"]), P) for x in st) > 60:
            bad("driver=at_pickup but no stationary run within 60 m of the pickup")
        if tap and continuous_after_tap_s(gps, P, tap) < 180:
            bad("driver=at_pickup but under 180 s at the pin after the tap")
    if case["profiles"]["rider"]["no_show_disputes_upheld_90d"] != c["prior_ns"]:
        bad(f"prior_ns={c['prior_ns']} but rider.no_show_disputes_upheld_90d = {case['profiles']['rider']['no_show_disputes_upheld_90d']}")
    if c.get("fee_in_statement"):
        fee = case["fare"]["cancellation_fee"]
        if f"${fee:.2f}" not in case["dispute"]["statement"]:
            bad(f"rider statement does not name the ${fee:.2f} fee charged")
    kind = c.get("chat")
    need = {"two_more": "2 more minutes", "driver_claims": None, "threat": "regret"}.get(kind)
    if need and not any(need in m["text"] for m in chat):
        bad(f"chat={kind} but no '{need}' line")
    if kind == "driver_claims" and "5 minutes" not in (case["driver_statement"] or ""):
        bad("chat=driver_claims but the driver's statement does not claim 5 minutes")
    if kind != "threat" and any("regret" in m["text"] for m in chat):
        bad("chat holds an intimidating line the scenario did not script")
    if c.get("gps_hole_s"):
        gaps = [(ts(b) - ts(a)).total_seconds() for a, b in zip(gps, gps[1:]) if (ts(b) - ts(a)).total_seconds() > 5]
        if len(gaps) != 1 or abs(gaps[0] - c["gps_hole_s"]) > 10:
            bad(f"gps_hole_s={c['gps_hole_s']} but the trace's holes are {gaps}")
        elif tap and not (tap < ts(gps[[i for i, (a, b) in enumerate(zip(gps, gps[1:])) if (ts(b) - ts(a)).total_seconds() > 5][0]]) < canc):
            bad("the gps hole is not inside the wait")
    if c.get("policy"):
        pp = case.get("policy_params") or {}
        for k, v in c["policy"].items():
            if pp.get(k) != v:
                bad(f"policy_params.{k} = {pp.get(k)}, scenario says {v}")
        if case["fare"]["cancellation_fee"] != c["policy"].get("cancellation_fee", case["fare"]["cancellation_fee"]):
            bad("fare.cancellation_fee differs from the record-stated fee")


def _check_safety(case, c, errs, trip_gps, poly, P, D):
    bad = errs.append
    chat, kind = case["chat"], c["chat"]
    texts = [m["text"] for m in chat]
    need = {"driver_threat": ("lock the doors", "rider"), "rider_threat": ("punch", "driver")}.get(kind)
    if need:
        if not any(need[0] in x for x in texts):
            bad(f"chat={kind} but no '{need[0]}' line")
        if case["dispute"]["filed_by"] != need[1]:
            bad(f"chat={kind}: filed_by should be {need[1]}")
    if kind == "none" and chat:
        bad("chat=none but the record holds messages")
    if kind == "innocuous" and any(re.search(r"lock|punch|stupid|shut up|regret", x, re.I) for x in texts):
        bad("chat=innocuous but a line carries a threat hint")
    ds = case["driver_statement"] or ""
    if c.get("statement_threat") != ("stupid" in ds):
        bad(f"statement_threat={c.get('statement_threat')} but the driver's statement {'has' if 'stupid' in ds else 'lacks'} the insult")
    if segments(trip_gps, poly):
        bad("safety script: the trace leaves the optimal route")
    if stops(trip_gps, exclude=(P, D)):
        bad("safety script: the trip stops mid-way")


# ----------------------------------------------------------------------------------------------- label vs truth

def label_implications(hard: str) -> dict:
    """What the one-line `hard` label promises about the reference: {"ruling": set | None, "flag": bool | None}.
    Reads the part after the last '->' (the outcome), e.g. '... -> refund + flag_account', '... -> fee stands'."""
    tail = hard.split("->")[-1].strip().lower() if "->" in hard else ""
    out = {"ruling": None, "flag": None}
    if not tail:
        return out
    exempt = re.search(r"\bexempt\b", tail) and not re.search(r"not exempt|no exemption|does not exempt", tail)
    if "escalate" in tail or "a person decides" in tail:
        out["ruling"] = {"escalate"}
    elif re.search(r"no_action|fee stands|no refund|ruling stands", tail) or (exempt and "refund" not in tail):
        out["ruling"] = {"no_action"}
    elif re.search(r"refund|\bcounts\b", tail):
        out["ruling"] = {"refund_full", "refund_partial"}
    if "flag" in tail and "depends" not in tail:
        out["flag"] = "no flag" not in tail
    return out


def check_expect(expect: dict, truth: dict) -> list[str]:
    """The scenario's typed promise against the reference: {"ruling": "refund_partial" | "no_action" | "refund_full" |
    "escalate", "flag": bool}. It checks the derived answer; it never feeds it."""
    errs = []
    if expect.get("ruling") not in ("refund_partial", "no_action", "refund_full", "escalate"):
        errs.append(f"expect.ruling {expect.get('ruling')!r} is not an outcome")
    elif truth["ruling"] != expect["ruling"]:
        errs.append(f"expect promises {expect['ruling']} but the reference ruling is {truth['ruling']}")
    if expect.get("ruling") in ("no_action", "escalate") and truth.get("amount"):
        errs.append(f"expect promises no amount but the reference carries {truth['amount']}")
    if "flag" in expect and bool(truth.get("flag_account")) != bool(expect["flag"]):
        errs.append(f"expect says flag={expect['flag']} but the reference flag_account is {truth.get('flag_account')}")
    return errs


def check_label(hard: str, truth: dict) -> list[str]:
    """The `hard` label's promised outcome against the reference (ruling, amount, flag)."""
    imp = label_implications(hard)
    errs = []
    if not imp["ruling"]:
        errs.append("hard label does not state the expected outcome after '->' (escalate / refund / no_action / fee stands / exempt)")
    if imp["ruling"] and truth["ruling"] not in imp["ruling"]:
        errs.append(f"hard label promises {'/'.join(sorted(imp['ruling']))} but the reference ruling is {truth['ruling']}")
    if imp["ruling"] == {"no_action"} and truth.get("amount"):
        errs.append(f"hard label promises no refund but the reference carries an amount {truth['amount']}")
    if imp["flag"] is not None and bool(truth.get("flag_account")) != imp["flag"]:
        errs.append(f"hard label says {'flag' if imp['flag'] else 'no flag'} but the reference flag_account is {truth.get('flag_account')}")
    return errs
