"""Turn a route polyline into a 5 s GPS trace with injected stops / congestion.

build_trajectory() drives the polyline from `start` and reaches its end exactly `total_s` seconds later.
Stops pin the vehicle to a coordinate (a vertex of the polyline) from `start_s` for `duration_s`; the
cruising speed of each leg between stops is solved from the time budget, congestion zones run at their
own fixed speed. A no-show is just a polyline that ends at the parking spot plus a Stop that lasts until
the cancellation: nothing is left to drive after it.
"""
from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from route_provider import M_PER_DEG_LAT, haversine_m, m_per_deg_lon


@dataclass
class Stop:
    lat: float
    lon: float
    start_s: int            # seconds after `start` when the vehicle comes to rest
    duration_s: int
    jitter_m: float = 0.0   # GPS wander while parked (0 = identical points -> speed 0)
    anchor_s: int | None = None      # offset within the stop that sits exactly on (lat, lon)
    away_from: tuple | None = None   # wander only on the far side from this point (keeps anchor the closest sample)


@dataclass
class Congestion:
    from_km: float
    to_km: float
    speed_kmh: float


def profile_time_s(profile, d_a: float, d_b: float) -> float:
    """Seconds to drive metres d_a..d_b of a polyline at the profile's speeds ([(from_m, to_m, kmh)], contiguous)."""
    t = 0.0
    for lo, hi, kmh in profile:
        a, b = max(lo, d_a), min(hi, d_b)
        if b > a:
            t += (b - a) / (kmh / 3.6)
    return t


def _profile_kmh(profile, d: float) -> float:
    i = bisect.bisect_right([p[0] for p in profile], d) - 1
    return profile[max(0, min(i, len(profile) - 1))][2]


def build_trajectory(polyline, start: datetime, total_s: int, stops=(), congestion=(), step_s: int = 5,
                     seed: int = 0, profile=None, end_at_rest: bool = True) -> list[dict]:
    """`profile` = [(from_m, to_m, kmh)] along the polyline: each leg's speeds follow it (road class), scaled to the
    leg's time budget; None = one cruising speed per leg (the demo cases). `end_at_rest=False` keeps the real speed on
    the last sample (a car still moving when the record ends)."""
    pts = [tuple(p) for p in polyline]
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + haversine_m(a, b))
    total_len = cum[-1]
    rng = random.Random(seed)

    legs, d_prev, t_prev = [], 0.0, 0
    for st in sorted(stops, key=lambda s: s.start_s):
        i = min(range(len(pts)), key=lambda k: haversine_m(pts[k], (st.lat, st.lon)))
        legs.append((d_prev, cum[i], t_prev, st.start_s, st))
        d_prev, t_prev = cum[i], st.start_s + st.duration_s
    legs.append((d_prev, total_len, t_prev, total_s, None))

    samples = [(0, pts[0])]  # (offset_s, (lat, lon))
    for d_a, d_b, t_a, t_b, st in legs:
        if d_b - d_a > 0.5:
            samples.extend(_drive(pts, cum, d_a, d_b, t_a, t_b, congestion, step_s, profile))
            if st is not None:
                samples.pop()  # the arrival tick is re-emitted by _rest (so it gets the stop's jitter/anchor rule)
        elif t_b > t_a:  # nothing to drive but time to burn (only if a stop was placed at the start)
            raise ValueError(f"leg {d_a:.0f}->{d_b:.0f} m has no length but {t_b - t_a} s of time")
        if st is not None:
            samples.extend(_rest(st, rng, step_s))

    out, prev = [], None
    for off, (lat, lon) in samples:
        lat, lon = round(lat, 6), round(lon, 6)
        speed = 0.0 if prev is None else haversine_m(prev, (lat, lon)) / step_s * 3.6
        out.append({"ts": (start + timedelta(seconds=off)).isoformat(), "lat": lat, "lon": lon,
                    "speed_kmh": round(speed, 1)})
        prev = (lat, lon)
    if end_at_rest:
        out[-1]["speed_kmh"] = 0.0  # arrived / cancelled: the vehicle is at rest at the last sample
    return out


def _drive(pts, cum, d_a, d_b, t_a, t_b, congestion, step_s, profile=None):
    n = round((t_b - t_a) / step_s)
    if n <= 0:
        raise ValueError(f"leg {d_a:.0f}->{d_b:.0f} m gets no time ({t_a}..{t_b} s)")
    zones = []
    for z in congestion:
        lo, hi = max(d_a, z.from_km * 1000), min(d_b, z.to_km * 1000)
        if hi > lo:
            zones.append((lo, hi, z.speed_kmh / 3.6))
    zone_len = sum(hi - lo for lo, hi, _ in zones)
    zone_t = sum((hi - lo) / v for lo, hi, v in zones)
    free_t = n * step_s - zone_t
    if free_t <= 0 or (d_b - d_a - zone_len) < 0:
        raise ValueError(f"congestion does not fit in leg {d_a:.0f}->{d_b:.0f} m / {n * step_s} s")
    v_base = (d_b - d_a - zone_len) / free_t
    if profile:
        # time the profile needs outside the zones; its speeds are scaled so the leg fits its budget
        prof_t = profile_time_s(profile, d_a, d_b) - sum(profile_time_s(profile, lo, hi) for lo, hi, _ in zones)
        scale = prof_t / free_t if free_t > 0 else 1.0

    steps, d = [], d_a
    for i in range(n):
        t = t_a + i * step_s
        zone = next((z for z in zones if z[0] <= d < z[1]), None)
        wobble = 1 + (0.08 if profile else 0.12) * math.sin(2 * math.pi * t / 90)
        v = zone[2] if zone else (_profile_kmh(profile, d) / 3.6 * scale if profile else v_base) * wobble
        steps.append([v * step_s, zone is None])
        d += v * step_s
    resid = (d_b - d_a) - sum(s[0] for s in steps)
    free = [s for s in steps if s[1]] or steps
    for s in free:
        s[0] += resid / len(free)

    out, d = [], d_a
    for i, (ds, _) in enumerate(steps):
        d = d_b if i == n - 1 else min(d + ds, d_b)
        out.append((t_a + (i + 1) * step_s, _interp(pts, cum, d)))
    return out


def _rest(st: Stop, rng, step_s):
    out = []
    for j in range(0, st.duration_s // step_s + 1):
        lat, lon = st.lat, st.lon
        if st.jitter_m > 0 and j * step_s != st.anchor_s:
            r = rng.uniform(0.4, 1.0) * st.jitter_m
            if st.away_from:
                base = math.atan2(st.lat - st.away_from[0], (st.lon - st.away_from[1]) * math.cos(math.radians(st.lat)))
                theta = base + rng.uniform(-1.2, 1.2)
            else:
                theta = rng.uniform(0, 2 * math.pi)
            lat += r * math.sin(theta) / M_PER_DEG_LAT
            lon += r * math.cos(theta) / m_per_deg_lon(st.lat)
        out.append((st.start_s + j * step_s, (lat, lon)))
    return out


def _interp(pts, cum, d):
    i = max(1, min(bisect.bisect_left(cum, d), len(pts) - 1))
    seg = cum[i] - cum[i - 1]
    f = 0.0 if seg == 0 else (d - cum[i - 1]) / seg
    return (pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f)
