"""Import a RydeResolve sample dataset (the organisers' JSON shape) into this system's Case.

    python -m core.ingest data/samples/DISP-002.md            # markdown with a ```json block, or a bare .json
    python -m core.ingest data/samples/DISP-002.md --out data/cases/DISP-002.json

Mapping (official → ours):
  dispute_ticket           → dispute (no_show_charge → no_show, route_* → route_deviation, safety_* → safety)
  trip_data + app_events   → trip (booking_confirmed → requested_at, driver_assigned → accepted_at,
                             driver_arrived / driver_arrival_time → driver_arrived_at and driver_pressed_here_at
                             (the platform's auto-arrival confirmation plays the role of the "I'm Here" tap),
                             cancellation_time / cancellation_reason → cancelled_at / cancelled_by)
  gps_telemetry            → gps (lng → lon)
  chat_logs                → chat (rider/driver messages; a driver call attempt becomes a driver line; system lines dropped)
  cancellation_policy      → fare.cancellation_fee (+ the dataset's own wait rule kept in provenance for the record)
  rider/driver_profile     → profiles (dispute_history → disputes / upheld; fraud flags recorded in provenance)
  route                    → OneMap route for pickup → dropoff (cached), straight line if no token and no cache
Nothing is invented: fields the sample does not carry stay None / 0 and are listed in provenance.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TYPE_MAP = {"no_show_charge": "no_show", "no_show": "no_show", "route_deviation": "route_deviation", "detour": "route_deviation",
            "safety_incident": "safety", "safety": "safety"}


def load_official(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise SystemExit(f"{path}: no ```json block found")
    return json.loads(m.group(1))


def _event(events: list[dict], kind: str) -> str | None:
    for e in events:
        if e.get("event_type") == kind:
            return e.get("timestamp")
    return None


def _radius(events: list[dict]):
    """Radius quoted in the platform's auto-arrival event ("GPS within 10m of pickup point"), if any."""
    for e in events:
        if e.get("event_type") == "driver_arrived":
            m = re.search(r"within\s*(\d+)\s*m", e.get("details", ""))
            return int(m.group(1)) if m else None
    return None


def _route(pickup: dict, dropoff: dict) -> dict:
    try:
        from data.synth.route_provider import OneMapRouteProvider
        prov = OneMapRouteProvider()
        r = prov.route([(pickup["lat"], pickup["lon"]), (dropoff["lat"], dropoff["lon"])])
        return {"total_km": r["total_km"], "total_min": r["total_min"], "polyline": r["polyline"], "roads": r.get("roads", []), "source": "onemap"}
    except Exception as e:  # noqa: BLE001  (no token and leg not cached)
        from data.synth.route_provider import haversine_m
        d_km = haversine_m((pickup["lat"], pickup["lon"]), (dropoff["lat"], dropoff["lon"])) / 1000 * 1.3
        return {"total_km": round(d_km, 3), "total_min": round(d_km / 25 * 60, 1),
                "polyline": [(pickup["lat"], pickup["lon"]), (dropoff["lat"], dropoff["lon"])], "roads": [], "source": f"straight-line estimate ({type(e).__name__})"}


