"""The reference answer of a synthetic case, derived from the raw record and the scenario's labels WITHOUT the engine.

`derive_reference(raw, cond, kind)` measures the record with contract.py's own geometry and applies the frozen rules
of policy/policy.md as written (RD-1..RD-6, NS-1..NS-4, G12, G13, SAFE-1). scenarios.derive_truth runs the engine
(core/) on the same record and refuses to publish a case where the two disagree; tests/test_contract.py re-runs this
function over every committed case. A rule shared by this file and the engine is the only kind of error neither can
see; the policy boundary tests (tests/test_evidence.py) cover those by hand-written vectors.

Labels the derivation reads (the interpretive slots a judge fills from the chat, decided by the scenario's story):
  consent  before / named_singlish / named_cn / before_seg1(loop 1)  -> agreement to a NAMED road, nothing ties the
           driven segment to it: undetermined (G13); general / general_cn -> the loop is covered; everything else counts
  stop     named -> the rider's own request, exempt (RD-3(a)); unnamed / driver_errand -> counts
  threat   driver / chat=threat -> the safety screen (SAFE-1) sends the case to a person
Everything else (incident on the stretch and its timing, holes, coverage, waits, taps, amounts) is measured.
"""
from __future__ import annotations

import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402
from fare import slice_gps  # noqa: E402

