"""The reference answer of a synthetic case, derived from the raw record and the scenario's labels WITHOUT the engine.

`derive_reference(raw, cond, kind)` measures the record with contract.py's own geometry and applies the rules of
policy/policy.md (v3, the organisers' policy v2.1 plus the system details written there) as code: RD-1..RD-7, NS-0..NS-9,
SURGE-1..SURGE-3, SAFE-1, TH-1..TH-4. It returns the whole expected answer (ruling, amount, cited_policy, escalate,
rationale, flag_account, and goodwill_credit / evidence_gap when they apply) plus `_trace`, the checks it made.
scenarios.py publishes this answer; unless SYNTH_SKIP_ENGINE_CHECK=1 it also runs the engine (core/) on the same record
and refuses a case where the two disagree. tests/test_contract.py re-runs this function over every committed case.
Nothing here imports core/: a rule the engine and this file read the same wrong way is the only error neither can see.

Labels the derivation reads (the interpretive slots a judge fills from the chat, decided by the scenario's story):
  consent  before / named_singlish / named_cn / before_seg1 (loop 1) / named_elsewhere / recorded_call (the agreement is in
           the transcript of a recorded call before pickup) -> the rider agreed to "go via X";
           whether X is a road this segment drove is MEASURED from the GPS road names (RD-5): among them -> exempt, not ->
           counts, no road names on the segment -> undetermined (a person decides)
           general / general_cn -> a general route choice covers the loop (exempt); qualified ("can, but not via Y") -> counts
           when the segment drove Y (measured), else exempt; general_errand / negation / request_only / scope_other / after ->
           counts; verbal_unrecorded (the driver claims a spoken agreement, the call has no recording) -> no rider words on
           record, counts
  stop     named -> the rider's own request, exempt (RD-3); unnamed / driver_errand -> counts
  threat   driver / chat=threat / complaint_safety -> the safety screen (SAFE-1) sends the case to a person
  notice   (surge) what a timely in-app notice's text states: full / no_cancel / no_fare / no_multiplier / cancel_fee
  reason_reading  (no-show) why the driver cancelled, read from his own words: no_show / own_reason (NS-0, NS-3)
Everything else (who wrote what before which segment, incidents and bands on the replaced stretch, holes, waits, taps,
contact attempts, multipliers, notices, amounts, the TH bands) is measured. A segment with no rider message before it
counts without any reading; a route case where some segment has one rests on a judge reading (TH-3 confidence 0.90).
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402
from fare import slice_gps, surgeable_subtotal  # noqa: E402

GRACE_S = 180                # NS-4: a rider may cancel free within 3 minutes of matching (strictly more is chargeable)
FREE_WAIT_S = 300            # NS-1 (ii): the 5-minute free wait, inclusive ("after 5 minutes")
CANCEL_FEE = 5.00            # NS-1 / NS-4: the official fee when the record states none
GOODWILL = 5.00              # NS-8: credit when the late driver made no contact attempt
TOLERANCE_KM = 1.0           # RD-1: applied to what is left once exempt segments are taken out (residue = GPS jitter)
TH_CONFIDENT, TH_MANUAL = 10.0, 50.0   # TH-1: from $10 confidence must reach 80%; above $50 a person decides
CONF_JUDGE, CONF_FRAUD = 0.90, 0.97    # TH-3 as code computes it: a judge reading costs 10%, a fraud flag 3%
GPS_GAP_S = 120              # a hole is a gap longer than this AND longer than twice the trace's own median interval
CADENCE_MIN_SAMPLES = 6
MIN_BYPASS_KM = 0.3          # RD-4: a spur whose entry and exit are closer than this replaces nothing, so no incident can sit "on" it
TIED_CONSENT = ("before", "named_singlish", "named_cn", "named_elsewhere", "recorded_call", "notice_ack")


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
        if (_ts(b["ts"]) - _ts(a["ts"])).total_seconds() > thr and (not w1 or _ts(a["ts"]) < _ts(w1)) and (not w0 or _ts(b["ts"]) > _ts(w0)):
            out.append((a["ts"], b["ts"]))
    return out


def uncovered(points, start: str, end: str) -> tuple[float, float]:
    """Seconds of `start..end` before the first and after the last sample, when beyond the hole threshold (else 0)."""
    thr, _ = hole_threshold_s(points)
    head = (_ts(points[0]["ts"]) - _ts(start)).total_seconds() if points else 0
    tail = (_ts(end) - _ts(points[-1]["ts"])).total_seconds() if points else 0
    return (head if head > thr else 0.0), (tail if tail > thr else 0.0)


EXPRESSWAYS = {"AYE": "AYER RAJAH EXPRESSWAY", "BKE": "BUKIT TIMAH EXPRESSWAY", "CTE": "CENTRAL EXPRESSWAY", "ECP": "EAST COAST PARKWAY",
               "KJE": "KRANJI EXPRESSWAY", "KPE": "KALLANG PAYA LEBAR EXPRESSWAY", "MCE": "MARINA COASTAL EXPRESSWAY", "PIE": "PAN ISLAND EXPRESSWAY",
               "SLE": "SELETAR EXPRESSWAY", "TPE": "TAMPINES EXPRESSWAY"}   # how riders and drivers name them


def norm_road(name: str) -> str:
    n = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("'S", "S"))).strip()
    return EXPRESSWAYS.get(n, n)


def road_match(name: str, roads: list[str]) -> bool:
    """`name` is one of `roads` (case and punctuation ignored; a whole-word containment either way counts)."""
    n = norm_road(name)
    for r in roads:
        m = norm_road(r)
        if n and m and (n == m or re.search(rf"\b{re.escape(n)}\b", m) or re.search(rf"\b{re.escape(m)}\b", n)):
            return True
    return False


def fraud_flag(raw: dict) -> bool:
    p = raw.get("profiles") or {}
    return any(((p.get(k) or {}).get("fraud_flags") or 0) >= 1 for k in ("rider_account", "driver_account"))


def answer(ruling: str, amount, cited: list[str], why: list[str], flag: bool = False, **extra) -> dict:
    out = {"ruling": ruling, "amount": amount, "cited_policy": cited, "escalate": ruling == "escalate",
           "rationale": " ".join(why), "flag_account": bool(flag)}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def escalate(cited: list[str], why: list[str], gap: str | None = None) -> dict:
    return answer("escalate", None, cited, why, False, evidence_gap=gap)


def th_gate(res: dict, judge_reading: bool, fraud: bool, why: list[str]) -> dict:
    """TH-1 / TH-3: may the outcome execute without a person? Amount = refund + goodwill credit. The thresholds are
    applied by code, so they are named in the rationale, never in cited_policy."""
    amt = float(res.get("amount") or 0) + float(res.get("goodwill_credit") or 0)
    conf = (CONF_JUDGE if judge_reading else 1.0) * (CONF_FRAUD if fraud else 1.0)
    need = 0.95 if fraud else (0.80 if amt >= TH_CONFIDENT else 0.0)
    if amt > TH_MANUAL:
        return escalate(res["cited_policy"], why + [f"${amt:.2f} is above ${TH_MANUAL:.0f}: a person decides; the system prepares the case file (TH-1)."])
    if conf < need - 1e-9:
        merit = res["ruling"] + (f" ${res['amount']:.2f}" if res.get("amount") else "") + (" + flag_account" if res.get("flag_account") else "")
        what = judge_reading if isinstance(judge_reading, str) else "what was said"
        if fraud:
            line = (f"A fraud flag raises the bar to 95% (TH-3). The outcome rests on reading {what}; a lone reading gives {conf:.0%}. "
                    f"Settled by agreement (both sides read it the same way) -> {merit}; otherwise a person decides.")
        else:
            line = f"Would be {merit}, but ${amt:.2f} needs 80% confidence (TH-1) and code confidence is {conf:.0%}: a person decides."
        out = escalate(res["cited_policy"], why + [line])
        # the policy's answer once the reading is settled (both advocates reading the text alike lifts the confidence)
        return {**out, "merits": {"ruling": res["ruling"], "amount": res.get("amount"), "flag_account": bool(res.get("flag_account"))}}
    notes = []
    if amt >= TH_CONFIDENT:
        notes.append(f"${amt:.2f} is in the $10-50 band: code confidence {conf:.0%} >= 80%, the system decides (TH-1).")
    if fraud:
        notes.append(f"A party carries a fraud flag, so the threshold is 95%; code confidence {conf:.0%} meets it and the profile does not decide the case (TH-3).")
    if notes:
        res = {**res, "rationale": res["rationale"] + " " + " ".join(notes)}
    return res


# ----------------------------------------------------------------------------------------------- entry point

def safety_summary(raw: dict) -> list[str]:
    """Who said what, and when: the factual summary a reviewer gets (SAFE-3: no fault, no recommended outcome)."""
    d = raw["dispute"]
    out = [f"Complaint filed by the {d['filed_by']} at {d['filed_at'][11:16]}: \"{d['statement']}\""]
    out += [f"Chat {m['ts'][11:19]} {m['from']}: \"{m['text']}\"" for m in raw["chat"] if m.get("ts")]
    if raw.get("driver_statement"):
        out.append(f"Driver's statement: \"{raw['driver_statement']}\"")
    t = raw["trip"]
    if t.get("pickup_at") and t.get("dropoff_at"):
        out.append(f"Trip {t['pickup_at'][11:16]}-{t['dropoff_at'][11:16]}, {t['pickup']['name']} to {t['dropoff']['name']}.")
    return [" ".join(out)]


def derive_reference(raw: dict, cond: dict, kind: str) -> dict:
    if kind == "safety":
        dangerous = bool(cond.get("speeding")) or (cond.get("chat") == "innocuous" and not cond.get("statement_threat"))
        return escalate(["SAFE-1", "SAFE-2"] if dangerous else ["SAFE-1"],
                        safety_summary(raw) + ["Filed as a safety incident: a person reviews it (SAFE-1" + (", SAFE-2" if dangerous else "") + ")."])
    if cond.get("threat") == "driver" or cond.get("chat") == "threat":
        return escalate(["SAFE-1"], safety_summary(raw) + [f"The {kind.replace('_', ' ')} dispute's chat holds an intimidating message: the safety screen sends it to a person (SAFE-1)."])
    if cond.get("complaint_safety"):
        return escalate(["SAFE-1"], safety_summary(raw) + [f"Filed as a {kind.replace('_', ' ')} dispute, but the complaint alleges conduct that makes it a safety matter: "
                                                           "the safety screen sends it to a person (SAFE-1)."])
    if kind == "no_show":
        return _no_show(raw, cond)
    if kind == "fare_dispute":
        return _surge(raw, cond)
    return _route(raw, cond)


# ----------------------------------------------------------------------------------------------- route deviation

def segment_roads(trip_gps, seg) -> list[str]:
    out = []
    for p in trip_gps:
        if seg["start"] <= p["ts"] <= seg["end"] and p.get("road") and p["road"] not in out:
            out.append(p["road"])
    return out


def named_road(raw: dict) -> str | None:
    """The road the driver proposed and the rider agreed to: 'go round via X?' in the driver's request (chat, or the
    transcript of a recorded call)."""
    texts = [m["text"] for m in raw["chat"] if m["from"] == "driver"] + [c["transcript"] for c in raw.get("calls", []) if c.get("transcript")]
    for t in texts:
        x = re.search(r"(?:go round via|go round by|can go via|going via|go by) (.+?)(?: instead)?(?:,|[?.]| ok)", t)
        if x:
            return x.group(1)
    return None


def excluded_road(raw: dict) -> str | None:
    """The road a rider's qualified yes rules out: 'Can lah, but not via Y.'"""
    for m in raw["chat"]:
        if m["from"] == "rider":
            x = re.search(r"not via (.+?)\.|不要走 (.+?)。", m["text"])
            if x:
                return x.group(1) or x.group(2)
    return None


