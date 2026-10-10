"""
Fact tools: deterministic computations over one Case (spec 1.5).

    Case --(these functions, pure code)--> list[Fact] --(build_fact_table)--> FactTable

Every function here is a plain Python function with type hints and a docstring,
so any agent framework can wrap it with its own @tool decorator. Nothing here
calls an LLM. Facts carry a temporary id until build_fact_table() renumbers
them F1..Fn in a stable source order (gps -> timeline -> fare -> chat ->
traffic -> weather -> profile). Distances use haversine on WGS84.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.schemas import Case, DisputeType, Fact, FactSource, FactTable, GpsPoint

# ---------------------------------------------------------------------------
# constants (thresholds referenced by policy/policy.md)
# ---------------------------------------------------------------------------

RATES_PATH = Path(__file__).resolve().parents[2] / "data" / "rates.json"
DEFAULT_RATE_KM = 1.41          # SGD/km, used when data/rates.json is absent
STOP_MIN_S = 120                # a stationary run shorter than this is not a stop
STOP_RADIUS_M = 30              # a run is stationary while every point stays within this of its first point
DETOUR_MERGE_S = 120            # off-route runs separated by a shorter on-route gap are one detour
DETOUR_MIN_KM = 0.2             # detours adding less than this are polyline-matching noise
ENDPOINT_RADIUS_M = 100         # a stop this close to pickup/dropoff is boarding, not a stop
PICKUP_RADIUS_M = 200           # NS-1 / NS-2 arrival radius
OFF_ROUTE_M = 200               # a GPS point farther than this from the polyline is off-route
EARTH_RADIUS_M = 6_371_008.8

SOURCE_ORDER: tuple[FactSource, ...] = (
    "gps", "timeline", "fare", "chat", "traffic", "weather", "profile",
)

# LTA DataMall speed band -> km/h range
SPEED_BANDS: dict[int, tuple[int, Optional[int]]] = {
    1: (0, 9), 2: (10, 19), 3: (20, 29), 4: (30, 39),
    5: (40, 49), 6: (50, 59), 7: (60, 69), 8: (70, None),
}

GPS_GAP_S = 120                 # a hole in the trace longer than this is an evidence gap, not "nothing happened"
CADENCE_MIN_SAMPLES = 6         # samples needed before a trace's own sampling interval widens the hole threshold

# Words that only LOCATE a message for the reader. They never label it: whether a line is agreement, a request or a
# threat is a reading of its meaning, and readings belong to the court (advocates argue, the judge finds), not to code.
THREAT_HINT_WORDS = ("threat", "threaten", "kill", "hurt", "hit you", "beat you", "punch", "slap", "lock the door", "lock you",
                     "find you", "shut up", "idiot", "stupid", "harass", "regret")


# ---------------------------------------------------------------------------
# geometry / formatting helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _dist_pt(a: GpsPoint, lat: float, lon: float) -> float:
    return haversine_m(a.lat, a.lon, lat, lon)


def _path_km(points: list[GpsPoint]) -> float:
    return sum(haversine_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(points, points[1:])) / 1000


def _secs(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


def _t(ts: datetime, seconds: bool = False) -> str:
    return ts.strftime("%H:%M:%S" if seconds else "%H:%M")


def _dur(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def _track(case: Case, start: Optional[datetime], end: Optional[datetime]) -> list[GpsPoint]:
    """GPS points inside [start, end]; an open bound keeps everything on that side."""
    return [p for p in case.gps if (start is None or p.ts >= start) and (end is None or p.ts <= end)]


def _stationary_runs(points: list[GpsPoint]) -> list[tuple[GpsPoint, GpsPoint]]:
    """(first, last) point of each run that stays within STOP_RADIUS_M of its first point for >= STOP_MIN_S.
    Position, not the reported speed, defines "stationary": a parked car's GPS jitters at 0-3 km/h, and
    staying inside 30 m for two minutes already means a mean speed under 1 km/h. Works on sparse tracks too."""
    runs, start = [], None
    for i, p in enumerate(points):
        if start is not None and _dist_pt(p, points[start].lat, points[start].lon) > STOP_RADIUS_M:
            if _secs(points[start].ts, points[i - 1].ts) >= STOP_MIN_S:
                runs.append((points[start], points[i - 1]))
            start = None
        if start is None:
            start = i
    if start is not None and _secs(points[start].ts, points[-1].ts) >= STOP_MIN_S:
        runs.append((points[start], points[-1]))
    return runs


def _project(lat: float, lon: float, polyline: list[tuple[float, float]]) -> tuple[float, float]:
    """Distance (m) from a point to a polyline and the along-track position (km) of the nearest projection.
    Uses a local equirectangular frame centred on the point; accurate to well under 1 % at Singapore scale."""
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_540
    best_d, best_along, cum = math.inf, 0.0, 0.0
    for (alat, alon), (blat, blon) in zip(polyline, polyline[1:]):
        ax, ay = (alon - lon) * kx, (alat - lat) * ky
        bx, by = (blon - lon) * kx, (blat - lat) * ky
        vx, vy = bx - ax, by - ay
        seg = math.hypot(vx, vy)
        t = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * vx + ay * vy) / (seg * seg)))
        d = math.hypot(ax + t * vx, ay + t * vy)
        if d < best_d:
            best_d, best_along = d, cum + t * seg / 1000
        cum += seg / 1000
    return best_d, best_along


def _detours(points: list[GpsPoint], polyline: list[tuple[float, float]]) -> list[dict]:
    """Off-route segments: runs of points > OFF_ROUTE_M from the polyline, merged when the on-route gap
    between them is shorter than DETOUR_MERGE_S. For each, the km actually driven from the last on-route
    point to the next on-route point, minus the km of optimal route those two points bracket, is the extra
    distance the detour added. Segments adding < DETOUR_MIN_KM are dropped as map-matching noise."""
    if len(polyline) < 2 or len(points) < 2:
        return []
    proj = [_project(p.lat, p.lon, polyline) for p in points]
    runs, i, n = [], 0, len(points)
    while i < n:                                   # raw runs of off-route indices [i, j)
        if proj[i][0] <= OFF_ROUTE_M:
            i += 1
            continue
        j = i
        while j < n and proj[j][0] > OFF_ROUTE_M:
            j += 1
        if runs and _secs(points[runs[-1][1] - 1].ts, points[i].ts) <= DETOUR_MERGE_S:
            runs[-1] = (runs[-1][0], j)
        else:
            runs.append((i, j))
        i = j
    out = []
    for i, j in runs:
        entry, exit_ = max(i - 1, 0), min(j, n - 1)
        driven = _path_km(points[entry:exit_ + 1])
        skipped = abs(proj[exit_][1] - proj[entry][1])
        if driven - skipped < DETOUR_MIN_KM:
            continue
        out.append({
            "start": points[entry].ts, "end": points[exit_].ts,
            "driven_km": round(driven, 2), "route_km": round(skipped, 2),
            "extra_km": round(driven - skipped, 2),
            "max_off_route_m": round(max(proj[k][0] for k in range(i, j))),
            "entry_km": round(min(proj[entry][1], proj[exit_][1]), 3),   # along-track km where the car left the route
            "exit_km": round(max(proj[entry][1], proj[exit_][1]), 3),    # ... and where it rejoined
        })
    return out


def keyword_hint(text: str) -> Optional[str]:
    """The first threat-hint word in a text, or None. A locator for human and judge attention, never a finding."""
    low = text.lower()
    return next((w for w in THREAT_HINT_WORDS if w in low), None)


def _hole_threshold_s(points: list[GpsPoint]) -> tuple[float, Optional[float]]:
    """(hole threshold in seconds, median sampling interval or None).

    A hole is a gap longer than GPS_GAP_S AND longer than twice the trace's own median interval: a record sampled every
    3 min (the organisers' sample) has no hole at 3 min, while a 5 s trace has one at anything over 2 min. The cadence
    rule needs CADENCE_MIN_SAMPLES samples; with fewer, GPS_GAP_S alone applies (two samples 220 s apart are a hole)."""
    if len(points) < CADENCE_MIN_SAMPLES:
        return GPS_GAP_S, None
    ints = sorted(_secs(a.ts, b.ts) for a, b in zip(points, points[1:]))
    med = ints[len(ints) // 2]
    return max(GPS_GAP_S, 2 * med), med


def _gaps(points: list[GpsPoint]) -> list[tuple[GpsPoint, GpsPoint]]:
    """Consecutive samples further apart than the hole threshold: stretches the trace does not cover."""
    thr, _ = _hole_threshold_s(points)
    return [(a, b) for a, b in zip(points, points[1:]) if _secs(a.ts, b.ts) > thr]


def _coverage_facts(points: list[GpsPoint], start: Optional[datetime], end: Optional[datetime], what: str) -> list[Fact]:
    """gps-cadence (sparse records only, so the reader knows what a hole means here) and gps-coverage when the trace
    starts later than `start` or ends earlier than `end` by more than the hole threshold."""
    facts: list[Fact] = []
    if not points:
        return facts
    thr, med = _hole_threshold_s(points)
    if med is not None and med > 30:
        facts.append(Fact(id="gps-cadence", source="gps",
                          text=f"GPS in this record is sampled about every {_dur(med)} ({len(points)} samples over the {what}); a gap counts as a hole only beyond {_dur(thr)}.",
                          value={"median_interval_s": round(med), "hole_threshold_s": round(thr), "samples": len(points)}))
    head = _secs(start, points[0].ts) if start else 0.0
    tail = _secs(points[-1].ts, end) if end else 0.0
    if head > thr or tail > thr:
        parts = []
        if head > thr:
            parts.append(f"first sample {_dur(head)} after {_t(start, True)}")
        if tail > thr:
            parts.append(f"last sample {_dur(tail)} before {_t(end, True)}")
        facts.append(Fact(id="gps-coverage", source="gps",
                          text=f"GPS trace does not cover the whole {what}: {'; '.join(parts)}. What happened outside the covered stretch is not on record.",
                          value={"uncovered_start_s": round(head) if head > thr else 0, "uncovered_end_s": round(tail) if tail > thr else 0,
                                 "hole_threshold_s": round(thr)}))
    return facts


def _load_rates() -> tuple[dict, str]:
    """Per-km / per-minute rates from data/rates.json (accepts rate_per_km | rate_km | per_km and
    waiting_rate_per_min | rate_wait), else the documented default with a note the fact text carries."""
    if RATES_PATH.exists():
        raw = json.loads(RATES_PATH.read_text())
        pick = lambda *keys: next((raw[k] for k in keys if k in raw), None)
        rate_km, rate_wait = pick("rate_per_km", "rate_km", "per_km"), pick("waiting_rate_per_min", "rate_wait")
        if rate_km is not None:
            return {"rate_km": float(rate_km), "rate_wait": rate_wait}, ""
    return {"rate_km": DEFAULT_RATE_KM, "rate_wait": None}, f"; default rate, {RATES_PATH.name} not found"


# ---------------------------------------------------------------------------
# the six fact tools
# ---------------------------------------------------------------------------

def get_route_facts(case: Case) -> list[Fact]:
    """Route facts from the GPS track between pickup and drop-off (source: gps).

    Produces: actual km vs optimal route km with the excess ratio (RD-1 inputs);
    every stop away from the pickup/drop-off points (position held within 30 m
    for >= 120 s, i.e. mean speed < 1 km/h) with location and duration; actual vs estimated duration; and, for each
    off-route segment, the extra km it added over the optimal route.
    """
    trip, facts = case.trip, []
    pts = _track(case, trip.pickup_at, trip.dropoff_at)
    if len(pts) < 2:
        facts.append(Fact(id="gps-missing", source="gps",
                          text="No GPS trace on record for the trip: route and distance cannot be measured.",
                          value={"gps_missing": True, "points": len(pts)}))
    for k, (a, b) in enumerate(_gaps(pts), 1):
        facts.append(Fact(id=f"gps-gap-{k}", source="gps",
                          text=f"GPS trace has no samples between {_t(a.ts, True)} and {_t(b.ts, True)} ({_dur(_secs(a.ts, b.ts))}): what happened in that stretch is not on record.",
                          value={"gps_gap_s": round(_secs(a.ts, b.ts)), "gap_start": a.ts.isoformat(), "gap_end": b.ts.isoformat()}))
    facts += _coverage_facts(pts, trip.pickup_at, trip.dropoff_at, "trip")
    if len(pts) >= 2:
        actual, optimal = _path_km(pts), case.route.total_km
        excess = round(actual - optimal, 2) or 0.0          # `or 0.0` turns -0.0 into 0.0
        pct = round(excess / optimal * 100, 1) if optimal else 0.0
        shown = round(round(actual, 1) - round(optimal, 1), 1) or 0.0   # the text's delta is the difference of the numbers it prints
        facts.append(Fact(
            id="gps-distance", source="gps",
            text=f"Actual distance {actual:.1f} km vs optimal route {optimal:.1f} km: {shown:+.1f} km ({pct:+.0f}%).",
            value={"actual_km": round(actual, 2), "optimal_km": optimal,
                   "excess_km": round(excess, 2), "excess_pct": round(pct, 1)},
        ))
    for k, (a, b) in enumerate(_stationary_runs(pts), 1):
        d_pick = _dist_pt(a, trip.pickup.lat, trip.pickup.lon)
        d_drop = _dist_pt(a, trip.dropoff.lat, trip.dropoff.lon)
        if min(d_pick, d_drop) <= ENDPOINT_RADIUS_M:
            continue
        dur = _secs(a.ts, b.ts)
        facts.append(Fact(
            id=f"gps-stop-{k}", source="gps",
            text=(f"Stationary {_dur(dur)} at ({a.lat:.4f}, {a.lon:.4f}), {_t(a.ts)}–{_t(b.ts)}. "
                  f"Not a pickup or drop-off point ({d_pick:.0f} m from pickup, {d_drop:.0f} m from drop-off)."),
            value={"lat": a.lat, "lon": a.lon, "start": a.ts.isoformat(), "end": b.ts.isoformat(),
                   "duration_s": round(dur), "m_from_pickup": round(d_pick), "m_from_dropoff": round(d_drop)},
        ))
    if trip.pickup_at and trip.dropoff_at:
        actual_min = _secs(trip.pickup_at, trip.dropoff_at) / 60
        delta = actual_min - trip.estimated_min
        facts.append(Fact(
            id="gps-duration", source="gps",
            text=f"Trip duration {actual_min:.1f} min vs estimated {trip.estimated_min:.1f} min ({round(round(actual_min, 1) - round(trip.estimated_min, 1), 1):+.1f} min).",
            value={"actual_min": round(actual_min, 1), "estimated_min": trip.estimated_min, "delta_min": round(delta, 1)},
        ))
    for k, d in enumerate(_detours(pts, case.route.polyline), 1):
        facts.append(Fact(
            id=f"gps-detour-{k}", source="gps",
            text=(f"Off-route segment {_t(d['start'])}–{_t(d['end'])}: {d['driven_km']:.2f} km driven where the optimal "
                  f"route covers {d['route_km']:.2f} km, adding {d['extra_km']:.2f} km "
                  f"(up to {d['max_off_route_m']} m from the optimal route)."),
            value={**d, "start": d["start"].isoformat(), "end": d["end"].isoformat()},
        ))
    return facts


def get_no_show_facts(case: Case) -> list[Fact]:
    """No-show facts from the driver's track after acceptance and the trip timeline (sources: gps, timeline).

    Produces: the driver's closest approach to the pickup point and when; the first
    time within 200 m and the cumulative seconds spent within 200 m before cancellation
    (NS-1 / NS-2 inputs); stationary runs with their distance from pickup; who cancelled
    and when, relative to acceptance; and the gap between recorded arrival and cancellation.
    """
    trip, pk, facts = case.trip, case.trip.pickup, []
    pts = _track(case, trip.accepted_at, trip.cancelled_at)
    if not pts:
        facts.append(Fact(id="gps-missing", source="gps",
                          text="No GPS trace on record between acceptance and cancellation: where the driver was cannot be measured.",
                          value={"gps_missing": True, "points": 0}))
    for k, (a, b) in enumerate(_gaps(pts), 1):
        facts.append(Fact(id=f"gps-gap-{k}", source="gps",
                          text=f"GPS trace has no samples between {_t(a.ts, True)} and {_t(b.ts, True)} ({_dur(_secs(a.ts, b.ts))}).",
                          value={"gps_gap_s": round(_secs(a.ts, b.ts)), "gap_start": a.ts.isoformat(), "gap_end": b.ts.isoformat()}))
    facts += _coverage_facts(pts, trip.driver_pressed_here_at or trip.accepted_at, trip.cancelled_at, "wait")
    if pts:
        dists = [_dist_pt(p, pk.lat, pk.lon) for p in pts]
        i_min = min(range(len(pts)), key=dists.__getitem__)
        near = dists[i_min]
        tail = f" Driver never came within {PICKUP_RADIUS_M} m." if near > PICKUP_RADIUS_M else ""
        facts.append(Fact(
            id="gps-nearest", source="gps",
            text=f"Driver's closest approach to pickup: {near:.0f} m at {_t(pts[i_min].ts, True)}.{tail}",
            value={"nearest_m": round(near), "at": pts[i_min].ts.isoformat(), "within_200m": near <= PICKUP_RADIUS_M},
        ))
        inside = [d <= PICKUP_RADIUS_M for d in dists]
        within_s = sum(_secs(a.ts, b.ts) for a, b, ia, ib in zip(pts, pts[1:], inside, inside[1:]) if ia and ib)
        if any(inside):
            first = pts[inside.index(True)]
            facts.append(Fact(
                id="gps-within", source="gps",
                text=(f"Driver first within {PICKUP_RADIUS_M} m of pickup at {_t(first.ts, True)}; "
                      f"cumulative time within {PICKUP_RADIUS_M} m before cancellation: {_dur(within_s)}."),
                value={"first_within_200m_at": first.ts.isoformat(), "within_200m_s": round(within_s)},
            ))
        for k, (a, b) in enumerate(_stationary_runs(pts), 1):
            d = _dist_pt(a, pk.lat, pk.lon)
            facts.append(Fact(
                id=f"gps-stop-{k}", source="gps",
                text=(f"Driver stationary {_t(a.ts, True)}–{_t(b.ts, True)} ({_dur(_secs(a.ts, b.ts))}) "
                      f"at ({a.lat:.4f}, {a.lon:.4f}), {d:.0f} m from pickup."),
                value={"lat": a.lat, "lon": a.lon, "start": a.ts.isoformat(), "end": b.ts.isoformat(),
                       "duration_s": round(_secs(a.ts, b.ts)), "m_from_pickup": round(d)},
            ))
    if trip.cancelled_at:
        since_accept = _secs(trip.accepted_at, trip.cancelled_at)
        fee = case.fare.cancellation_fee
        fee_txt = f" Cancellation fee on record: ${fee:.2f}." if fee else " No cancellation fee on record."
        facts.append(Fact(
            id="tl-cancel", source="timeline",
            text=(f"Accepted {_t(trip.accepted_at, True)}. Cancelled by {trip.cancelled_by} at "
                  f"{_t(trip.cancelled_at, True)} ({_dur(since_accept)} after acceptance).{fee_txt}"),
            value={"accepted_at": trip.accepted_at.isoformat(), "cancelled_at": trip.cancelled_at.isoformat(),
                   "cancelled_by": trip.cancelled_by, "s_after_accept": round(since_accept), "cancellation_fee": fee},
        ))
        if trip.driver_arrived_at:
            gap = _secs(trip.driver_arrived_at, trip.cancelled_at)
            facts.append(Fact(
                id="tl-arrival", source="timeline",
                text=f"Platform recorded driver arrival at {_t(trip.driver_arrived_at, True)}; cancelled {_dur(gap)} after arrival.",
                value={"driver_arrived_at": trip.driver_arrived_at.isoformat(), "s_arrival_to_cancel": round(gap)},
            ))
        else:
            facts.append(Fact(
                id="tl-arrival", source="timeline",
                text="driver_arrived_at is null: the platform never recorded the driver at the pickup point.",
                value={"driver_arrived_at": None, "s_arrival_to_cancel": None},
            ))
        if trip.driver_pressed_here_at:
            at_tap = min(pts, key=lambda p: abs(_secs(p.ts, trip.driver_pressed_here_at))) if pts else None
            d_tap = _dist_pt(at_tap, pk.lat, pk.lon) if at_tap else None
            after = [p for p in pts if p.ts >= trip.driver_pressed_here_at]
            cont = 0.0   # continuous seconds inside the radius from the tap until the first exit (or cancellation)
            left = False
            for a, b in zip(after, after[1:]):
                if _dist_pt(a, pk.lat, pk.lon) <= PICKUP_RADIUS_M and _dist_pt(b, pk.lat, pk.lon) <= PICKUP_RADIUS_M:
                    cont += _secs(a.ts, b.ts)
                else:
                    left = True
                    break
            # the wait is what the samples show. The stretch between the last sample and the cancellation is NOT counted
            # as waiting, except when it is no longer than one sampling interval (the trace reaches the cancellation to
            # within a sample); a longer uncovered tail is reported so the engine can refuse to decide on it.
            if after:
                tail = _secs(after[-1].ts, trip.cancelled_at) if (trip.cancelled_at and not left) else 0.0
            else:
                # not one sample after the arrival confirmation: the whole wait is unrecorded, not "0 s of waiting"
                tail = _secs(trip.driver_pressed_here_at, trip.cancelled_at) if trip.cancelled_at else 0.0
            slack = _hole_threshold_s(pts)[1] or 5.0
            if 0 < tail <= slack and after and _dist_pt(after[-1], pk.lat, pk.lon) <= PICKUP_RADIUS_M:
                cont += tail; tail = 0.0
            auto = trip.arrival_confirmed_by == "platform_auto"
            how = (f"Platform auto-confirmed the driver's arrival (GPS within {trip.arrival_radius_m or PICKUP_RADIUS_M} m) at" if auto
                   else "Driver tapped \"I'm Here\" at")
            facts.append(Fact(
                id="tl-here", source="timeline",
                text=(f"{how} {_t(trip.driver_pressed_here_at, True)}"
                      + (f", {d_tap:.0f} m from the pickup point at that moment; stayed within {PICKUP_RADIUS_M} m for {_dur(cont)} after {'that confirmation' if auto else 'the tap'}." if d_tap is not None else ".")),
                value={"driver_pressed_here_at": trip.driver_pressed_here_at.isoformat(),
                       "arrival_confirmed_by": trip.arrival_confirmed_by or "driver_tap",
                       "m_from_pickup_at_tap": None if d_tap is None else round(d_tap),
                       "within_200m_after_tap_s": round(cont),
                       "left_radius": left,                       # the car left the 200 m radius before the cancellation
                       "tail_uncovered_s": round(tail)},          # seconds between the last in-radius sample and the cancellation that no sample covers
            ))
        else:
            facts.append(Fact(
                id="tl-here", source="timeline",
                text="No arrival confirmation on record: the driver never tapped \"I'm Here\" and the platform recorded no automatic arrival (driver_pressed_here_at is null).",
                value={"driver_pressed_here_at": None},
            ))
        if trip.wait_started_at and trip.wait_expired_at:
            w = _secs(trip.wait_started_at, trip.wait_expired_at)
            facts.append(Fact(
                id="tl-wait", source="timeline",
                text=(f"Platform wait timer: started {_t(trip.wait_started_at, True)}, free period expired {_t(trip.wait_expired_at, True)} ({_dur(w)})"
                      + (f"; fee applied {_t(trip.fee_applied_at, True)}." if trip.fee_applied_at else ".")),
                value={"wait_started_at": trip.wait_started_at.isoformat(), "wait_expired_at": trip.wait_expired_at.isoformat(), "wait_window_s": round(w),
                       "fee_applied_at": trip.fee_applied_at.isoformat() if trip.fee_applied_at else None},
            ))
    return facts


def get_fare_facts(case: Case) -> list[Fact]:
    """Fare facts from the billing record (source: fare).

    Produces: the excess distance billed beyond the optimal route converted to SGD at
    the per-km rate from data/rates.json (falls back to 1.41 and says so in the text);
    the waiting fee; the cancellation fee; the surge multiplier; and the total breakdown.
    """
    f, facts = case.fare, []
    rates, note = _load_rates()
    rate_km = float(rates["rate_km"])
    if f.distance_km and f.distance_fare:
        rate_km, note = f.distance_fare / f.distance_km, ", this trip's distance fare ÷ distance km"   # the rate RD-2 uses; rates.json only when the fare record cannot give one
    if f.distance_km or f.distance_fare:
        excess_km = round(f.distance_km - case.route.total_km, 2)
        amount = round(max(excess_km, 0) * rate_km, 2)          # from the printed km, so a reader's arithmetic reproduces it
        text = (f"Excess distance billed ${amount:.2f} ({excess_km:.2f} km × ${rate_km:.4f}/km{note})."
                if excess_km > 0 else
                f"Billed distance {f.distance_km:.1f} km does not exceed the optimal route ({case.route.total_km:.1f} km).")
        facts.append(Fact(id="fare-excess", source="fare", text=text,
                          value={"billed_km": f.distance_km, "optimal_km": case.route.total_km,
                                 "excess_km": round(excess_km, 2), "excess_amount": round(amount, 2), "rate_km": rate_km}))
    if f.waiting_fee:
        rate_wait = rates.get("rate_wait")
        mins = f" ({f.waiting_fee / rate_wait:.1f} min × ${rate_wait:.2f}/min)" if rate_wait else ""
        facts.append(Fact(id="fare-wait", source="fare", text=f"Waiting fee billed ${f.waiting_fee:.2f}{mins}.",
                          value={"waiting_fee": f.waiting_fee}))
    if f.cancellation_fee:
        facts.append(Fact(id="fare-cancel", source="fare", text=f"Cancellation fee charged: ${f.cancellation_fee:.2f}.",
                          value={"cancellation_fee": f.cancellation_fee}))
    surge = f.surge_multiplier
    facts.append(Fact(id="fare-surge", source="fare",
                      text=f"Surge multiplier {surge:.1f}×{' (no surge)' if surge == 1 else ''}.",
                      value={"surge_multiplier": surge}))
    if f.total:
        facts.append(Fact(
            id="fare-total", source="fare",
            text=(f"Total charged ${f.total:.2f} {f.currency}: base ${f.base_fare:.2f}, distance ${f.distance_fare:.2f} "
                  f"({f.distance_km:.2f} km), time ${f.time_fare:.2f} ({f.time_min:.1f} min), waiting ${f.waiting_fee:.2f}, "
                  f"platform ${f.platform_fee:.2f}, discount ${f.discount:.2f}."),
            value=f.model_dump(),
        ))
    return facts


def get_chat_facts(case: Case) -> list[Fact]:
    """Chat facts: every in-app message verbatim, numbered and timestamped, plus the driver's written statement (source: chat).

    Code records who said what and when, and whether the record is complete (every message carries a time). What a
    message MEANS — agreement, a request, a threat — is not computed here: the advocates argue it and the judge finds
    it (RD-3, RD-5, SAFE-1). A threat-hint word only marks a line for attention (value["keyword_hint"]); it is not a
    finding and no rule reads it. User-submitted content: system records (gps / timeline / fare) override it when they conflict.
    """
    facts = []
    for i, m in enumerate(case.chat, 1):
        hint = keyword_hint(m.text)
        when = _t(m.ts) if m.ts else "time not recorded"
        facts.append(Fact(id=f"chat-{i}", source="chat",
                          text=f"Chat #{i} {when} {m.sender}{' [call]' if m.kind == 'call' else ''}: “{m.text}”",
                          value={"idx": i, "from": m.sender, "ts": m.ts.isoformat() if m.ts else None, "kind": m.kind,
                                 **({"keyword_hint": hint} if hint else {})}))
    untimed = sum(1 for m in case.chat if m.ts is None)
    if not case.chat:
        facts.append(Fact(id="chat-none", source="chat", text="No in-app chat messages between rider and driver.",
                          value={"count": 0, "complete": True, "untimed": 0}))
    else:
        facts.append(Fact(id="chat-record", source="chat",
                          text=(f"Chat record: {len(case.chat)} message(s), every one timestamped." if not untimed else
                                f"Chat record: {len(case.chat)} message(s), {untimed} without a timestamp — whether they came before or after the events in dispute is not on record."),
                          value={"count": len(case.chat), "complete": untimed == 0, "untimed": untimed}))
    calls = [m for m in case.chat if m.kind == "call"]
    if calls:
        by = {s: sum(1 for m in calls if m.sender == s) for s in ("driver", "rider")}
        replies = {s: sum(1 for m in case.chat if m.sender == s and m.kind == "message") for s in ("driver", "rider")}
        facts.append(Fact(id="chat-calls", source="chat",
                          text=f"Call attempts logged in the chat: driver {by['driver']}, rider {by['rider']}; messages sent: driver {replies['driver']}, rider {replies['rider']}.",
                          value={"calls_driver": by["driver"], "calls_rider": by["rider"], "messages_driver": replies["driver"], "messages_rider": replies["rider"]}))
    if case.driver_statement:
        hint = keyword_hint(case.driver_statement)
        facts.append(Fact(id="chat-driver-statement", source="chat",
                          text=f"Driver statement (written after the trip, not part of the chat): “{case.driver_statement}”",
                          value={"from": "driver", "statement": True, **({"keyword_hint": hint} if hint else {})}))
    return facts


def get_traffic_facts(case: Case) -> list[Fact]:
    """Traffic facts: LTA speed bands translated to km/h ranges, incidents with their distance from
    the optimal route, and the weather record (sources: traffic, weather).

    Speed band 1 (0–9 km/h) is reported as severe congestion, which is what RD-4 asks for.
    Emits an explicit "none recorded" fact when there are no bands or incidents so the
    absence is citable.
    """
    facts = []
    for k, sb in enumerate(case.traffic.speed_bands, 1):
        lo, hi = SPEED_BANDS[sb.speed_band]
        rng = f"{lo}–{hi} km/h" if hi is not None else f"{lo}+ km/h"
        severe = sb.speed_band == 1
        facts.append(Fact(
            id=f"traffic-band-{k}", source="traffic",
            text=(f"{sb.road_name} (category {sb.road_category}) speed band {sb.speed_band} ({rng}) during "
                  f"{_t(sb.window_start)}–{_t(sb.window_end)}.{' Severe congestion.' if severe else ''}"),
            value={"road_name": sb.road_name, "speed_band": sb.speed_band, "kmh_min": lo, "kmh_max": hi,
                   "severe": severe, "window_start": sb.window_start.isoformat(), "window_end": sb.window_end.isoformat()},
        ))
    if not case.traffic.speed_bands:
        facts.append(Fact(id="traffic-band-none", source="traffic",
                          text="No speed band records for the route during the trip window.", value={"count": 0}))
    for k, inc in enumerate(case.traffic.incidents, 1):
        d_route, _ = _project(inc.lat, inc.lon, case.route.polyline) if len(case.route.polyline) >= 2 else (math.inf, 0)
        d_pick = haversine_m(inc.lat, inc.lon, case.trip.pickup.lat, case.trip.pickup.lon)
        where = f"{d_route:.0f} m from the optimal route" if d_route != math.inf else f"{d_pick:.0f} m from pickup"
        facts.append(Fact(
            id=f"traffic-incident-{k}", source="traffic",
            text=f"{inc.type} reported {_t(inc.reported_at)} at ({inc.lat:.4f}, {inc.lon:.4f}), {where}: {inc.message}",
            value={"type": inc.type, "lat": inc.lat, "lon": inc.lon, "reported_at": inc.reported_at.isoformat(),
                   "m_from_route": None if d_route == math.inf else round(d_route), "m_from_pickup": round(d_pick)},
        ))
    if not case.traffic.incidents:
        facts.append(Fact(id="traffic-incident-none", source="traffic",
                          text="No traffic incidents recorded near the route during the trip window.", value={"count": 0}))
    w = case.weather
    facts.append(Fact(id="weather", source="weather",
                      text=(f"Weather: {w.description}, {w.rain_mm:.1f} mm rain." if "not in the sample" not in (w.description or "").lower()
                            else "Weather: not in the sample (no rain figure on record)."),
                      value={"rain_mm": w.rain_mm, "description": w.description}))
    return facts


def get_profile_facts(case: Case) -> list[Fact]:
    """Profile facts for both parties: account age, rating, 90-day dispute counts (source: profile).

    Profile facts may support an outcome or an account flag (RD-6, NS-2), never decide the case alone.
    """
    r, d = case.profiles.rider, case.profiles.driver
    win = ((case.provenance or {}).get("history_window") if isinstance(getattr(case, "provenance", None), dict) else None) or "90 d"
    w = f"in {win}" if win == "90 d" else f"on record ({win})"
    return [
        Fact(id="profile-rider", source="profile",
             text=(f"Rider: account age {r.account_age_days} d ({r.account_age_days / 365:.1f} y), rating {r.rating}, "
                   f"{r.disputes_90d} disputes {w}, {r.disputes_upheld_90d} upheld "
                   f"(route: {r.route_disputes_upheld_90d}, no-show: {r.no_show_disputes_upheld_90d})."),
             value={"party": "rider", "history_window": win, **r.model_dump()}),
        Fact(id="profile-driver", source="profile",
             text=(f"Driver: account age {d.account_age_days} d ({d.account_age_days / 365:.1f} y), rating {d.rating}, "
                   f"{d.trips_90d} trips {w}, {d.disputes_90d} disputes, {d.disputes_upheld_90d} upheld "
                   f"(route: {d.route_disputes_upheld_90d}, no-show: {d.no_show_disputes_upheld_90d})."),
             value={"party": "driver", "history_window": win, **d.model_dump()}),
    ]


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

FactTool = Callable[[Case], list[Fact]]

TOOLS_BY_TYPE: dict[DisputeType, tuple[FactTool, ...]] = {
    "route_deviation": (get_route_facts, get_fare_facts, get_chat_facts, get_traffic_facts, get_profile_facts),
    "no_show": (get_no_show_facts, get_fare_facts, get_chat_facts, get_traffic_facts, get_profile_facts),
    "safety": (get_chat_facts, get_route_facts, get_profile_facts),
}

# Which FactTable sources each agent-facing tool name returns (spec 3.x: advocates read slices).
TOOL_SOURCES: dict[str, tuple[FactSource, ...]] = {
    "get_route_facts": ("gps",),
    "get_no_show_facts": ("gps", "timeline"),
    "get_fare_facts": ("fare",),
    "get_chat_facts": ("chat",),
    "get_traffic_facts": ("traffic", "weather"),
    "get_profile_facts": ("profile",),
}


def build_fact_table(case: Case) -> FactTable:
    """Run the fact tools relevant to the dispute type and number the facts F1..Fn.

    Order is stable: facts are grouped by SOURCE_ORDER (gps, timeline, fare, chat,
    traffic, weather, profile) and keep their within-tool order, so the same Case
    always yields the same ids. Temporary tool ids are discarded here.
    """
    facts = [f for tool in TOOLS_BY_TYPE[case.dispute.type] for f in tool(case)]
    facts.sort(key=lambda f: SOURCE_ORDER.index(f.source))  # stable
    numbered = [f.model_copy(update={"id": f"F{i}"}) for i, f in enumerate(facts, 1)]
    return FactTable(case_id=case.case_id, dispute_type=case.dispute.type, facts=numbered)


def facts_for_tool(table: FactTable, tool_name: str) -> list[Fact]:
    """The slice of a built FactTable an agent-facing tool returns (see TOOL_SOURCES)."""
    sources = TOOL_SOURCES[tool_name]
    return [f for f in table.facts if f.source in sources]