GRACE_S = 180                # NS-4: a rider may cancel free within this of acceptance; NS-1: the driver's default wait (strict >)
GPS_GAP_S = 120              # a hole is a gap longer than this AND longer than twice the trace's own median interval
CADENCE_MIN_SAMPLES = 6
MIN_BYPASS_KM = 0.3          # RD-4: a spur whose entry and exit are closer than this replaces nothing, so no incident can sit "on" it


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def hole_threshold_s(points) -> tuple[float, float | None]:
    if len(points) < CADENCE_MIN_SAMPLES:
        return GPS_GAP_S, None
    ints = sorted((_ts(b["ts"]) - _ts(a["ts"])).total_seconds() for a, b in zip(points, points[1:]))
    med = ints[len(ints) // 2]
    return max(GPS_GAP_S, 2 * med), med


def holes(points, w0: str | None = None, w1: str | None = None) -> list[tuple[str, str]]:
    thr, _ = hole_threshold_s(points)
    out = []
    for a, b in zip(points, points[1:]):
        if (_ts(b["ts"]) - _ts(a["ts"])).total_seconds() > thr and (not w1 or a["ts"] < w1) and (not w0 or b["ts"] > w0):
            out.append((a["ts"], b["ts"]))
    return out


def uncovered(points, start: str, end: str) -> tuple[float, float]:
    """Seconds of `start..end` before the first and after the last sample, when beyond the hole threshold (else 0)."""
    thr, _ = hole_threshold_s(points)
    head = (_ts(points[0]["ts"]) - _ts(start)).total_seconds() if points else 0
    tail = (_ts(end) - _ts(points[-1]["ts"])).total_seconds() if points else 0
    return (head if head > thr else 0.0), (tail if tail > thr else 0.0)


def escalate() -> dict:
    return {"ruling": "escalate", "amount": None, "flag_account": False}


def derive_reference(raw: dict, cond: dict, kind: str) -> dict:
    t = raw["trip"]
    if kind == "safety":
        return escalate()
    if cond.get("threat") == "driver" or cond.get("chat") == "threat":
        return escalate()
    if kind == "no_show":
        return _no_show(raw, cond)
    return _route(raw, cond)


def _no_show(raw: dict, cond: dict) -> dict:
    t, gps = raw["trip"], raw["gps"]
    P = (t["pickup"]["lat"], t["pickup"]["lon"])
    fee = raw["fare"]["cancellation_fee"]
    if t.get("cancelled_by") not in ("rider", "driver"):
        return escalate()                                              # G12: who cancelled is not on record
    s_cancel = (_ts(t["cancelled_at"]) - _ts(t["accepted_at"])).total_seconds()
    if t["cancelled_by"] == "rider":                                   # NS-4
        return {"ruling": "no_action" if s_cancel > GRACE_S else "refund_full", "amount": None if s_cancel > GRACE_S else fee, "flag_account": False}
    if not t.get("driver_pressed_here_at"):                            # NS-3: no arrival confirmation -> the fee is refunded
        return {"ruling": "refund_full", "amount": fee, "flag_account": False}
    tap = t["driver_pressed_here_at"]
    at = min(gps, key=lambda p: abs((_ts(p["ts"]) - _ts(tap)).total_seconds()))
    if contract.hav_m((at["lat"], at["lon"]), P) > contract.PICKUP_RADIUS_M:   # NS-2: tapped "I'm Here" away from the pickup
        return {"ruling": "refund_full", "amount": fee, "flag_account": True}
    pp = raw.get("policy_params") or {}
    T, inclusive = (pp["no_show_threshold_min"] * 60, True) if pp.get("no_show_threshold_min") else (GRACE_S, False)
    wait = [p for p in gps if tap <= p["ts"] <= t["cancelled_at"]]
    if not wait or holes(gps, tap, t["cancelled_at"]):                  # G12: the wait is not on record, or has a hole in it
        return escalate()
    cont = contract.continuous_after_tap_s(gps, P, _ts(tap))
    reached = cont >= T if inclusive else cont > T
    if reached:
        return {"ruling": "no_action", "amount": None, "flag_account": False}
    _, tail = uncovered(wait, tap, t["cancelled_at"])
    left_radius = any(contract.hav_m((p["lat"], p["lon"]), P) > contract.PICKUP_RADIUS_M for p in wait)
    if tail and not left_radius and ((cont + tail >= T) if inclusive else (cont + tail > T)):
        return escalate()                                              # G12: the uncovered tail would decide it
    return {"ruling": "refund_full", "amount": fee, "flag_account": False}


def _route(raw: dict, cond: dict) -> dict:
    t = raw["trip"]
    poly = [tuple(p) for p in raw["route"]["polyline"]]
    trip_gps = slice_gps(raw["gps"], t["pickup_at"], t["dropoff_at"])
    if not trip_gps or holes(trip_gps) or any(uncovered(trip_gps, t["pickup_at"], t["dropoff_at"])):
        return escalate()                                              # G12: an off-route stretch inside a hole / the uncovered part cannot be measured
    segs = contract.segments(trip_gps, poly)
    if not segs:
        return {"ruling": "no_action", "amount": None, "flag_account": False}   # RD-1 fails
    metered = raw["fare"]["pricing"] == "metered"
    rate = raw["fare"]["distance_fare"] / raw["fare"]["distance_km"] if metered else None
    prior = raw["profiles"]["driver"]["route_disputes_upheld_90d"] >= 1
    consent, stop = cond.get("consent", "none"), cond.get("stop", "none")
    findings = []
    for k, s in enumerate(segs):
        incident_exempt = False
        for inc in raw["traffic"]["incidents"]:                        # RD-4(a): a reported incident on the replaced stretch, reported before the segment
            d, along = contract.project(inc["lat"], inc["lon"], poly)
            on = (d <= contract.INCIDENT_NEAR_M and s["exit_km"] - s["entry_km"] >= MIN_BYPASS_KM
                  and s["entry_km"] - contract.STRETCH_TOL_KM <= along <= s["exit_km"] + contract.STRETCH_TOL_KM)
            if on and inc["reported_at"] < s["start"]:
                incident_exempt = True
        if incident_exempt:
            findings.append("exempt")
        elif consent in ("before", "named_singlish", "named_cn") or (consent == "before_seg1" and k == 0):
            findings.append("undetermined")                            # RD-5 + G13
        elif stop == "named" or consent in ("general", "general_cn"):
            findings.append("exempt")                                  # RD-3(a) / RD-5 general route choice
        else:
            findings.append("counts")
    if "undetermined" in findings and (metered or prior):
        return escalate()                                              # the open finding changes the amount (RD-2) or the flag (RD-6)
    counts = [s for s, f in zip(segs, findings) if f == "counts"]
    amount = round(sum(s["extra_km"] for s in counts) * rate + 1e-9, 2) if (metered and counts) else None
    return {"ruling": "refund_partial" if amount else "no_action", "amount": amount, "flag_account": bool(prior and counts)}