def recorded_rider_words(raw: dict, before: str) -> list[dict]:
    """Calls before `before` whose recording transcript carries the rider's own words (RD-5: verbal notice with a recording)."""
    return [c for c in raw.get("calls", []) if c.get("recording_ref") and "Rider:" in (c.get("transcript") or "")
            and c.get("ts") and _ts(c["ts"]) <= _ts(before)]


def traffic_reason(raw: dict, seg: dict, poly) -> list[str]:
    """RD-4: an incident on the replaced stretch reported before the segment (by coordinates within 300 m, or by road name
    on the optimal route and not cleared), or a speed band 1-2 on a road of the replaced stretch overlapping the segment."""
    start = _ts(seg["start"])
    lo, hi = seg["entry_km"], seg["exit_km"]
    out = []
    for inc in raw["traffic"].get("incidents", []):
        d, along = contract.project(inc["lat"], inc["lon"], poly)
        if hi - lo >= MIN_BYPASS_KM and d <= contract.INCIDENT_NEAR_M and lo - contract.STRETCH_TOL_KM <= along <= hi + contract.STRETCH_TOL_KM \
                and _ts(inc["reported_at"]) < start:
            out.append(f"{inc['type']} reported {inc['reported_at'][11:16]}")
    route_roads = [r["name"] for r in raw["route"].get("roads", [])]
    for inc in raw["traffic"].get("road_incidents", []):
        if inc.get("road") and road_match(inc["road"], route_roads) and inc.get("reported_at") and _ts(inc["reported_at"]) <= start \
                and (not inc.get("cleared_at") or _ts(inc["cleared_at"]) >= start) and (inc.get("incident_type") or "") != "traffic_flow":
            out.append(f"{inc.get('incident_type')} on {inc['road']}")
    labels = [r["name"] for r in raw["route"].get("roads", []) if (lo - 0.3) * 1000 <= r["to_m"] and r["from_m"] <= (hi + 0.3) * 1000]
    for b in raw["traffic"].get("speed_bands", []):
        if b["speed_band"] <= 2 and _ts(b["window_start"]) <= _ts(seg["end"]) and start <= _ts(b["window_end"]) and road_match(b["road_name"], labels):
            out.append(f"speed band {b['speed_band']} on {b['road_name'].title()}")
    return out


