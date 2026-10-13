"""Case files on disk: the organisers' RydeResolve JSON ("official") plus the fields this system adds ("plus").

    to_internal(d)   official / official-plus dict -> internal Case dict (core.schemas.Case). Case validation calls it,
                     so every loader that does Case.model_validate(json.load(...)) reads either shape.
    to_official(c)   internal Case dict -> official-plus dict (what data/cases and data/bench store)
    read_case(path)  a case file (.json, or .md with a ```json block) -> internal Case dict, for code that reads raw dicts

Official fields keep the official names and structure; plus fields sit next to the official field they extend. Where the
samples name one thing differently, the writer uses the first name and the reader takes both:
    chat_logs[].message (DISP-001, DISP-003)          | chat_logs[].content (DISP-002)
    fare_breakdown.actual_fare (DISP-003)            | fare_breakdown.actual (DISP-001)
    fare_breakdown.upfront_quote (DISP-003)          | fare_breakdown.estimated (DISP-001)
Official fields with no internal home stay in the file untouched. Nothing is invented: when the record lacks something
the internal Case requires (booking time, optimal route), the reader uses a stated fallback (earliest timestamp in the
record; straight line pickup -> dropoff) and names it in provenance.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path

TYPE_IN = {"route_deviation": "route_deviation", "detour": "route_deviation",
           "no_show_charge": "no_show", "no_show": "no_show", "cancellation_fee": "no_show",
           "safety_incident": "safety", "safety": "safety",
           "fare_dispute": "fare_dispute", "property_damage": "property_damage"}
TYPE_OUT = {"route_deviation": "route_deviation", "no_show": "no_show_charge", "safety": "safety_incident",
            "fare_dispute": "fare_dispute", "property_damage": "property_damage"}

# internal trip field -> app_events event_type (the official timeline vocabulary, DISP-002)
EVENTS = {"requested_at": "booking_confirmed", "accepted_at": "driver_assigned", "driver_pressed_here_at": "driver_arrived",
          "wait_started_at": "wait_timer_started", "wait_expired_at": "wait_timer_expired", "fee_applied_at": "cancellation_fee_applied"}
# internal trip field -> trip_data field
TRIP_FIELDS = {"trip_id": "trip_id", "service_type": "service_type", "estimated_km": "estimated_distance_km",
               "estimated_min": "estimated_duration_min", "scheduled_at": "scheduled_time", "driver_arrived_at": "driver_arrival_time",
               "pickup_at": "start_time", "dropoff_at": "end_time", "cancelled_at": "cancellation_time", "cancelled_by": "cancelled_by",
               "cancellation_reason": "cancellation_reason"}
TRIP_ALWAYS = ("driver_arrived_at", "driver_pressed_here_at", "pickup_at", "dropoff_at", "cancelled_at", "cancelled_by")
POLICY_PARAMS = {"free_wait_min": "free_wait_time_min", "no_show_threshold_min": "no_show_threshold_min",
                 "cancellation_fee": "cancellation_fee_after_wait", "fee_goes_to": "fee_goes_to"}
FARE_DETAIL_ACTUAL = ("surge_amount", "surgeable_subtotal", "booking_fee")       # fare_breakdown.actual_fare keys that are not v2 fare lines
FARE_DETAIL_TOP = ("excess_distance_fare", "excess_tolls")
QUOTE_KEYS = ("surge_multiplier", "surge_amount", "surgeable_subtotal")
SURGE_KEYS = ("quote_time_surge", "trip_start_surge", "surge_activated_at", "rider_notified", "notification_method",
              "notification_timestamp", "notification_text", "notification_content", "reason")
INCIDENT_KEYS = {"incident_id": "incident_id", "road": "road", "direction": "direction", "stretch": "stretch",
                 "incident_type": "incident_type", "severity": "severity", "reported_at": "timestamp",
                 "cleared_at": "clear_time", "description": "description"}
CALL_KEYS = {"ts": "timestamp", "caller": "caller", "callee": "callee", "answered": "answered", "duration_s": "duration_s",
             "recording_ref": "recording_ref", "transcript": "transcript", "details": "details"}
ACCOUNT_KEYS = ("fraud_flags", "fraud_flag_details", "no_shows_30d")
CALL_EVENT = re.compile(r"^(rider|driver)_called_(rider|driver)$")
NO_WEATHER = {"rain_mm": 0, "description": "not in the sample"}


def is_official(d) -> bool:
    return isinstance(d, dict) and "dispute_ticket" in d


def load_official(path: Path) -> dict:
    """The JSON of a case file: a bare .json, or the first ```json block of a markdown file (the organisers' samples)."""
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        return json.loads(text)
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise ValueError(f"{path}: no ```json block found")
    return json.loads(m.group(1))