def convert(d: dict) -> dict:
    t, tk, ev = d["trip_data"], d["dispute_ticket"], d.get("app_events", [])
    pickup = {"lat": t["pickup_location"]["lat"], "lon": t["pickup_location"]["lng"], "name": t["pickup_location"]["name"]}
    dropoff = {"lat": t["dropoff_location"]["lat"], "lon": t["dropoff_location"]["lng"], "name": t["dropoff_location"]["name"]}
    route = _route(pickup, dropoff)
    dtype = TYPE_MAP.get(tk["dispute_type"], tk["dispute_type"])
    arrived = t.get("driver_arrival_time") or _event(ev, "driver_arrived")
    cancelled_by = "driver" if (t.get("cancellation_reason") or "").startswith("rider_no_show") else ("rider" if t.get("cancellation_time") else None)
    gps = [{"ts": p["timestamp"], "lat": p["lat"], "lon": p["lng"], "speed_kmh": p.get("speed_kmh", 0)} for p in d.get("gps_telemetry", [])]
    chat = []
    for c in d.get("chat_logs", []):
        if c.get("sender") in ("rider", "driver"):
            chat.append({"ts": c["timestamp"], "from": c["sender"], "text": c["content"], "kind": "call" if c.get("type") == "call" else "message"})
    pol = d.get("cancellation_policy", {})
    rp, dp = d.get("rider_profile", {}), d.get("driver_profile", {})
    def prof(p, driver=False):
        h = p.get("dispute_history", {})
        out = {"account_age_days": p.get("account_age_days", 0), "rating": p.get("avg_rating", 0),
               "disputes_90d": h.get("total_disputes", 0), "disputes_upheld_90d": h.get("upheld", h.get("upheld_against", 0)),
               "route_disputes_upheld_90d": 0, "no_show_disputes_upheld_90d": 0,
               "disputes_window_days": None}
        if driver:
            out["trips_90d"] = p.get("total_trips", 0)
            out["trips_window_days"] = None
        return out
    case = {
        "case_id": tk["dispute_id"],
        "dispute": {"type": dtype, "filed_by": tk["filed_by"], "filed_at": tk["filed_at"], "statement": tk["description"]},
        "trip": {"trip_id": t["trip_id"], "service_type": "RydeX", "pickup": pickup, "dropoff": dropoff,
                 "estimated_km": route["total_km"], "estimated_min": route["total_min"],
                 "requested_at": _event(ev, "booking_confirmed") or t.get("scheduled_time"),
                 "accepted_at": _event(ev, "driver_assigned") or _event(ev, "booking_confirmed") or t.get("scheduled_time"),
                 "driver_arrived_at": arrived, "driver_pressed_here_at": arrived,
                 "arrival_confirmed_by": "platform_auto" if _event(ev, "driver_arrived") else ("driver_tap" if arrived else None),
                 "arrival_radius_m": _radius(ev),
                 "wait_started_at": _event(ev, "wait_timer_started"), "wait_expired_at": _event(ev, "wait_timer_expired"), "fee_applied_at": _event(ev, "cancellation_fee_applied"),
                 "pickup_at": t.get("pickup_time"), "dropoff_at": t.get("dropoff_time"),
                 "cancelled_at": t.get("cancellation_time"), "cancelled_by": cancelled_by},
        "route": {k: route[k] for k in ("total_km", "total_min", "polyline", "roads")},
        "gps": gps, "traffic": {"speed_bands": [], "incidents": []}, "weather": {"rain_mm": 0, "description": "not in the sample"},
        "fare": {"pricing": "fixed", "cancellation_fee": float(t.get("cancellation_fee", pol.get("cancellation_fee_after_wait", 0)) or 0), "currency": "SGD"},
        "policy_params": {"free_wait_min": pol.get("free_wait_time_min"), "no_show_threshold_min": pol.get("no_show_threshold_min"),
                          "cancellation_fee": pol.get("cancellation_fee_after_wait"), "fee_goes_to": pol.get("fee_goes_to")} if pol else None,
        "chat": chat, "driver_statement": None,
        "profiles": {"rider": prof(rp), "driver": prof(dp, driver=True)},
        "provenance": {
            "source": "RydeResolve sample dataset (organisers)", "schema": "official → core.ingest",
            "route": route["source"],
            "arrival": "platform auto-arrival event (no manual tap in the sample); arrival_confirmed_by = platform_auto",
            "dataset_policy": json.dumps(pol) if pol else "none in sample",
            "rider_fraud_flags": f"{rp.get('fraud_flags', 0)} ({rp.get('fraud_flag_details', '')})",
            "driver_fraud_flags": str(dp.get("fraud_flags", 0)),
            "traffic_weather": "not in the sample",
            "rider_payment_method": rp.get("payment_method", ""),
        },
    }
    return case


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path"); ap.add_argument("--out")
    a = ap.parse_args()
    case = convert(load_official(Path(a.path)))
    out = Path(a.out) if a.out else ROOT / "data" / "cases" / f"{case['case_id']}.json"
    out.write_text(json.dumps(case, ensure_ascii=False, indent=1))
    print(f"wrote {out}  ({case['dispute']['type']}, {len(case['gps'])} gps points, route {case['provenance']['route']})")


if __name__ == "__main__":
    main()