def _route(raw: dict, cond: dict) -> dict:
    t, fare = raw["trip"], raw["fare"]
    poly = [tuple(p) for p in raw["route"]["polyline"]]
    trip_gps = slice_gps(raw["gps"], t["pickup_at"], t["dropoff_at"])
    rider_words = any(m["from"] == "rider" and m.get("kind", "message") == "message" for m in raw["chat"]) or recorded_rider_words(raw, t["dropoff_at"])
    if not trip_gps or ((holes(trip_gps) or any(uncovered(trip_gps, t["pickup_at"], t["dropoff_at"]))) and rider_words):
        gap = ("the GPS trace has a hole" if trip_gps and holes(trip_gps) else "the GPS trace does not cover the whole trip") + \
              ": whether the car went where the rider asked in the uncovered part cannot be measured"
        return escalate(["RD-1", "RD-2", "RD-3"], [f"Evidence insufficient: {gap}; missing records favour neither party (TH-4) -> escalate."], gap)
    segs = contract.segments(trip_gps, poly)
    D = round(fare["distance_km"] - raw["route"]["total_km"], 2)
    xf = (raw.get("fare_detail") or {}).get("excess_distance_fare")
    rate = xf / D if (xf and D > 0) else fare["distance_fare"] / fare["distance_km"]
    if D <= TOLERANCE_KM or not segs:
        why = (f"Billed distance {fare['distance_km']:.2f} km vs optimal {raw['route']['total_km']:.2f} km: deviation {D:.2f} km is within the {TOLERANCE_KM:g} km tolerance (RD-1) -> no refund."
               if segs or D > TOLERANCE_KM else "No off-route segment: the GPS follows the optimal route (RD-1) -> no refund.")
        return answer("no_action", None, ["RD-1"], [why])
    msgs = [m for m in raw["chat"] if m.get("kind", "message") == "message"]
    consent, stop = cond.get("consent", "none"), cond.get("stop", "none")
    X = named_road(raw)
    findings, notes, judge, reasons = [], [], False, []
    for k, s in enumerate(segs):
        fid = f"segment {k + 1} ({s['start'][11:19]}-{s['end'][11:19]}, +{s['extra_km']:.2f} km)"
        reason = traffic_reason(raw, s, poly)
        reasons.append(reason)
        rider_before = [m for m in msgs if m["from"] == "rider" and m.get("ts") and _ts(m["ts"]) <= _ts(s["start"])] + recorded_rider_words(raw, s["start"])
        if not rider_before:
            findings.append("counts")
            notes.append(f"{fid}: no rider message (and no recorded call with the rider's words) before it started, so neither RD-5 nor RD-3 "
                         "can excuse it" + (" - the driver's account of a spoken agreement is not a recording" if consent == "verbal_unrecorded" else "") + " -> counts")
            continue
        judge = True
        if consent in TIED_CONSENT or (consent == "before_seg1" and k == 0):
            roads = segment_roads(trip_gps, s)
            if not roads:
                f = "undetermined"
                notes.append(f"{fid}: the rider agreed to go via {X}; the record names no roads for this segment -> undetermined (RD-5)")
            elif X and road_match(X, roads):
                f = "exempt"
                notes.append(f"{fid}: the rider agreed beforehand to go via {X}, and the segment drove it ({', '.join(r.title() for r in roads)}) -> exempt (RD-5)")
            else:
                f = "counts"
                notes.append(f"{fid}: the rider agreed to go via {X}, but the segment drove {', '.join(r.title() for r in roads)}, not {X} -> the agreement does not cover it, counts (RD-5)")
        elif consent in ("qualified", "excluded_not_driven"):
            Y, roads = excluded_road(raw), segment_roads(trip_gps, s)
            if Y and road_match(Y, roads):
                f = "counts"
                notes.append(f"{fid}: the rider said yes 'but not via {Y}', and the segment drove {Y} -> the agreement does not cover it, counts (RD-5)")
            else:
                f = "exempt"
                notes.append(f"{fid}: the rider agreed to another way except {Y}, and the segment kept off it -> exempt (RD-5)")
        elif consent in ("general", "general_cn", "general_buried", "general_rider"):
            f = "exempt"
            notes.append(f"{fid}: the rider gave a general route choice before it started -> the rider's route, exempt (RD-5)")
        elif stop == "named":
            f = "exempt"
            notes.append(f"{fid}: the rider named the place before it started and the car stopped there -> exempt (RD-3)")
        else:
            f = "counts"
            what = {"general_errand": "a general route choice does not cover the driver's own stop", "negation": "the rider refused the change",
                    "request_only": "the rider never answered the driver's request", "scope_other": "the rider agreed to a short stop, not this loop",
                    "after": "the rider's agreement came after the segment started", "before_seg1": "the rider's agreement covered the first segment only",
                    "retracted": "the rider said ok, then took it back ('actually no, please stay on ...') before the turn-off",
                    "conditional": "the rider agreed only 'if it's faster', and the trip ran well over the estimate: the condition failed",
                    "misattributed": "the rider's only 'ok' answered a question about luggage; the route notice that followed got no answer",
                    "sarcastic": "the rider's reply is a sarcastic objection, not an acknowledgement"}
            notes.append(f"{fid}: " + (what.get(consent) or ("the rider named one 7-Eleven and the car stopped at another, off the route (RD-3 not met)" if stop == "named_missed" else
                                                         "the rider asked for 'a 7-Eleven' without naming a place, the driver chose a far one (RD-3)" if stop == "unnamed"
                                                         else "the rider's messages before it do not agree to it")) + " -> counts")
        findings.append(f)
    if "undetermined" in findings:
        gap = "a segment's road names are missing, so the rider's agreement to a named road cannot be checked against it"
        return {**escalate(["RD-1", "RD-2", "RD-5"], notes + [f"Evidence insufficient (TH-4): {gap} -> escalate."], gap), "_findings": findings}
    exempt_km = sum(s["extra_km"] for s, f in zip(segs, findings) if f == "exempt")
    left = round(max(0.0, D - exempt_km), 2)
    cited = ["RD-1", "RD-2"]
    if consent != "none":
        cited.append("RD-5")
    if stop != "none" or (consent != "general_rider" and any(f == "exempt" and not r for f, r in zip(findings, reasons))):
        cited.append("RD-3")         # a rider-named stop, or an agreed reroute with no traffic reason: the rider's own route
    why = [f"Deviation {D:.2f} km (billed {fare['distance_km']:.2f} km − optimal {raw['route']['total_km']:.2f} km) over {len(segs)} off-route segment(s)."] + [n + "." for n in notes]
    if left <= TOLERANCE_KM:
        why.append(f"Less the exempt {exempt_km:.2f} km, {left:.2f} km is left: within the {TOLERANCE_KM:g} km tolerance (RD-1) -> no refund.")
        res = answer("no_action", None, cited, why)
        prior = raw["profiles"]["driver"]["route_disputes_upheld_90d"]
        if prior:
            res["rationale"] += f" The driver's {prior} prior upheld route dispute(s) do not trigger RD-6: nothing is upheld against him."
        return {**th_gate(res, "the rider's words before the detour" if judge else False, fraud_flag(raw), why), "_findings": findings}
    amount = round(left * rate + 1e-9, 2)
    counted = [k for k, f in enumerate(findings) if f == "counts"]
    with_reason = [k for k in counted if reasons[k]]
    without = [k for k in counted if not reasons[k]]
    why.append(f"Refund = ({D:.2f} − {exempt_km:.2f}) km × ${rate:.4f}/km = ${amount:.2f} (RD-2).")
    if with_reason:
        cited.append("RD-4")
        why.append("Traffic reason on record for segment(s) " + ", ".join(str(k + 1) for k in with_reason) + " (" + "; ".join(r for k in with_reason for r in reasons[k])
                   + "), but the rider was not informed of this route and did not agree to it beforehand: refund, no violation; the driver gets a notification-duty reminder (RD-2, RD-7).")
        cited.append("RD-7")
    if without:
        why.append("No traffic reason for segment(s) " + ", ".join(str(k + 1) for k in without) + ": a driver violation is recorded (RD-2).")
    prior = raw["profiles"]["driver"]["route_disputes_upheld_90d"]
    flag = prior >= 1
    if flag:
        cited.append("RD-6")
        why.append(f"The driver has {prior} upheld route dispute(s) in 90 days and this one is upheld -> flag_account (RD-6).")
    return {**th_gate(answer("refund_partial", amount, cited, why, flag), "the rider's words before the detour" if judge else False, fraud_flag(raw), why), "_findings": findings}