def read_case(path) -> dict:
    """A case file of either shape as an internal Case dict."""
    d = load_official(Path(path))
    return to_internal(d) if is_official(d) else d


def dumps(d: dict) -> str:
    """A case file's text: indented JSON with flat objects (a GPS sample, a waypoint) and [lat, lon] pairs on one line."""
    text = json.dumps(d, indent=2, ensure_ascii=False)
    flat = r'\{\n\s+((?:"[^"\n]*": [^\n{}\[\]]*\n\s+)*"[^"\n]*": [^\n{}\[\]]*)\n\s+\}'
    text = re.sub(flat, lambda m: "{" + re.sub(r"\n\s+", " ", m.group(1)) + "}", text)
    text = re.sub(r"\[\n\s+(-?[\d.]+),\n\s+(-?[\d.]+)\n\s+\]", r"[\1, \2]", text)
    assert json.loads(text) == d
    return text + "\n"


def _put(d: dict, key: str, value):
    if value is not None:
        d[key] = value


def _sub(d: dict, keys) -> dict:
    return {k: d[k] for k in keys if k in d}


def _hav_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


# ----------------------------------------------------------------------------------------------- official -> internal

def to_internal(d: dict) -> dict:
    tk, t = d.get("dispute_ticket", {}), d.get("trip_data", {})
    meta, fb = d.get("case_metadata", {}), d.get("fare_breakdown", {})
    prov = dict(meta.get("provenance") or {})
    events: dict[str, dict] = {}
    for e in d.get("app_events", []):
        events.setdefault(e.get("event_type"), e)
    ev_ts = lambda kind: (events.get(kind) or {}).get("timestamp")

    def place(p: dict) -> dict:
        return {"lat": p["lat"], "lon": p["lng"], "name": p.get("name", "")}
    pickup, dropoff = place(t["pickup_location"]), place(t["dropoff_location"])

    # optimal route: the record's own waypoints when present, else a straight line (named in provenance)
    o = d.get("optimal_route") or {}
    if o.get("waypoints"):
        poly = [[w["lat"], w["lng"]] for w in o["waypoints"]]
        km = o.get("estimated_distance_km", t.get("estimated_distance_km"))
        if km is None:
            km = round(sum(_hav_km(a, b) for a, b in zip(poly, poly[1:])), 3)
            prov.setdefault("route_km", "length of the optimal_route waypoints (no estimated distance in the record)")
    else:
        poly = [[pickup["lat"], pickup["lon"]], [dropoff["lat"], dropoff["lon"]]]
        km = t.get("estimated_distance_km")
        if km is None:
            km = round(_hav_km(poly[0], poly[1]) * 1.3, 3)
        prov.setdefault("route", "straight-line estimate (the record has no optimal_route)")
    mins = o.get("estimated_duration_min", t.get("estimated_duration_min"))
    if mins is None:
        mins = round(km / 25 * 60, 1)
    route = {"total_km": km, "total_min": mins, "polyline": poly}
    _put(route, "roads", o.get("roads") or [{"name": w["location_desc"]} for w in o.get("waypoints", []) if w.get("location_desc")] or None)

    # timeline: trip_data fields, then the app_events the official sample logs
    trip = {"trip_id": t.get("trip_id", tk.get("trip_id")), "service_type": t.get("service_type", "RydeX"),
            "pickup": pickup, "dropoff": dropoff,
            "estimated_km": t.get("estimated_distance_km", km), "estimated_min": t.get("estimated_duration_min", mins)}
    for k, src in TRIP_FIELDS.items():
        if k not in trip and (src in t or k in TRIP_ALWAYS):
            trip[k] = t.get(src)
    for k, kind in EVENTS.items():
        if kind in events or k in TRIP_ALWAYS:
            trip[k] = ev_ts(kind)
    if trip.get("requested_at") is None or trip.get("accepted_at") is None:
        # no booking events: the trip was booked and accepted no later than the first thing the record shows
        first = ev_ts("booking_confirmed") or min(
            [x for x in [c.get("timestamp") for c in d.get("chat_logs", [])] + [p.get("timestamp") for p in d.get("gps_telemetry", [])]
             + [t.get(k) for k in ("scheduled_time", "start_time", "driver_arrival_time", "cancellation_time")] if x],
            key=lambda x: datetime.fromisoformat(x), default=None)
        if not ev_ts("booking_confirmed"):
            prov.setdefault("timeline", "no booking events in the record: requested_at / accepted_at set to its earliest timestamp")
        for k in ("requested_at", "accepted_at"):
            if trip.get(k) is None:
                trip[k] = first
    arrived = events.get("driver_arrived") or {}
    by = arrived.get("confirmed_by") or ("platform_auto" if re.search(r"\bauto", arrived.get("details", ""), re.I) else None)
    _put(trip, "arrival_confirmed_by", by)
    m = re.search(r"within\s*(\d+)\s*m\b", arrived.get("details", ""))
    _put(trip, "arrival_radius_m", arrived.get("radius_m", int(m.group(1)) if m else None))
    _put(trip, "cancellation_reason", t.get("cancellation_reason"))
    if "cancelled_by" not in t and trip["cancelled_at"] is not None:      # the official sample gives only a reason
        trip["cancelled_by"] = "driver" if (t.get("cancellation_reason") or "").startswith("rider_no_show") else "rider"

    gps = [{"ts": p["timestamp"], "lat": p["lat"], "lon": p["lng"], "speed_kmh": p.get("speed_kmh", 0),
            **({"road": p.get("road") or p.get("location_desc")} if (p.get("road") or p.get("location_desc")) else {})}
           for p in d.get("gps_telemetry", [])]
    chat = []
    for c in d.get("chat_logs", []):
        if c.get("sender") in ("rider", "driver"):
            m = {"ts": c.get("timestamp"), "from": c["sender"], "text": c["message"] if "message" in c else c.get("content", "")}
            if "type" in c:
                m["kind"] = "call" if c["type"] == "call" else "message"
            chat.append(m)

    incidents, road_incidents = [], []
    for e in d.get("traffic_conditions", []):
        if "lat" in e and "lng" in e:             # located: what the RD-4 incident check reads
            incidents.append({"type": e.get("incident_type", ""), "lat": e["lat"], "lon": e["lng"],
                              "message": e.get("description", ""), "reported_at": e["timestamp"]})
        else:                                     # identified by road name only (DISP-001)
            road_incidents.append({k: e[src] for k, src in INCIDENT_KEYS.items() if src in e})
    traffic = {"speed_bands": d.get("traffic_speed_bands", []), "incidents": incidents}
    if road_incidents:
        traffic["road_incidents"] = road_incidents

    weather = {}
    _put(weather, "rain_mm", t.get("rain_mm"))
    _put(weather, "description", t.get("weather"))

    actual = fb.get("actual_fare", fb.get("actual")) or {}
    quote = fb.get("upfront_quote", fb.get("estimated")) or {}
    fare = {"pricing": fb.get("pricing", "fixed"), "currency": fb.get("currency", "SGD")}
    fare.update({k: v for k, v in actual.items() if k not in FARE_DETAIL_ACTUAL})
    if "total" not in fare:
        _put(fare, "total", t.get("actual_fare"))
    _put(fare, "distance_km", t.get("actual_distance_km"))
    _put(fare, "cancellation_fee", t.get("cancellation_fee"))
    _put(fare, "quoted_total", quote.get("total", t.get("upfront_quote", t.get("estimated_fare"))))

    detail = {k: actual[k] for k in FARE_DETAIL_ACTUAL if actual.get(k) is not None}
    detail.update({k: fb[k] for k in FARE_DETAIL_TOP if fb.get(k) is not None})
    _put(detail, "booking_fee_surge_exempt", (fb.get("comparison") or {}).get("booking_fee_surge_exempt"))
    q = {k: quote[k] for k in QUOTE_KEYS if quote.get(k) is not None}
    if q:
        detail["upfront_quote"] = q

    def profile(p: dict, driver: bool) -> dict:
        h90 = p.get("dispute_history_90d")
        h = h90 if h90 is not None else (p.get("dispute_history") or {})
        sfx = "_against" if "upheld_against" in h or (driver and "upheld" not in h) else ""
        out = {"account_age_days": p.get("account_age_days", 0), "rating": p.get("avg_rating", 0),
               "disputes_90d": h.get("total_disputes", 0), "disputes_upheld_90d": h.get("upheld" + sfx, 0),
               "route_disputes_upheld_90d": h.get("route_deviation_upheld" + sfx, 0), "no_show_disputes_upheld_90d": h.get("no_show_upheld" + sfx, 0)}
        if driver:
            out["trips_90d"] = p.get("total_trips_90d", 0) if h90 is not None else p.get("total_trips", 0)
        if h90 is None and ("dispute_history" in p or "total_trips" in p):
            prov.setdefault("history_window", "all time")    # the official profile gives lifetime totals, not a 90-day window
        return out
    rp, dp = d.get("rider_profile", {}), d.get("driver_profile", {})
    profiles = {"rider": profile(rp, False), "driver": profile(dp, True)}
    for side, p in (("rider", rp), ("driver", dp)):
        acct = {k: p[k] for k in ACCOUNT_KEYS if p.get(k) is not None}
        if acct:
            profiles[f"{side}_account"] = acct

    if "call_records" in d:
        calls = [{k: c[src] for k, src in CALL_KEYS.items() if src in c} for c in d["call_records"]]
    else:                                         # the platform's call log in app_events (DISP-002: driver_called_rider)
        calls = []
        for e in d.get("app_events", []):
            m = CALL_EVENT.match(e.get("event_type", ""))
            if m:
                calls.append({"ts": e.get("timestamp"), "caller": m.group(1), "callee": m.group(2), **({"details": e["details"]} if "details" in e else {})})

    case = {"case_id": tk.get("dispute_id", meta.get("dataset_id")),
            "dispute": {"type": TYPE_IN.get(tk.get("dispute_type"), tk.get("dispute_type")), "filed_by": tk.get("filed_by"),
                        "filed_at": tk.get("filed_at"), "statement": tk.get("description", "")},
            "trip": trip, "route": route, "gps": gps, "traffic": traffic, "weather": weather or dict(NO_WEATHER),
            "fare": fare, "chat": chat, "driver_statement": tk.get("driver_statement"), "profiles": profiles}
    pol = d.get("cancellation_policy")
    if pol is not None:
        case["policy_params"] = {k: pol[src] for k, src in POLICY_PARAMS.items() if src in pol}
    if detail:
        case["fare_detail"] = detail
    if d.get("surge_pricing_log") is not None:
        case["surge"] = _sub(d["surge_pricing_log"], SURGE_KEYS)
    if calls:
        case["calls"] = calls
    if prov:
        case["provenance"] = prov
    return case


