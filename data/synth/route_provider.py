"""Route providers. Both return {"total_km", "total_min", "polyline": [[lat, lon], ...]}.

OneMapRouteProvider   real routing via OneMap (https://www.onemap.gov.sg/apidocs/), verified 2026-09-30.
                      Needs ONEMAP_TOKEN (or ONEMAP_EMAIL / ONEMAP_PASSWORD) only for legs missing from
                      data/synth/onemap_cache.json. Adds "roads" (name + metres along the polyline).
FallbackRouteProvider offline: straight legs between the given points with a lateral wiggle whose
                      amplitude is solved so the length equals straight-line x 1.25 (or target_km).
"""
from __future__ import annotations

import json
import math
import os
import random
import urllib.parse
import urllib.request

Point = tuple[float, float]  # (lat, lon)
M_PER_DEG_LAT = 111_320.0


def m_per_deg_lon(lat: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(lat))


def haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(h))


def path_length_m(pts) -> float:
    return sum(haversine_m(a, b) for a, b in zip(pts, pts[1:]))


def decode_polyline(encoded: str, precision: int = 5) -> list[Point]:
    """Google encoded-polyline decoder (OneMap route_geometry uses precision 5)."""
    coords, idx, lat, lon, factor = [], 0, 0, 0, 10 ** precision
    while idx < len(encoded):
        for is_lat in (True, False):
            shift = result = 0
            while True:
                b = ord(encoded[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lat:
                lat += delta
            else:
                lon += delta
        coords.append((lat / factor, lon / factor))
    return coords


def _pack(poly, dist_m: float, time_min: float) -> dict:
    return {
        "total_km": round(dist_m / 1000, 3),
        "total_min": round(time_min, 1),
        "polyline": [[round(la, 6), round(lo, 6)] for la, lo in poly],
    }


class OneMapRouteProvider:
    """Real routing via OneMap (SLA). Responses are cached in data/synth/onemap_cache.json keyed by the leg's
    start/end, so a rebuild with a warm cache needs no token and is deterministic. The route dict adds
    "roads": [{"name", "from_m", "to_m"}] built from route_instructions (metres along the polyline), which
    is what gives a speed band its geometry."""

    BASE = "https://www.onemap.gov.sg/api"
    CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onemap_cache.json")

    def __init__(self, email: str | None = None, password: str | None = None, timeout: int = 20):
        self.email = email or os.environ.get("ONEMAP_EMAIL")
        self.password = password or os.environ.get("ONEMAP_PASSWORD")
        self._token: str | None = os.environ.get("ONEMAP_TOKEN") or None
        self.timeout = timeout
        self._cache = json.load(open(self.CACHE)) if os.path.exists(self.CACHE) else {}

    def token(self) -> str:
        if self._token is None:
            if not (self.email and self.password):
                raise RuntimeError("OneMapRouteProvider: leg not in cache and no ONEMAP_TOKEN / ONEMAP_EMAIL+PASSWORD")
            body = json.dumps({"email": self.email, "password": self.password}).encode()
            req = urllib.request.Request(
                f"{self.BASE}/auth/post/getToken", data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self._token = json.load(r)["access_token"]  # valid ~72 h
        return self._token

    def _leg(self, a: Point, b: Point) -> dict:
        key = f"{a[0]:.6f},{a[1]:.6f}|{b[0]:.6f},{b[1]:.6f}"
        if key not in self._cache:
            q = urllib.parse.urlencode({"start": f"{a[0]},{a[1]}", "end": f"{b[0]},{b[1]}", "routeType": "drive"})
            req = urllib.request.Request(f"{self.BASE}/public/routingsvc/route?{q}", headers={"Authorization": self.token()})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                if e.code != 401 or not (self.email and self.password):
                    raise
                self._token = None          # stale ONEMAP_TOKEN: log in again and retry once
                req = urllib.request.Request(f"{self.BASE}/public/routingsvc/route?{q}", headers={"Authorization": self.token()})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
            if data.get("status_message") != "Found route between points":
                raise RuntimeError(f"OneMap: {data.get('status_message')} for {key}")
            self._cache[key] = {"route_summary": data["route_summary"], "route_geometry": data["route_geometry"],
                                "route_instructions": [[i[1], i[2]] for i in data["route_instructions"]]}
            with open(self.CACHE, "w") as f:
                json.dump(self._cache, f, indent=0, sort_keys=True)
        return self._cache[key]

    def route(self, points, target_km: float | None = None) -> dict:
        """Route through every point in order (extra points = detour / stop waypoints). target_km is ignored."""
        dist = secs = 0.0
        poly: list[Point] = []
        roads: list[dict] = []
        for a, b in zip(points, points[1:]):
            d = self._leg(tuple(a), tuple(b))
            s = d["route_summary"]  # total_distance in metres, total_time in seconds
            p = decode_polyline(d["route_geometry"])
            at = dist
            for name, length in d["route_instructions"]:
                if length > 0:
                    if roads and roads[-1]["name"] == name and abs(roads[-1]["to_m"] - at) < 1:
                        roads[-1]["to_m"] = at + length
                    else:
                        roads.append({"name": name, "from_m": round(at, 1), "to_m": round(at + length, 1)})
                    at += length
            dist += float(s["total_distance"])
            secs += float(s["total_time"])
            poly.extend(p if not poly else p[1:])
        # OneMap snaps both ends to the road network; add the short hop to the exact pins so a trace can start /
        # end on the pickup / drop-off coordinates (kerb-side pull-in, usually < 50 m)
        end_pin = (round(points[-1][0], 6), round(points[-1][1], 6))
        if haversine_m(poly[-1], end_pin) > 1:
            dist += haversine_m(poly[-1], end_pin)
            poly.append(end_pin)
        start_pin = (round(points[0][0], 6), round(points[0][1], 6))
        hop = haversine_m(poly[0], start_pin)
        if hop > 1:
            dist += hop
            poly.insert(0, start_pin)
            for r in roads:
                r["from_m"], r["to_m"] = round(r["from_m"] + hop, 1), round(r["to_m"] + hop, 1)
        out = _pack(poly, dist, secs / 60)
        out["roads"] = roads
        return out


def road_geometry(route: dict, name: str, from_m: float | None = None, to_m: float | None = None) -> list[list[float]]:
    """Polyline slice covering road `name` in a route (its longest run, or the run overlapping from_m..to_m).
    Metres along the instructions are matched to metres along the decoded polyline."""
    runs = [r for r in route.get("roads", []) if r["name"] == name]
    if not runs:
        raise KeyError(f"{name} not on this route: {[r['name'] for r in route.get('roads', [])]}")
    if from_m is not None:
        runs = [r for r in runs if r["to_m"] > from_m and r["from_m"] < to_m] or runs
    r = max(runs, key=lambda r: r["to_m"] - r["from_m"])
    poly = [tuple(p) for p in route["polyline"]]
    cum = [0.0]
    for a, b in zip(poly, poly[1:]):
        cum.append(cum[-1] + haversine_m(a, b))
    scale = cum[-1] / max(route["total_km"] * 1000, 1)  # instruction metres vs polyline metres
    lo, hi = r["from_m"] * scale, r["to_m"] * scale
    pts = [list(p) for p, c in zip(poly, cum) if lo - 1 <= c <= hi + 1]
    return pts if len(pts) >= 2 else [list(poly[min(range(len(poly)), key=lambda k: abs(cum[k] - lo))]),
                                      list(poly[min(range(len(poly)), key=lambda k: abs(cum[k] - hi))])]


class FallbackRouteProvider:
    """Synthetic road-like polyline. Deterministic for a given seed."""

    def __init__(self, seed: int = 0, factor: float = 1.25, avg_speed_kmh: float = 25.0,
                 spacing_m: float = 100.0, jitter_m: float = 3.0):
        self.seed, self.factor, self.avg_speed_kmh = seed, factor, avg_speed_kmh
        self.spacing_m, self.jitter_m = spacing_m, jitter_m

    def route(self, points, target_km: float | None = None) -> dict:
        pts = [tuple(p) for p in points]
        straight = path_length_m(pts)
        target = target_km * 1000 if target_km else straight * self.factor
        lo, hi = 0.0, 2000.0  # lateral wiggle amplitude, metres per km of leg length
        for _ in range(60):
            mid = (lo + hi) / 2
            if path_length_m(self._wiggle(pts, mid)) < target:
                lo = mid
            else:
                hi = mid
        poly = self._wiggle(pts, hi)
        dist = path_length_m(poly)
        return _pack(poly, dist, dist / 1000 / self.avg_speed_kmh * 60)

    def _wiggle(self, pts, amp_per_km: float):
        rng = random.Random(self.seed)
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            leg = haversine_m(a, b)
            n = max(2, int(leg / self.spacing_m))
            kx = m_per_deg_lon(a[0])
            dx, dy = (b[1] - a[1]) * kx, (b[0] - a[0]) * M_PER_DEG_LAT
            nx, ny = -dy / leg, dx / leg  # unit normal in metres
            amp = amp_per_km * leg / 1000
            for k in range(1, n + 1):
                if k == n:
                    out.append(b)
                    break
                s = k / n
                off = amp * (0.5 * math.sin(math.pi * s) + 0.3 * math.sin(3 * math.pi * s)
                             + 0.2 * math.sin(7 * math.pi * s)) + rng.gauss(0, self.jitter_m)
                lat = a[0] + (b[0] - a[0]) * s + off * ny / M_PER_DEG_LAT
                lon = a[1] + (b[1] - a[1]) * s + off * nx / kx
                out.append((lat, lon))
        return out