# ----------------------------------------------------------------------------------------------- no-show

def contact_counts(raw: dict, before: str) -> tuple[int, int]:
    """(driver in-app messages, driver in-app calls) logged before `before`."""
    b = _ts(before)
    msgs = sum(1 for m in raw["chat"] if m["from"] == "driver" and m.get("kind", "message") == "message" and m.get("ts") and _ts(m["ts"]) <= b)
    calls = sum(1 for m in raw["chat"] if m["from"] == "driver" and m.get("kind") == "call" and m.get("ts") and _ts(m["ts"]) <= b)
    calls += sum(1 for c in raw.get("calls", []) if c.get("caller") == "driver" and c.get("ts") and _ts(c["ts"]) <= b)
    return msgs, calls


def last_driver_words(raw: dict) -> str:
    b = _ts(raw["trip"]["cancelled_at"])
    m = [x for x in raw["chat"] if x["from"] == "driver" and x.get("ts") and _ts(x["ts"]) <= b]
    return m[-1]["text"] if m else ""


def first_within(gps, P, radius=contract.PICKUP_RADIUS_M):
    return next((p["ts"] for p in gps if contract.hav_m((p["lat"], p["lon"]), P) <= radius), None)


def _no_show(raw: dict, cond: dict) -> dict:
    t, gps = raw["trip"], raw["gps"]
    P = (t["pickup"]["lat"], t["pickup"]["lon"])
    pp = raw.get("policy_params") or {}
    fee = pp.get("cancellation_fee") or raw["fare"].get("cancellation_fee") or CANCEL_FEE
    fraud = fraud_flag(raw)
    by = t.get("cancelled_by")
    if by not in ("rider", "driver"):
        gap = "who cancelled is not on record: NS-1 (driver declares a no-show) and NS-4 (rider cancels) cannot be told apart"
        return escalate(["NS-0"], [f"Evidence insufficient (TH-4): {gap} -> escalate."], gap)
    s_cancel = (_ts(t["cancelled_at"]) - _ts(t["accepted_at"])).total_seconds()
    if by == "rider":
        if t.get("scheduled_at"):
            deadline = _ts(t["scheduled_at"]) + timedelta(seconds=FREE_WAIT_S)
            arrived = first_within(gps, P)
            if (arrived is None or _ts(arrived) > deadline) and _ts(t["cancelled_at"]) > deadline:
                msgs, calls = contact_counts(raw, t["cancelled_at"])
                why = [f"Scheduled pickup {t['scheduled_at'][11:16]}; the driver was " + ("never within 200 m of the pickup" if arrived is None else f"first within 200 m at {arrived[11:19]}")
                       + f" by {deadline:%H:%M} (scheduled + 5 min), and the rider cancelled at {t['cancelled_at'][11:19]}, after it: free cancellation (NS-8) -> refund ${fee:.2f}."]
                good = msgs == 0 and calls == 0
                why.append(f"The driver made {msgs} in-app message(s) and {calls} call(s) before the cancellation" + (": no contact attempt -> $5.00 goodwill credit (NS-8)." if good else "; no goodwill credit."))
                res = answer("refund_full", fee, ["NS-0", "NS-8"], why, goodwill_credit=GOODWILL if good else None)
                return th_gate(res, False, fraud, why)
        if s_cancel > GRACE_S:
            why = [f"The rider cancelled {s_cancel:.0f} s after matching, more than 3 minutes (NS-4) -> the ${fee:.2f} fee stands."]
            if t.get("scheduled_at"):
                why.insert(0, "NS-8 does not apply: the rider cancelled before the scheduled time + 5 min had passed without the driver.")
            return th_gate(answer("no_action", None, ["NS-0", "NS-4"], why), False, fraud, why)
        why = [f"The rider cancelled {s_cancel:.0f} s after matching, within 3 minutes (NS-4): free -> refund ${fee:.2f}."]
        return th_gate(answer("refund_full", fee, ["NS-0", "NS-4"], why), False, fraud, why)
    # driver cancelled
    tap = t.get("driver_pressed_here_at")
    w0 = tap or t["accepted_at"]
    if not gps:
        gap = "no GPS trace between acceptance and cancellation"
        return escalate(["NS-0", "NS-1"], [f"Evidence insufficient (TH-4): {gap} -> escalate."], gap)
    gap_in_wait = bool(holes(gps, w0, t["cancelled_at"]))
    if not tap:
        if cond.get("by") == "driver_other":
            why = ["The driver cancelled for a reason of his own, not a rider no-show (no arrival on record): no fee is due (NS-0, NS-3) -> refund " f"${fee:.2f}."]
            return th_gate(answer("refund_full", fee, ["NS-0", "NS-3"], why), False, fraud, why)
        why = ["The driver cancelled as a no-show without an arrival confirmation: NS-1 (i) fails -> fee voided (NS-2), refund " f"${fee:.2f}."]
        return th_gate(answer("refund_full", fee, ["NS-0", "NS-1", "NS-2"], why), False, fraud, why)
    at = min(gps, key=lambda p: abs((_ts(p["ts"]) - _ts(tap)).total_seconds()))
    d_tap = contract.hav_m((at["lat"], at["lon"]), P)
    at_pickup = d_tap <= contract.PICKUP_RADIUS_M
    record_T = pp.get("no_show_threshold_min")
    T = int(record_T * 60) if record_T else FREE_WAIT_S
    cont = contract.continuous_after_tap_s(gps, P, _ts(tap))
    late_start = 0
    if not record_T and t.get("scheduled_at") and _ts(t["scheduled_at"]) > _ts(tap):
        late_start = round((_ts(t["scheduled_at"]) - _ts(tap)).total_seconds())
    wait = cont - late_start
    ii = wait >= T
    msgs, calls = contact_counts(raw, t["cancelled_at"])
    iii = msgs >= 1 and calls >= 1
    if gap_in_wait and iii and ii:
        # the fee would stand if the car stayed through the hole; whether it did is not on record (NS-1 (iv))
        gap = "the GPS trace has a hole during the wait: whether the driver stayed at the pickup throughout is not on record (NS-1 (iv))"
        return escalate(["NS-0", "NS-1"], [f"Arrival confirmed, {msgs} message(s) and {calls} call(s) before cancelling, {wait} s from the arrival confirmation "
                                           f"to the cancellation; but {gap}. Missing records favour neither party (TH-4) -> escalate."], gap)
    if not ii:
        wait_pts = [p for p in gps if _ts(tap) <= _ts(p["ts"]) <= _ts(t["cancelled_at"])]
        _, tail = uncovered(wait_pts, tap, t["cancelled_at"]) if wait_pts else (0, 0)
        left = any(contract.hav_m((p["lat"], p["lon"]), P) > contract.PICKUP_RADIUS_M for p in wait_pts)
        if tail and not left and wait + tail >= T:
            gap = f"the GPS stops {tail:.0f} s before the cancellation and the uncovered time would decide the wait (NS-1 (iv))"
            return escalate(["NS-0", "NS-1"], [f"Evidence insufficient (TH-4): {gap} -> escalate."], gap)
    src = f"the record's own {record_T:g}-min no-show threshold, counted from the arrival confirmation" if record_T else \
          ("the 5-minute free wait, counted from the scheduled time (later than the arrival confirmation)" if late_start else "the 5-minute free wait, counted from the arrival confirmation")
    why = [f"(i) Arrival confirmed {d_tap:.0f} m from the pickup: " + ("within 200 m." if at_pickup else "more than 200 m away, fails."),
           f"(ii) {wait} s continuously at the pickup against {T} s ({src}): " + ("reached." if ii else "not reached, fails."),
           f"(iii) Before cancelling the driver sent {msgs} in-app message(s) and made {calls} call(s): " + ("both present." if iii else "needs at least one of each, fails.")]
    reading = cond.get("reason_reading") or "no_show"      # why the driver cancelled, read from his words (the court's slot)
    if at_pickup and ii and iii and reading == "own_reason":
        why.append(f"Every NS-1 element holds, but the driver's own message before cancelling gives his own reason (\"{last_driver_words(raw)}\")"
                   + (f"; the app reason '{t.get('cancellation_reason')}' is his claim" if t.get("cancellation_reason") else "; no reason was picked in the app")
                   + f": not a no-show cancellation (NS-0, NS-3) -> refund ${fee:.2f}.")
        return th_gate(answer("refund_full", fee, ["NS-0", "NS-3"], why), "the driver's own words for why he cancelled", fraud, why)
    if at_pickup and ii and iii and cond.get("reason_reading") == "no_show" and not t.get("cancellation_reason"):
        why.append(f"No reason was picked in the app; the driver's own message (\"{last_driver_words(raw)}\") says the rider did not come: a no-show cancellation (NS-0).")
    if at_pickup and ii and iii:
        prior = (raw["profiles"].get("rider_account") or {}).get("no_shows_30d")
        flag = prior is not None and prior + 1 >= 3
        why.append(f"All NS-1 conditions hold -> the ${fee:.2f} fee stands.")
        cited = ["NS-0", "NS-1"]
        if flag:
            cited.append("NS-9")
            why.append(f"The rider had {prior} no-show cancellations in the last 30 days; this is the third -> flag_account (NS-9).")
        elif prior:
            why.append(f"The rider had {prior} earlier no-show(s) in 30 days; this makes {prior + 1}, under 3 -> no flag (NS-9).")
        return th_gate(answer("no_action", None, cited, why, flag), "the driver's own words for why he cancelled", fraud, why)   # NS-0, read from his words
    flag = not at_pickup
    why.append(f"An NS-1 condition fails -> fee voided, refund ${fee:.2f} (NS-2)" + (" + flag_account: arrival confirmed while not at the pickup." if flag else "."))
    prior = (raw["profiles"].get("rider_account") or {}).get("no_shows_30d")
    if prior:
        why.append(f"The rider's {prior} earlier no-show(s) do not count here: this cancellation is not upheld as a no-show (NS-9).")
    return th_gate(answer("refund_full", fee, ["NS-0", "NS-1", "NS-2"], why, flag), False, fraud, why)