# ----------------------------------------------------------------------------------------------- internal -> official-plus

def to_official(c) -> dict:
    """Internal Case dict (or Case) -> official-plus dict. Writes only what the case carries; to_internal reads it back
    to the same dict."""
    if not isinstance(c, dict):
        c = c.model_dump(mode="json", by_alias=True)
    dsp, trip, fare, route = c["dispute"], c["trip"], c["fare"], c["route"]
    prov = c.get("provenance") or {}
    out: dict = {}
    if prov:
        out["case_metadata"] = {"provenance": prov}

    tk = {"dispute_id": c["case_id"], "trip_id": trip["trip_id"], "filed_by": dsp["filed_by"],
          "dispute_type": TYPE_OUT.get(dsp["type"], dsp["type"]), "description": dsp["statement"], "filed_at": dsp["filed_at"]}
    _put(tk, "driver_statement", c.get("driver_statement"))
    out["dispute_ticket"] = tk

    lifetime = prov.get("history_window") == "all time"
    profiles = c["profiles"]
    for side in ("rider", "driver"):
        p, sfx = profiles[side], "_against" if side == "driver" else ""
        o = {"account_age_days": p["account_age_days"], "avg_rating": p["rating"]}
        h = {"total_disputes": p["disputes_90d"], "upheld" + sfx: p["disputes_upheld_90d"]}
        for k, src in (("route_deviation_upheld", "route_disputes_upheld_90d"), ("no_show_upheld", "no_show_disputes_upheld_90d")):
            if p.get(src) or not lifetime:
                h[k + sfx] = p.get(src, 0)
        if lifetime:
            o["dispute_history"] = h
            if side == "driver":
                o["total_trips"] = p["trips_90d"]
        else:
            o["dispute_history_90d"] = h
            if side == "driver":
                o["total_trips_90d"] = p["trips_90d"]
        o.update(profiles.get(f"{side}_account") or {})
        out[f"{side}_profile"] = o

    td = {"trip_id": trip["trip_id"],
          "pickup_location": {"name": trip["pickup"]["name"], "lat": trip["pickup"]["lat"], "lng": trip["pickup"]["lon"]},
          "dropoff_location": {"name": trip["dropoff"]["name"], "lat": trip["dropoff"]["lat"], "lng": trip["dropoff"]["lon"]}}
    for k, dst in TRIP_FIELDS.items():
        if k != "trip_id":
            _put(td, dst, trip.get(k))
    if trip.get("cancelled_at") is not None:
        td["cancelled_by"] = trip.get("cancelled_by")         # written even when null: a cancellation the record does not attribute
    _put(td, "actual_distance_km", fare.get("distance_km"))
    _put(td, "actual_fare", fare.get("total"))
    _put(td, "upfront_quote", fare.get("quoted_total"))
    _put(td, "cancellation_fee", fare.get("cancellation_fee"))
    w = c.get("weather")
    if w is not None and w != NO_WEATHER:
        _put(td, "weather", w.get("description"))
        _put(td, "rain_mm", w.get("rain_mm"))
    out["trip_data"] = td

    detail = c.get("fare_detail") or {}
    fb = {"pricing": fare.get("pricing", "fixed"), "currency": fare.get("currency", "SGD")}
    q = dict(detail.get("upfront_quote") or {})
    _put(q, "total", fare.get("quoted_total"))
    if q:
        fb["upfront_quote"] = q
    actual = {k: v for k, v in fare.items() if k not in ("pricing", "currency", "distance_km", "cancellation_fee", "quoted_total")}
    actual.update({k: detail[k] for k in FARE_DETAIL_ACTUAL if k in detail})
    if actual:
        fb["actual_fare"] = actual
    fb.update({k: detail[k] for k in FARE_DETAIL_TOP if k in detail})
    if "booking_fee_surge_exempt" in detail:
        fb["comparison"] = {"booking_fee_surge_exempt": detail["booking_fee_surge_exempt"]}
    out["fare_breakdown"] = fb

    out["gps_telemetry"] = [{"timestamp": p["ts"], "lat": p["lat"], "lng": p["lon"], "speed_kmh": p["speed_kmh"], **({"road": p["road"]} if p.get("road") else {})}
                            for p in c["gps"]]
    o = {"estimated_distance_km": route["total_km"], "estimated_duration_min": route["total_min"],
         "waypoints": [{"lat": la, "lng": lo} for la, lo in route["polyline"]]}
    _put(o, "roads", route.get("roads"))
    out["optimal_route"] = o

    chat = []
    for m in c.get("chat", []):
        e = {}
        _put(e, "timestamp", m.get("ts"))
        e.update({"sender": m.get("from", m.get("sender")), "message": m["text"]})
        if "kind" in m:
            e["type"] = m["kind"]
        chat.append(e)
    out["chat_logs"] = chat
    if c.get("calls"):
        out["call_records"] = [{dst: x[k] for k, dst in CALL_KEYS.items() if k in x} for x in c["calls"]]

    events = []
    for k, kind in EVENTS.items():
        if trip.get(k) is not None:
            e = {"timestamp": trip[k], "event_type": kind}
            if kind == "driver_arrived":
                _put(e, "confirmed_by", trip.get("arrival_confirmed_by"))
                _put(e, "radius_m", trip.get("arrival_radius_m"))
            events.append(e)
    if events:
        out["app_events"] = sorted(events, key=lambda e: e["timestamp"])

    tr = c.get("traffic") or {}
    tc = [{"incident_type": i["type"], "timestamp": i["reported_at"], "description": i["message"], "lat": i["lat"], "lng": i["lon"]}
          for i in tr.get("incidents", [])]
    tc += [{src: i[k] for k, src in INCIDENT_KEYS.items() if k in i} for i in tr.get("road_incidents", [])]
    out["traffic_conditions"] = tc
    out["traffic_speed_bands"] = tr.get("speed_bands", [])
    if c.get("surge"):
        out["surge_pricing_log"] = dict(c["surge"])
    if c.get("policy_params") is not None:
        out["cancellation_policy"] = {dst: c["policy_params"][k] for k, dst in POLICY_PARAMS.items() if k in c["policy_params"]}
    return out
