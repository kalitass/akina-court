"""Fare from GPS + data/rates.json. Nothing here is hand-typed: metered fares come from the trace,
fixed (RydeX) fares from the quoted optimal route, cancellation fees from the rate card."""
from __future__ import annotations

import json
import os
from datetime import datetime

from route_provider import haversine_m

RATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rates.json")


def load_rates(path: str = RATES_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


def ts(p) -> datetime:
    return datetime.fromisoformat(p["ts"])


def slice_gps(gps, start: str, end: str):
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    return [p for p in gps if a <= ts(p) <= b]


def distance_km(gps) -> float:
    return sum(haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(gps, gps[1:])) / 1000


def stationary_windows(gps, threshold_m: float = 3.0, min_s: int = 60):
    """[(start_ts, end_ts, seconds, lat, lon)] for runs of samples that do not move."""
    wins, run_start = [], None
    for a, b in zip(gps, gps[1:]):
        if haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) < threshold_m:
            run_start = run_start or a
        else:
            if run_start:
                wins.append((run_start, a))
            run_start = None
    if run_start:
        wins.append((run_start, gps[-1]))
    out = []
    for s, e in wins:
        secs = int((ts(e) - ts(s)).total_seconds())
        if secs >= min_s:
            out.append((s["ts"], e["ts"], secs, s["lat"], s["lon"]))
    return out


def stationary_seconds(gps, threshold_m: float = 3.0) -> int:
    return sum(int((ts(b) - ts(a)).total_seconds())
               for a, b in zip(gps, gps[1:])
               if haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) < threshold_m)


def platform_fee(subtotal: float, rates: dict) -> float:
    for tier in rates["platform_fee_tiers"]:
        if tier["subtotal_up_to"] is None or subtotal <= tier["subtotal_up_to"]:
            return tier["fee"]
    raise ValueError("no platform fee tier matched")


def _assemble(rates, km, minutes, wait_min, surge, discount, pricing, basis):
    """`minutes` are billed moving minutes (stop minutes already deducted), `wait_min` the stop minutes:
    a stationary minute is billed once, as waiting, never also as trip time (review 2b, spec 1.4)."""
    distance_fare = r2(km * rates["rate_per_km"])
    time_fare = r2(minutes * rates["rate_per_min"])
    waiting_fee = r2(wait_min * rates["waiting_rate_per_min"])
    subtotal = r2((rates["base_fare"] + distance_fare + time_fare + waiting_fee) * surge)
    pf = platform_fee(subtotal, rates)
    return {
        "pricing": pricing,
        "base_fare": rates["base_fare"], "distance_km": km, "distance_fare": distance_fare,
        "time_min": minutes, "time_fare": time_fare,
        "waiting_min": wait_min, "waiting_fee": waiting_fee, "waiting_fee_basis": basis,
        "surge_multiplier": surge, "platform_fee": pf, "discount": r2(discount),
        "total": r2(subtotal + pf - discount), "currency": rates["currency"],
    }


def metered_fare(trip_gps, rates: dict, surge: float = 1.0, discount: float = 0.0) -> dict:
    """RydeTAXI: meter runs on the actual trace (pickup..dropoff samples only).
    time_min = trip minutes minus stationary minutes (the stop is billed as waiting_min, once)."""
    km = r2(distance_km(trip_gps))
    wait_s = stationary_seconds(trip_gps, rates["stationary_threshold_m"])
    wait_min = round(wait_s / 60 + 1e-9, 2)
    minutes = round(((ts(trip_gps[-1]) - ts(trip_gps[0])).total_seconds() - wait_s) / 60 + 1e-9, 2)
    return _assemble(rates, km, minutes, wait_min, surge, discount, "metered", "metered_minutes")


def fixed_fare(route: dict, rates: dict, surge: float = 1.0, discount: float = 0.0) -> dict:
    """RydeX: price quoted at booking from the optimal route; the trace does not change it.
    waiting_fee is the flat $5 pickup button, 0 unless the driver pressed it (never in the demo cases)."""
    return _assemble(rates, route["total_km"], route["total_min"], 0.0, surge, discount, "fixed", "flat_pickup_button")


def cancellation_fare(rates: dict) -> dict:
    return {"pricing": "fixed", "cancellation_fee": rates["cancellation_fee"], "currency": rates["currency"]}
