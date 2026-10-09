"""Fact tools (core/facts/tools.py). Uses data/cases/C-0001.json / C-0004.json when they exist,
otherwise minimal inline cases built by the generators below."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.facts import tools
from core.facts.tools import (
    SOURCE_ORDER, build_fact_table, facts_for_tool, get_chat_facts, get_fare_facts,
    get_no_show_facts, get_route_facts, get_traffic_facts, haversine_m,
)
from core.schemas import Case

SGT = timezone(timedelta(hours=8))
T0 = datetime(2026, 9, 20, 14, 5, 10, tzinfo=SGT)
CASES_DIR = Path(__file__).resolve().parents[1] / "data" / "cases"

ORCHARD = (1.3048, 103.8318)
MBS = (1.2839, 103.8607)
WAYPOINT = (1.3100, 103.8700)          # far east of the straight line Orchard -> MBS
BUGIS = (1.2996, 103.8555)


def track(waypoints, speed_kmh=30.0, start=T0, step_s=5, stop_at=None, stop_s=0):
    """GPS points along straight segments at constant speed; optional stop of stop_s at waypoint index stop_at."""
    pts, t = [], start
    for idx, ((alat, alon), (blat, blon)) in enumerate(zip(waypoints, waypoints[1:]), 1):
        n = max(1, round(haversine_m(alat, alon, blat, blon) / (speed_kmh / 3.6 * step_s)))
        for k in range(n):
            f = k / n
            pts.append({"ts": t.isoformat(), "lat": alat + (blat - alat) * f, "lon": alon + (blon - alon) * f, "speed_kmh": speed_kmh})
            t += timedelta(seconds=step_s)
        if stop_at == idx:
            for _ in range(stop_s // step_s):
                pts.append({"ts": t.isoformat(), "lat": blat, "lon": blon, "speed_kmh": 0})
                t += timedelta(seconds=step_s)
    last = waypoints[-1]
    pts.append({"ts": t.isoformat(), "lat": last[0], "lon": last[1], "speed_kmh": 0})
    return pts


def base_case(case_id, dtype, trip, gps, fare, chat=(), **extra) -> Case:
    place = lambda lat, lon, name: {"lat": lat, "lon": lon, "name": name}
    data = {
        "case_id": case_id,
        "dispute": {"type": dtype, "filed_by": "rider", "filed_at": T0.isoformat(), "statement": "test"},
        "trip": {"trip_id": "T-TEST", "pickup": place(*ORCHARD, "Orchard Road"), "dropoff": place(*MBS, "MBS"),
                 "estimated_km": 3.5, "estimated_min": 10,
                 "requested_at": (T0 - timedelta(minutes=5)).isoformat(),
                 "accepted_at": (T0 - timedelta(minutes=4)).isoformat(), **trip},
        "route": {"total_km": 3.5, "total_min": 10, "polyline": [ORCHARD, MBS]},
        "gps": gps,
        "fare": fare,
        "chat": list(chat),
        "profiles": {"rider": {"account_age_days": 610, "rating": 4.9, "disputes_90d": 0, "disputes_upheld_90d": 0},
                     "driver": {"account_age_days": 1450, "rating": 4.7, "trips_90d": 812, "disputes_90d": 3, "disputes_upheld_90d": 1}},
        **extra,
    }
    return Case.model_validate(data)


def route_case() -> Case:
    gps = track([ORCHARD, WAYPOINT, MBS], stop_at=1, stop_s=240)
    return base_case(
        "C-TEST-RD", "route_deviation",
        {"driver_arrived_at": (T0 - timedelta(minutes=1)).isoformat(), "pickup_at": T0.isoformat(), "dropoff_at": gps[-1]["ts"]},
        gps,
        {"base_fare": 3.9, "distance_km": 7.4, "distance_fare": 10.43, "time_min": 20, "time_fare": 4.6,
         "waiting_fee": 1.1, "surge_multiplier": 1.0, "platform_fee": 0.7, "total": 20.73},
        chat=[{"ts": (T0 - timedelta(minutes=3)).isoformat(), "from": "driver", "text": "Traffic on Orchard is bad, ok if I take PIE?"},
              {"ts": (T0 - timedelta(minutes=2)).isoformat(), "from": "rider", "text": "Sure. Can you stop at a 7-Eleven on the way?"}],
        traffic={"speed_bands": [{"road_name": "ORCHARD ROAD", "road_category": "B", "speed_band": 1,
                                  "window_start": T0.isoformat(), "window_end": (T0 + timedelta(minutes=20)).isoformat()}],
                 "incidents": []},
    )


def no_show_case(stop_offset_m: float, wait_s: int, cancelled_by="driver") -> Case:
    """Driver approaches Bugis from 2 km south, stops stop_offset_m short of the pickup for wait_s, then cancels."""
    start = (BUGIS[0] - 0.018, BUGIS[1])
    stop = (BUGIS[0] - stop_offset_m / 110_540, BUGIS[1])
    accepted = T0 - timedelta(minutes=1)
    gps = track([start, stop], start=T0, stop_at=1, stop_s=wait_s)
    trip = {"pickup": {"lat": BUGIS[0], "lon": BUGIS[1], "name": "Bugis Junction"},
            "accepted_at": accepted.isoformat(), "cancelled_at": gps[-1]["ts"], "cancelled_by": cancelled_by,
            "driver_arrived_at": None if stop_offset_m > 200 else gps[-(wait_s // 5) - 1]["ts"]}
    return base_case("C-TEST-NS", "no_show", trip, gps, {"cancellation_fee": 6.61})


def by_id(facts, tmp_id):
    return next(f for f in facts if f.id == tmp_id)


# ---------------------------------------------------------------------------- route deviation

def test_route_excess_ratio():
    case = route_case()
    facts = get_route_facts(case)
    dist = by_id(facts, "gps-distance")
    expected = (haversine_m(*ORCHARD, *WAYPOINT) + haversine_m(*WAYPOINT, *MBS)) / 1000
    assert dist.value["actual_km"] == pytest.approx(expected, abs=0.05)
    assert dist.value["excess_km"] == pytest.approx(expected - 3.5, abs=0.05)
    assert dist.value["excess_pct"] == pytest.approx((expected - 3.5) / 3.5 * 100, abs=2)
    assert "vs optimal route 3.5 km" in dist.text


def test_route_stop_detected_away_from_endpoints():
    facts = get_route_facts(route_case())
    stops = [f for f in facts if f.id.startswith("gps-stop-")]
    assert len(stops) == 1
    s = stops[0]
    assert s.value["duration_s"] == pytest.approx(240, abs=10)
    assert (s.value["lat"], s.value["lon"]) == pytest.approx(WAYPOINT, abs=1e-4)
    assert s.value["m_from_pickup"] > tools.ENDPOINT_RADIUS_M
    assert "Not a pickup or drop-off point" in s.text


def test_route_detour_extra_km_and_duration():
    facts = get_route_facts(route_case())
    detours = [f for f in facts if f.id.startswith("gps-detour-")]
    assert len(detours) == 1
    assert detours[0].value["extra_km"] > 3.0          # whole trip goes via WAYPOINT, optimal is 3.3 km straight
    dur = by_id(facts, "gps-duration")
    assert dur.value["actual_min"] > dur.value["estimated_min"]


def test_short_stop_is_ignored():
    gps = track([ORCHARD, WAYPOINT, MBS], stop_at=1, stop_s=60)  # < 120 s
    case = route_case().model_copy(update={"gps": Case.model_validate(route_case().model_dump() | {"gps": gps}).gps})
    assert not [f for f in get_route_facts(case) if f.id.startswith("gps-stop-")]


def test_stop_detected_in_sparse_track():
    """Spec 1.3 sample: 4 points, all speed 0, two identical points at Middle Rd 14:12-14:16."""
    mid = (1.3012, 103.8531)
    gps = [{"ts": (T0 + timedelta(seconds=s)).isoformat(), "lat": la, "lon": lo, "speed_kmh": 0}
           for s, (la, lo) in [(0, ORCHARD), (410, mid), (662, mid), (1590, MBS)]]
    case = route_case().model_copy(update={"gps": Case.model_validate(route_case().model_dump() | {"gps": gps}).gps})
    stops = [f for f in get_route_facts(case) if f.id.startswith("gps-stop-")]
    assert len(stops) == 1
    assert stops[0].value["duration_s"] == 252
    assert (stops[0].value["lat"], stops[0].value["lon"]) == mid


# ---------------------------------------------------------------------------- no-show

def test_no_show_never_within_200m():
    facts = get_no_show_facts(no_show_case(stop_offset_m=600, wait_s=180))
    near = by_id(facts, "gps-nearest")
    assert near.value["nearest_m"] == pytest.approx(600, abs=30)
    assert near.value["within_200m"] is False
    assert "never came within 200 m" in near.text
    assert not [f for f in facts if f.id == "gps-within"]
    stop = by_id(facts, "gps-stop-1")
    assert stop.value["duration_s"] == pytest.approx(180, abs=10)
    assert stop.value["m_from_pickup"] == pytest.approx(600, abs=30)
    tl = by_id(facts, "tl-cancel")
    assert tl.value["cancelled_by"] == "driver" and tl.value["cancellation_fee"] == 6.61
    assert by_id(facts, "tl-arrival").value["driver_arrived_at"] is None


def test_no_show_within_200m_waited():
    facts = get_no_show_facts(no_show_case(stop_offset_m=50, wait_s=360))
    near = by_id(facts, "gps-nearest")
    assert near.value["nearest_m"] == pytest.approx(50, abs=10)
    assert near.value["within_200m"] is True
    within = by_id(facts, "gps-within")
    assert within.value["within_200m_s"] >= 360           # 360 s parked + the approach inside 200 m
    assert within.value["within_200m_s"] < 360 + 60
    arrival = by_id(facts, "tl-arrival")
    assert arrival.value["s_arrival_to_cancel"] == pytest.approx(360, abs=10)


# ---------------------------------------------------------------------------- fare / chat / traffic

def test_fare_default_rate_when_rates_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "RATES_PATH", tmp_path / "rates.json")
    facts = get_fare_facts(route_case())
    ex = by_id(facts, "fare-excess")
    assert ex.value["rate_km"] == 1.41
    assert ex.value["excess_amount"] == pytest.approx((7.4 - 3.5) * 1.41, abs=0.01)
    assert "default rate" in ex.text
    assert by_id(facts, "fare-surge").value["surge_multiplier"] == 1.0


def test_fare_reads_rates_file(monkeypatch, tmp_path):
    p = tmp_path / "rates.json"
    p.write_text('{"rate_km": 2.0, "rate_wait": 0.5}')
    monkeypatch.setattr(tools, "RATES_PATH", p)
    facts = get_fare_facts(route_case())
    assert by_id(facts, "fare-excess").value["rate_km"] == 2.0
    assert "default" not in by_id(facts, "fare-excess").text
    assert "2.2 min" in by_id(facts, "fare-wait").text


def test_chat_facts_are_verbatim_timestamped_and_unlabelled():
    facts = get_chat_facts(route_case())
    assert facts[0].text.startswith("Chat #1") and facts[1].text.startswith("Chat #2")
    for f in facts:
        assert "flags" not in (f.value or {}) and "[agreement]" not in f.text and "[request]" not in f.text and "[threat]" not in f.text
    assert facts[0].value["from"] == "driver" and facts[0].value["ts"]
    rec = by_id(facts, "chat-record")
    assert rec.value["complete"] is True and rec.value["count"] == 2


def test_chat_hint_word_is_a_locator_not_a_finding():
    base = route_case()
    case = base.model_copy(update={"chat": Case.model_validate(base.model_dump() | {
        "chat": [{"ts": T0.isoformat(), "from": "driver", "text": "sit down or I lock the doors"},
                 {"ts": (T0 + timedelta(seconds=30)).isoformat(), "from": "rider", "text": "I cannot find you at the pickup point."}]}).chat})
    facts = get_chat_facts(case)
    assert by_id(facts, "chat-1").value["keyword_hint"] == "lock the door"
    assert by_id(facts, "chat-2").value["keyword_hint"] == "find you"          # the same hint on an ordinary line: the court reads it
    assert not [f for f in facts if "threat" in (f.value or {})]              # no fact says "threat": that is the judge's finding
    assert not [f for f in facts if f.id.startswith("chat-threat")]


def test_untimed_message_makes_the_record_incomplete():
    base = route_case()
    case = base.model_copy(update={"chat": Case.model_validate(base.model_dump() | {
        "chat": [{"from": "rider", "text": "Sure, go ahead."}]}).chat})
    facts = get_chat_facts(case)
    assert by_id(facts, "chat-1").value["ts"] is None and "time not recorded" in by_id(facts, "chat-1").text
    rec = by_id(facts, "chat-record")
    assert rec.value["complete"] is False and rec.value["untimed"] == 1


def test_traffic_band_translation():
    facts = get_traffic_facts(route_case())
    band = by_id(facts, "traffic-band-1")
    assert "0–9 km/h" in band.text and band.value["severe"] is True
    assert by_id(facts, "traffic-incident-none").value["count"] == 0


# ---------------------------------------------------------------------------- fact table

def assert_numbered(table):
    assert [f.id for f in table.facts] == [f"F{i}" for i in range(1, len(table.facts) + 1)]
    order = [SOURCE_ORDER.index(f.source) for f in table.facts]
    assert order == sorted(order)


def test_build_fact_table_numbering_and_slices():
    table = build_fact_table(route_case())
    assert_numbered(table)
    assert table.dispute_type == "route_deviation"
    assert table.facts[0].source == "gps"
    assert {f.source for f in table.facts} == {"gps", "fare", "chat", "traffic", "weather", "profile"}
    assert build_fact_table(route_case()) == table                    # deterministic
    gps_slice = facts_for_tool(table, "get_route_facts")
    assert gps_slice and all(f.source == "gps" for f in gps_slice)
    assert all(f.id in table.ids() for f in facts_for_tool(table, "get_traffic_facts"))


def test_build_fact_table_no_show():
    table = build_fact_table(no_show_case(600, 180))
    assert_numbered(table)
    srcs = [f.source for f in table.facts]
    assert srcs.index("timeline") > srcs.index("gps") and "fare" in srcs
    assert any("never came within 200 m" in f.text for f in table.facts)


# ---------------------------------------------------------------------------- real case files when present

@pytest.mark.skipif(not (CASES_DIR / "C-0001.json").exists(), reason="data/cases/C-0001.json not generated yet")
def test_c0001_file():
    case = Case.model_validate_json((CASES_DIR / "C-0001.json").read_text())
    table = build_fact_table(case)
    assert_numbered(table)
    dist = next(f for f in table.facts if f.value and "excess_pct" in f.value)
    assert dist.value["excess_pct"] > 15 and dist.value["excess_km"] > 1.0       # RD-1 threshold, per 1.7 script
    assert any(f.value and "duration_s" in f.value for f in table.facts)         # the 7-Eleven stop


@pytest.mark.skipif(not (CASES_DIR / "C-0004.json").exists(), reason="data/cases/C-0004.json not generated yet")
def test_c0004_file():
    case = Case.model_validate_json((CASES_DIR / "C-0004.json").read_text())
    table = build_fact_table(case)
    assert_numbered(table)
    near = next(f for f in table.facts if f.value and "nearest_m" in f.value)
    assert near.value["nearest_m"] > 200 and near.value["within_200m"] is False   # driver parked 600 m out


# ---------------------------------------------------------------------------- organisers' sample format: platform auto-arrival, wait timer, policy parameters, call attempts

def test_platform_auto_arrival_counts_as_arrival_confirmation():
    from core.policy_engine import evaluate
    case = no_show_case(stop_offset_m=50, wait_s=480)
    here_at = case.trip.driver_arrived_at
    trip = case.trip.model_copy(update={"driver_pressed_here_at": here_at, "arrival_confirmed_by": "platform_auto", "arrival_radius_m": 10,
                                        "wait_started_at": here_at, "wait_expired_at": here_at + timedelta(minutes=5)})
    case = case.model_copy(update={"trip": trip})
    facts = get_no_show_facts(case)
    here = by_id(facts, "tl-here")
    assert here.value["arrival_confirmed_by"] == "platform_auto" and "auto-confirmed" in here.text and "10 m" in here.text
    wait = by_id(facts, "tl-wait")
    assert wait.value["wait_window_s"] == 300
    cert = evaluate(case, build_fact_table(case))
    i = next(p for p in cert.predicates if p.clause == "NS-1" and p.element.startswith("(i)"))
    assert i.status == "pass" and "platform auto-arrival" in i.detail
    assert cert.allowed == ["no_action", "escalate"]


def test_policy_params_override_wait_window_and_fee():
    from core.policy_engine import evaluate, GRACE_S, CANCEL_FEE
    from core.schemas import PolicyParams
    base = no_show_case(stop_offset_m=50, wait_s=240)        # 4 min inside the radius
    base = base.model_copy(update={"trip": base.trip.model_copy(update={"driver_pressed_here_at": base.trip.driver_arrived_at})})
    default = evaluate(base, build_fact_table(base))
    assert default.grace == GRACE_S and default.fee == CANCEL_FEE and default.allowed == ["no_action", "escalate"]    # 4 min > Ryde's 3 min
    stricter = base.model_copy(update={"policy_params": PolicyParams(free_wait_min=5, cancellation_fee=5.0)})
    cert = evaluate(stricter, build_fact_table(stricter))
    assert cert.grace == 300 and cert.fee == 5.0
    assert cert.allowed == ["refund_full", "escalate"] and "5.00" in cert.amount_formula                         # 4 min < the record's 5 min
    assert any("parameters from the case record" in l for l in cert.lines())


def test_call_attempts_are_counted_in_chat_facts():
    from core.schemas import ChatMessage
    case = no_show_case(stop_offset_m=50, wait_s=360)
    chat = [ChatMessage(ts=T0, **{"from": "driver"}, text="I'm at the lobby"),
            ChatMessage(ts=T0 + timedelta(minutes=2), **{"from": "driver"}, text="Outgoing call, not answered", kind="call"),
            ChatMessage(ts=T0 + timedelta(minutes=4), **{"from": "driver"}, text="Outgoing call, not answered", kind="call")]
    facts = get_chat_facts(case.model_copy(update={"chat": chat}))
    calls = by_id(facts, "chat-calls")
    assert calls.value == {"calls_driver": 2, "calls_rider": 0, "messages_driver": 1, "messages_rider": 0}
    assert "[call]" in by_id(facts, "chat-2").text