# ----------------------------------------------------------------------------------------------- surge

def _surge(raw: dict, cond: dict) -> dict:
    t, fare = raw["trip"], raw["fare"]
    s, fd = raw.get("surge") or {}, raw.get("fare_detail") or {}
    fraud = fraud_flag(raw)
    m0 = s.get("quote_time_surge", (fd.get("upfront_quote") or {}).get("surge_multiplier"))
    m1 = s.get("trip_start_surge", fare.get("surge_multiplier"))
    if m0 is None or m1 is None:
        gap = "the record does not give both the quote-time and the trip-start surge multiplier"
        return escalate(["SURGE-2"], [f"Evidence insufficient (TH-4): {gap} -> escalate."], gap)
    if m1 <= m0:
        why = [f"Surge {m0:.1f}x at quote, {m1:.1f}x at trip start: " + ("unchanged, the quoted multiplier applies" if m1 == m0 else "it fell, and the fare was charged at the lower trip-start multiplier")
               + f" (SURGE-2); the fare of ${fare['total']:.2f} is what the rule gives -> no refund."]
        return th_gate(answer("no_action", None, ["SURGE-2"], why), False, fraud, why)
    s1 = fd.get("surgeable_subtotal") or surgeable_subtotal(fare)
    notified = s.get("rider_notified")
    if notified is None:
        gap = "the surge log does not say whether the rider was notified of the higher multiplier"
        return escalate(["SURGE-1"], [f"Surge rose {m0:.1f}x -> {m1:.1f}x, but {gap}; missing records favour neither party (TH-4) -> escalate."], gap)
    label = contract.NOTICE_CONTENT.get(cond.get("notice"))       # the reading of the notice text (the court's slot)
    content = dict(zip(("multiplier", "revised_fare", "cancel_option"), label)) if (label and s.get("notification_text")) else {}
    in_app = (s.get("notification_method") or "").lower().replace("-", "_").startswith("in_app")
    when = s.get("notification_timestamp")
    on_time = bool(when) and _ts(when) <= _ts(t["pickup_at"])
    complete = all(content.get(k) for k in ("multiplier", "revised_fare", "cancel_option"))
    reading = "the notice text" if (notified and in_app and on_time and s.get("notification_text")) else False
    proper = bool(notified) and in_app and on_time and complete
    if not notified:
        what = "the rider was not notified"
    elif not in_app:
        what = f"the notice went by {s.get('notification_method')}, not in-app"
    elif not on_time:
        what = f"the notice came at {when[11:19]}, after pickup at {t['pickup_at'][11:19]}"
    elif not complete:
        what = (f"the notice (\"{s.get('notification_text')}\") did not state " +
                " and ".join(n for k, n in (("multiplier", "the new multiplier"), ("revised_fare", "the revised fare"),
                                            ("cancel_option", "a free-cancel option")) if not content.get(k)))
    else:
        what = "the rider was notified in-app before pickup with the new multiplier, the revised fare and the free-cancel option"
    if proper:
        why = [f"Surge rose {m0:.1f}x -> {m1:.1f}x and {what} (\"{s.get('notification_text')}\", SURGE-1); the rider rode -> the higher fare applies, no refund (SURGE-2)."]
        return th_gate(answer("no_action", None, ["SURGE-1", "SURGE-2"], why), reading, fraud, why)
    gap_total = round(fare["total"] - (fare.get("quoted_total") or 0), 2)
    surge_part = round((m1 - m0) * s1 + 1e-9, 2)
    amount = min(surge_part, max(gap_total, 0.0))       # never more than the fare's excess over the quote (§3.3 differential)
    why = [f"Surge rose {m0:.1f}x -> {m1:.1f}x and {what}: not notified under SURGE-1 -> refund the surge differential (SURGE-2).",
           f"Differential = ({m1:.1f} − {m0:.1f}) × surgeable subtotal ${s1:.2f} = ${surge_part:.2f}; the booking fee is not surged (SURGE-3)."
           + (f" The fare is only ${gap_total:.2f} above the quote (the trip ran shorter than the estimate), so the refund is capped at ${amount:.2f}." if amount < surge_part else "")]
    cited = ["SURGE-1", "SURGE-2", "SURGE-3"]
    rest = round(gap_total - amount, 2)
    ask = next((m for m in raw["chat"] if m["from"] == "rider" and re.search(r"stop at ", m["text"])), None)
    if ask:
        ok = next((m for m in raw["chat"] if m["from"] == "driver" and _ts(m["ts"]) > _ts(ask["ts"])), None)
        place = re.search(r"stop at (.+?)\?", ask["text"])
        why.append(f"The fare is ${gap_total:.2f} above the quote. ${rest:.2f} of that is not surge: the rider asked at {ask['ts'][11:19]} "
                   f"\"{ask['text']}\"" + (f", the driver answered \"{ok['text']}\" at {ok['ts'][11:19]}" if ok else "")
                   + f", and the car stopped at {place.group(1) if place else 'the place named'}. That longer trip is the rider's own request (RD-3), so it is not refunded.")
        cited.append("RD-3")
    elif fare.get("quoted_total") is not None and rest > 0.015:
        why.append(f"The fare is ${gap_total:.2f} above the quote; ${rest:.2f} of that is not surge (the trip's own time and distance against the "
                   f"estimate) and is not refunded under SURGE-3.")
    elif fare.get("quoted_total") is not None and rest < -0.015:
        why.append(f"The fare is ${gap_total:.2f} above the quote, less than the surge part: the trip itself cost ${-rest:.2f} less than the estimate at "
                   f"the quoted multiplier, so the refund is the surge the rider was charged on this trip (SURGE-3).")
    return th_gate(answer("refund_partial", amount, cited, why), reading, fraud, why)
