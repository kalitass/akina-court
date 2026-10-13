"""Policy execution engine (code, no LLM): evaluates the numbered clauses as predicates over fact values.

Each predicate is three-state:
    pass     the facts satisfy the clause element (evidence ids listed)
    fail     the facts contradict it
    judge    the element is a reading of what people said or meant (did the rider agree, and to what; is a message
             a threat) — the Judge decides it and must say so in Ruling.segment_findings / safety_concern

Three layers, kept apart on purpose:
    evidence   (code)   who said what and when; GPS, fare and time arithmetic; whether the record is complete
    judgement  (court)  what the words meant: consent and its scope, safety concern — may be "undetermined"
    check      (code)   the judgement is well-formed: it rests on facts that exist, were written by the right party,
                        and came before the segment; the amount follows the formula; what may execute automatically

From the predicates the engine derives the ALLOWED outcomes and the exact amount formula. "escalate" is always
allowed: a judge who cannot decide, or who reads a safety concern, sends the case to a person and code never
overrides that. Missing evidence (no GPS, a hole in the trace, untimed messages) is itself a finding — "cannot be
measured" — and never a silent ruling for either side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from core.facts.tools import _project, road_match
from core.schemas import GROUND_CONSEQUENCE, Case, FactTable, Ruling

Status = Literal["pass", "fail", "judge", "n/a"]
NEAR_ROUTE_M = 300          # data-layer parameter (gap G3)
PICKUP_RADIUS_M = 200       # data-layer parameter (gap G2)
GRACE_S = 180               # NS-4: a rider may cancel free within 3 minutes of matching
FREE_WAIT_S = 300           # NS-1 (ii): the 5-minute free wait ("after 5 minutes" — reaching it counts); a case record may state its own threshold
CANCEL_FEE = 5.00           # NS-1 / NS-4: official cancellation fee; a case record may carry its own
GOODWILL = 5.00             # NS-8: goodwill credit when the driver neither arrived nor tried to make contact
TOLERANCE_KM = 1.0          # RD-1: a deviation of 1 km or less is within tolerance
TH_MANUAL = 50.0            # TH-1: above this the system only prepares the case file
TH_CONFIDENT = 10.0         # TH-1: from this amount the code-computed confidence must reach 80%


def grace_s(case: "Case") -> int:
    """NS-4 rider-cancel grace in seconds: Ryde's 3 minutes. A record's free-wait window is a different parameter
    (when waiting fees start) and does not change it."""
    return GRACE_S


def no_show_threshold(case: "Case") -> tuple[int, bool, str]:
    """NS-1 (ii) wait threshold as (seconds, inclusive, source).

    The case record's own no-show threshold when it states one (the organisers' sample: 8 min, "threshold reached");
    else the official 5-minute free wait. Both are inclusive: the driver may cancel once the time has passed."""
    pp = getattr(case, "policy_params", None)
    m = getattr(pp, "no_show_threshold_min", None) if pp else None
    if m:
        return int(m * 60), True, f"case record: no-show threshold {m:g} min, reached = at least {m:g} min"
    return FREE_WAIT_S, True, f"NS-1 free wait: at least {FREE_WAIT_S // 60} min"


def cancel_fee(case: "Case") -> float:
    pp = getattr(case, "policy_params", None)
    f = (getattr(pp, "cancellation_fee", None) if pp else None) or getattr(case.fare, "cancellation_fee", 0) or 0
    return float(f) if f > 0 else CANCEL_FEE


@dataclass
class Predicate:
    clause: str                 # "RD-4"
    element: str                # "(a) incident on the replaced stretch"
    subject: str                # "F5" (segment) | "case"
    status: Status
    evidence: list[str]         # fact ids
    detail: str                 # one line with the numbers


@dataclass
class Certificate:
    dispute_type: str
    predicates: list[Predicate] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)        # allowed Ruling.ruling values
    amount_formula: Optional[str] = None
    rate_per_km: Optional[float] = None
    segments: dict = field(default_factory=dict)            # seg fact id -> {"exempt": True|False|None, "extra_km", "why"}
    flag_required: Optional[bool] = None                    # RD-6 / NS-2 flag_account (None = depends on judge findings)
    fee: float = CANCEL_FEE                                 # cancellation fee this case was evaluated with
    grace: int = GRACE_S                                    # NS-4 rider-cancel grace (s)
    wait_threshold: int = GRACE_S                           # NS-1 (iii) wait threshold (s) this case was evaluated with
    wait_inclusive: bool = False                            # True = "reached" counts (record-stated threshold); False = "more than" (NS-1 default)
    wait_source: str = ""                                   # where the threshold came from (shown in the trace)
    flag_conditional: bool = False                          # route: flag iff the judge finds ≥1 non-exempt segment
    mechanical: bool = True                                 # True = outcome fully determined by code
    insufficient: Optional[str] = None                      # evidence the question needs but the record lacks → only escalate
    chat_index: dict = field(default_factory=dict)          # chat fact id -> {"from", "ts", "statement"} for the basis check
    deviation_km: Optional[float] = None                    # RD-1: billed distance − optimal route km
    amount: Optional[float] = None                          # the amount code fixes outright (no-show fee, surge part); route: expected_amount()
    goodwill_required: bool = False                         # NS-8: goodwill credit due
    fraud_flag: bool = False                                # TH-3: a party carries a fraud flag (threshold 95%)
    elements: dict = field(default_factory=dict)            # judge-read element id -> {"default": met|None, "outcome": {"met": ruling, "not_met": ruling}, "flag_if_met": bool}

    def what_would_change(self, findings: Optional[dict] = None) -> list[str]:
        """Deterministic 'what would change this ruling' sentences, derived from the failed / passed predicates.
        `findings` (segment fact id -> "exempt" / "counts" / "undetermined"), when given, phrases a judge-decided segment
        as what was found rather than as an open question."""
        out = []
        findings = findings or {}
        if self.dispute_type == "no_show":
            ns4 = next((p for p in self.predicates if p.clause == "NS-4"), None)
            if ns4 is not None and ns4.status == "pass":
                out.append(f"Had the rider cancelled within {self.grace // 60} minutes of matching, NS-4 would have waived the ${self.fee:.2f} fee.")
            elif ns4 is not None:
                out.append(f"Had the rider cancelled more than {self.grace // 60} minutes after matching, NS-4 would have upheld the ${self.fee:.2f} fee.")
            failed = [p for p in self.predicates if p.clause == "NS-1" and p.status == "fail" and p.element.startswith("(")]
            if len(failed) == 1:
                out.append(f"Had NS-1 {failed[0].element.split(' ')[0]} held ({failed[0].element}), the fee would stand and no refund would be due.")
            elif failed:
                out.append("Had NS-1 " + " and ".join(p.element.split(' ')[0] for p in failed) + (" both held (" if len(failed) == 2 else " all held (")
                           + "; ".join(p.element for p in failed) + "), the fee would stand and no refund would be due.")
            ns8 = next((p for p in self.predicates if p.clause == "NS-8" and p.element.startswith("driver not at")), None)
            if ns8 is not None and ns8.status == "pass":
                out.append(f"Had the driver reached the pickup by the scheduled time + 5 minutes, the rider's cancellation would fall under NS-4 instead"
                           + (", and had he messaged or called, no goodwill credit would be due." if self.goodwill_required else "."))
            elif ns8 is not None:
                out.append("Had the driver not reached the pickup by the scheduled time + 5 minutes, NS-8 would let the rider cancel free.")
            if "no_action" in self.allowed and any(p.clause == "NS-1" and p.status == "pass" for p in self.predicates):
                out.append(f"Had the driver confirmed arrival more than 200 m away, left before {self.wait_threshold / 60:g} minutes, or not both messaged and called the rider, NS-2 would refund the fee in full.")
        elif self.dispute_type == "fare_dispute":
            s1 = next((p for p in self.predicates if p.clause == "SURGE-1"), None)
            if s1 is not None and s1.status == "fail":
                out.append("Had the rider been notified in-app before pickup with the new multiplier, the revised fare and a free-cancel option, SURGE-2 would leave the higher fare in place.")
            elif s1 is not None:
                out.append(f"Had the notice been missing, late or incomplete, SURGE-2 would refund the surge part.")
        elif self.dispute_type == "route_deviation":
            money = (lambda km: f"${km * self.rate_per_km:.2f}") if self.rate_per_km else (lambda km: f"{km:.2f} km of fare")
            for fid, sg in self.segments.items():
                if sg["exempt"] is False:
                    base = expected_amount(self, {}) or 0.0
                    if self.rate_per_km and self.deviation_km is not None and all(s2["exempt"] is not None for s2 in self.segments.values()):
                        ex_km = sum(s2["extra_km"] for f, s2 in self.segments.items() if s2["exempt"] or f == fid)
                        left = max(0.0, self.deviation_km - ex_km)
                        alt = round(left * self.rate_per_km + 1e-9, 2) if left > TOLERANCE_KM else 0.0
                        delta = f" (refund ${base:.2f} → ${alt:.2f})"
                    else:
                        delta = ""
                    out.append(f"{fid}: a rider message agreeing to this route before it started would have exempted it{delta}.")
                elif findings.get(fid) == "exempt":
                    out.append(f"{fid}: the judge found the rider's own message covers this segment, so it is exempt; without that message it would count (+{money(sg['extra_km'])}).")
                elif findings.get(fid) == "counts":
                    out.append(f"{fid}: the judge found no rider agreement covering this segment, so it counts; a rider message agreeing to it beforehand would have exempted it.")
                elif findings.get(fid) == "undetermined":
                    out.append(f"{fid}: the record does not settle whether the rider's agreement covers this segment; a person decides.")
                else:
                    out.append(f"{fid}: if the judge finds the rider agreed to this route or named this stop beforehand, it is exempt; if not, it counts.")
            if self.deviation_km is not None and self.deviation_km <= TOLERANCE_KM:
                out.append(f"Had the trip run more than {TOLERANCE_KM:g} km over the optimal route, RD-2 would weigh each off-route segment.")
            if self.flag_required is False and any(p.clause == "RD-6" for p in self.predicates):
                out.append("Had the driver carried a prior upheld route dispute in the last 90 days, RD-6 would add an account flag.")
        return out

    def lines(self) -> list[str]:
        out = []
        for p in self.predicates:
            mark = {"pass": "✓", "fail": "✗", "judge": "?", "n/a": "–"}[p.status]
            out.append(f"{mark} {p.clause} {p.element} [{p.subject}] {p.detail} ({', '.join(p.evidence) or 'no evidence'})")
        if self.dispute_type == "no_show" and (self.fee != CANCEL_FEE or self.wait_source.startswith("case record")):
            out.append(f"parameters from the case record: cancellation fee ${self.fee:.2f}; NS-1 (ii) wait threshold {self.wait_threshold / 60:g} min "
                       f"({'at least' if self.wait_inclusive else 'more than'}; {self.wait_source}) — read these wherever NS-1 / NS-2 say ${CANCEL_FEE:.2f} / {FREE_WAIT_S // 60} min.")
        if self.goodwill_required:
            out.append(f"goodwill_credit required: {GOODWILL:.2f} (NS-8)")
        if self.insufficient:
            out.append(f"evidence insufficient: {self.insufficient}")
        open_segs = [f for f, sg in self.segments.items() if sg["exempt"] is None]
        if self.dispute_type == "route_deviation" and open_segs and len(open_segs) <= 3 and self.rate_per_km is not None:
            # the consequence of every reading, computed here so the judge only reads the words (RD-1 tolerance after
            # exemptions, RD-2 amount)
            from itertools import product
            settled_ex = sum(sg["extra_km"] for sg in self.segments.values() if sg["exempt"] is True)
            for combo in product((True, False), repeat=len(open_segs)):
                f = dict(zip(open_segs, combo))
                amt = expected_amount(self, f)
                left = max(0.0, (self.deviation_km or 0) - settled_ex - sum(self.segments[x]["extra_km"] for x, ex in f.items() if ex))
                what = ", ".join(f"{x} {'exempt' if ex else 'counts'}" for x, ex in f.items())
                out.append(f"if {what} → {left:.2f} km left " + (f"> {TOLERANCE_KM:g} km → refund_partial ${amt:.2f}" if amt else f"≤ {TOLERANCE_KM:g} km → no_action (no refund)"))
        out.append(f"allowed outcomes: {', '.join(self.allowed) or '—'}" + (f"; amount = {self.amount_formula}" if self.amount_formula else ""))
        if self.flag_conditional:
            out.append("flag_account required: only if a refund is due (RD-6 prior upheld dispute on file)")
        elif self.flag_required is not None:
            out.append(f"flag_account required: {self.flag_required}")
        return out


def _vals(table: FactTable) -> dict[str, dict]:
    return {f.id: (f.value or {}) for f in table.facts}


def table_text(table: FactTable, fid: str) -> str:
    return next((f.text for f in table.facts if f.id == fid), "")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


# --------------------------------------------------------------------------- route deviation

def _segment_replaced_stretch(case: Case, seg: dict) -> tuple[float, float]:
    """Along-track km range of the optimal route that the detour replaced (entry/exit projections)."""
    if "entry_km" in seg and "exit_km" in seg:                                  # measured by the fact tool itself
        return (seg["entry_km"], seg["exit_km"])
    poly = case.route.polyline
    before = [p for p in case.gps if p.ts.isoformat() < seg["start"]]
    after = [p for p in case.gps if p.ts.isoformat() > seg["end"]]
    entry = before[-1] if before else next(p for p in case.gps if p.ts.isoformat() >= seg["start"])
    exit_ = after[0] if after else case.gps[-1]
    a = _project(entry.lat, entry.lon, poly)[1]
    b = _project(exit_.lat, exit_.lon, poly)[1]
    return (min(a, b), max(a, b))


MIN_BYPASS_KM = 0.3         # data-layer parameter (gap G3): a detour "replaces" a stretch only if entry and exit are this far apart along
                            # the route; an out-and-back spur (entry ≈ exit) bypasses nothing, so no incident can sit "on the replaced stretch"


def _incident_on_stretch(case: Case, inc: dict, lo_km: float, hi_km: float) -> bool:
    if hi_km - lo_km < MIN_BYPASS_KM:
        return False
    d, along = _project(inc["lat"], inc["lon"], case.route.polyline)
    return d <= NEAR_ROUTE_M and (lo_km - 0.3) <= along <= (hi_km + 0.3)


def _chat_index(vals: dict[str, dict]) -> dict[str, dict]:
    # a recorded call carries the rider's own words (RD-5: a verbal notice counts with the call recording), so it can be
    # the basis of a consent finding like a rider message; an unrecorded call log entry cannot
    out = {fid: {"from": v.get("from"), "ts": v.get("ts"), "statement": bool(v.get("statement"))}
           for fid, v in vals.items() if ("idx" in v and "from" in v) or v.get("statement")}
    out.update({fid: {"from": "recorded_call", "ts": v.get("ts"), "statement": False}
                for fid, v in vals.items() if v.get("kind") == "call_log" and v.get("transcript")})
    return out


def _traffic_reason(case: Case, vals: dict[str, dict], seg: dict, lo: float, hi: float) -> list[str]:
    """RD-4: facts showing a closure, incident or congestion on the replaced stretch of the optimal route when the segment
    began — an incident by coordinates (within NEAR_ROUTE_M of that stretch, reported before), an incident by road name
    on the optimal route (reported before, not yet cleared), or a speed band 1–2 on an optimal-route road covering the start."""
    start = _ts(seg["start"])
    out = [fid for fid, v in vals.items() if "reported_at" in v and "lat" in v and _ts(v["reported_at"]) < start and _incident_on_stretch(case, v, lo, hi)]
    for fid, v in vals.items():
        if "on_route" in v and v["on_route"] and v.get("reported_at") and _ts(v["reported_at"]) <= start \
                and (not v.get("cleared_at") or _ts(v["cleared_at"]) >= start) and (v.get("incident_type") or "") != "traffic_flow":
            out.append(fid)
    labels = [r.get("name", "") for r in case.route.roads if r.get("from_m") is None or (lo - 0.3) * 1000 <= r["to_m"] and r["from_m"] <= (hi + 0.3) * 1000]
    for fid, v in vals.items():
        seg_end = _ts(seg["end"]) if seg.get("end") else start
        if v.get("severe") and "speed_band" in v and _ts(v["window_start"]) <= seg_end and start <= _ts(v["window_end"]) and road_match(v["road_name"], labels):
            out.append(fid)
    return out


def evaluate_route(case: Case, table: FactTable) -> Certificate:
    """RD-1 … RD-7. Money turns on one question per off-route segment — did the rider agree to it, or ask for it,
    before it started (RD-3 / RD-5)? A traffic reason (RD-4) does not change the amount: it decides whether a driver
    violation is recorded. The refund is the excess distance fare of the whole trip less the km of exempt segments."""
    vals = _vals(table)
    cert = Certificate(dispute_type="route_deviation")
    cert.chat_index = _chat_index(vals)
    cert.fraud_flag = any((v.get("fraud_flags") or 0) >= 1 for v in vals.values() if "party" in v)
    segs = {fid: v for fid, v in vals.items() if "extra_km" in v and "start" in v}
    excess = next(((fid, v) for fid, v in vals.items() if "billed_km" in v), (None, {}))
    messages = [(fid, v) for fid, v in vals.items() if "idx" in v and "from" in v and v.get("kind", "message") == "message"]
    messages += [(fid, {**v, "from": "recorded_call"}) for fid, v in vals.items() if v.get("kind") == "call_log" and v.get("transcript")]
    record = next((v for v in vals.values() if "complete" in v and "count" in v), {"complete": True, "count": 0})
    statement = next((fid for fid, v in vals.items() if v.get("statement")), None)
    # ---- evidence sufficiency: the route question needs a trace that covers the trip
    missing = [fid for fid, v in vals.items() if v.get("gps_missing")]
    gaps = [fid for fid, v in vals.items() if "gps_gap_s" in v]
    cover = [fid for fid, v in vals.items() if v.get("uncovered_start_s") or v.get("uncovered_end_s")]
    rider_words = [fid for fid, v in messages if v.get("from") in ("rider", "recorded_call")] + \
                  [fid for fid, v in vals.items() if "idx" in v and v.get("from") == "rider"]
    if (gaps or cover) and not missing and not rider_words and excess[1].get("rate_km") is not None:
        # TH-4: a stretch the trace does not cover matters only if it could hold an exempt segment. Exemption needs the
        # rider's own words (RD-3 / RD-5); with none on record nothing can be exempt, so the billed deviation decides.
        cert.predicates.append(Predicate("TH-4", "GPS trace covers the trip", "case", "fail", gaps + cover,
                                         "the trace has an uncovered stretch, but the rider said nothing that could exempt any part of the route: the billed deviation decides"))
        segs = segs or {}
        gaps, cover = [], []
    if missing or gaps or cover:
        what = ("no GPS trace for the trip" if missing else "; ".join(
            ([f"GPS trace has {len(gaps)} hole(s); an off-route stretch inside a hole cannot be measured"] if gaps else [])
            + (["GPS trace does not cover the whole trip (starts late or ends early); the uncovered stretch cannot be measured"] if cover else [])))
        cert.predicates.append(Predicate("TH-4", "GPS trace covers the trip", "case", "fail", missing + gaps + cover, what))
        cert.insufficient = what
        cert.allowed = ["escalate"]
        cert.mechanical = False
        return cert
    rate = excess[1].get("rate_km")
    dev = excess[1].get("excess_km")
    if dev is None:                                  # no billed distance: the GPS segments are the only measure
        dev = round(sum(v["extra_km"] for v in segs.values()), 2) if segs else 0.0
    cert.deviation_km, cert.rate_per_km = dev, rate
    if dev <= TOLERANCE_KM or not segs:
        why = (f"deviation {dev:.2f} km ≤ {TOLERANCE_KM:g} km: within tolerance" if dev <= TOLERANCE_KM
               else "no off-route segment measured (the trace follows the optimal route)")
        cert.predicates.append(Predicate("RD-1", "deviation over 1 km", "case", "fail", [x for x in [excess[0]] if x] + list(segs), why))
        cert.allowed = ["no_action", "escalate"]
        cert.flag_required = False
        return cert
    cert.predicates.append(Predicate("RD-1", "deviation over 1 km", "case", "pass", [x for x in [excess[0]] if x] + list(segs),
                                     f"deviation {dev:.2f} km (billed − optimal); {len(segs)} off-route segment(s)"))
    if rate is None:
        cert.insufficient = "the fare record gives no distance fare: the RD-2 amount cannot be computed"
        cert.predicates.append(Predicate("RD-2", "per-km distance fare on record", "case", "fail", [], cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    comm_ids = [fid for fid, _ in messages] + ([statement] if statement else [])
    drv = next((v for v in vals.values() if v.get("party") == "driver"), {})
    prior = drv.get("route_disputes_upheld_90d", 0) >= 1
    for fid, seg in segs.items():
        start = _ts(seg["start"])
        lo, hi = _segment_replaced_stretch(case, seg)
        rd4 = _traffic_reason(case, vals, seg, lo, hi)
        cert.predicates.append(Predicate("RD-4", "traffic reason on the replaced stretch when the segment began", fid, "pass" if rd4 else "fail", rd4,
                                         ("traffic reason on record — no driver violation; the amount still turns on RD-5" if rd4
                                          else "no incident or congestion on record for the replaced stretch — a driver violation if not exempt")))
        base = {"extra_km": seg["extra_km"], "start": seg["start"], "end": seg.get("end"), "roads": seg.get("roads", []), "traffic": bool(rd4)}
        before = [cid for cid, c in messages if c.get("ts") and _ts(c["ts"]) <= start]
        untimed = [cid for cid, c in messages if not c.get("ts")]
        rider_before = [cid for cid, c in messages if c.get("from") in ("rider", "recorded_call") and c.get("ts") and _ts(c["ts"]) <= start]
        if not rider_before and not untimed:
            later = [cid for cid, c in messages if c.get("from") == "rider"]
            why = (f"the rider's message(s) {', '.join(later)} came after the segment started at {start:%H:%M:%S}" if later
                   else f"no rider message on record before {start:%H:%M:%S}") + "; a driver's statement is a claim, not consent"
            cert.predicates.append(Predicate("RD-5", "rider informed and agreed before or at the deviation", fid, "fail", comm_ids, why))
            cert.predicates.append(Predicate("RD-3", "rider asked for this stop or route", fid, "fail", comm_ids, f"no rider message before {start:%H:%M:%S}"))
            cert.segments[fid] = {**base, "exempt": False, "why": "no rider message before the segment started"}
            continue
        stop_ids = [sid for sid, v in vals.items() if "duration_s" in v and "m_from_pickup" in v and seg["start"] <= v.get("start", "") <= (seg.get("end") or "~")]
        texts = "; ".join(f"{cid}: {table_text(table, cid)}" for cid in before + untimed + ([statement] if statement else []))
        roads = seg.get("roads") or []
        timing = ("" if record.get("complete", True) else f" {len(untimed)} message(s) carry no time: if the finding turns on them, it is undetermined.")
        cert.predicates.append(Predicate("RD-5", "rider informed and agreed before the deviation; scope of that agreement", fid, "judge", before + untimed + ([statement] if statement else []),
                                         f"RULE: exempt only if a RIDER message sent by {start:%H:%M:%S} agrees AND the agreement covers this segment. "
                                         f"(1) GENERAL route choice ('take whichever way is faster') covers a route chosen to get there, not an errand of the driver's own (a stop away from the route, a loop that reaches nothing: counts). "
                                         f"(2) A SPECIFIC named road or area ('go via X'): put X in named_road; code checks it against the roads this segment drove "
                                         + (f"({' → '.join(roads)}): X among them → named_road_tied (exempt), otherwise named_road_elsewhere (counts). " if roads
                                            else "— the record names no roads for this segment, so a named-road agreement is named_road_untied (undetermined). ")
                                         + f"(3) Scope unclear: undetermined. A driver's claim of agreement that appears only in his statement is not consent; a complete chat record with no rider agreement before the segment: counts.{timing} "
                                         f"This finding changes the amount. Evidence — {texts}"))
        cert.predicates.append(Predicate("RD-3", "rider asked for this stop or route; whether the rider named this place", fid, "judge", before + stop_ids,
                                         f"RULE (RD-3): exempt if a RIDER message before the segment named a specific place or route and the car went there. "
                                         f"A stop the rider asked for without naming a place ('a 7-Eleven on the way') does not excuse the driver's choice of a far one → counts."
                                         + (f" Stops in this segment: {', '.join(stop_ids)}." if stop_ids else " No stop measured in this segment.")))
        cert.segments[fid] = {**base, "exempt": None, "stops": stop_ids, "why": "judge reads RD-5 / RD-3 from the chat", "changes_outcome": True}
        if stop_ids:
            # RD-3: whether the rider named this place is a reading; what follows from it is not — a rider-named stop makes the
            # WHOLE segment not a deviation, so the judge answers the question and code fixes the consequence
            eid = f"RD-3:{fid}"
            cert.elements[eid] = {"default": None, "outcome": None, "segment": fid}
            cert.predicates.append(Predicate("RD-3", f"[{eid}] a RIDER message before {start:%H:%M:%S} NAMED this specific place, and the car stopped there ({', '.join(stop_ids)})", fid, "judge",
                                             before + stop_ids, "met → the whole segment is exempt (the way there included — do not split it); not_met (no rider message "
                                             "named a place, e.g. 'a 7-Eleven on the way', or the car stopped somewhere else) → RD-3 does not apply and the segment turns on RD-5"))
        cert.mechanical = False
    definite_bad = [f for f, sg in cert.segments.items() if sg["exempt"] is False]
    undecided = [f for f, sg in cert.segments.items() if sg["exempt"] is None]
    if not undecided:
        amt = expected_amount(cert, {})
        cert.allowed = ["refund_partial", "escalate"] if amt else ["no_action", "escalate"]
    elif definite_bad:
        cert.allowed = ["refund_partial", "escalate"] if expected_amount(cert, {f: True for f in undecided}) else ["refund_partial", "no_action", "escalate"]
    else:
        cert.allowed = ["refund_partial", "no_action", "escalate"]
    cert.amount_formula = (f"({dev:.2f} km deviation − km of exempt segments) × ${rate:.4f}/km, rounded to cents; "
                           f"no refund when what is left is {TOLERANCE_KM:g} km or less")
    cert.predicates.append(Predicate("RD-6", "prior upheld route dispute in 90 d (repeated breach → flag_account)", "case",
                                     "pass" if prior else "fail", [f for f, v in vals.items() if v.get("party") == "driver"],
                                     f"route_disputes_upheld_90d = {drv.get('route_disputes_upheld_90d', 0)}"))
    cert.flag_required = bool(prior) if not undecided else (None if prior else False)
    cert.flag_conditional = bool(undecided and prior)
    return cert


def expected_amount(cert: Certificate, findings: dict[str, Optional[bool]]) -> Optional[float]:
    """RD-2 amount once the judge's findings fill the undecided segments: (deviation − exempt km) × rate. None when a
    segment is missing or undetermined (no amount can execute)."""
    if cert.rate_per_km is None or cert.deviation_km is None:
        return None
    exempt_km = 0.0
    for fid, s in cert.segments.items():
        exempt = s["exempt"] if s["exempt"] is not None else findings.get(fid)
        if exempt is None:
            return None
        if exempt:
            exempt_km += s["extra_km"]
    km = max(0.0, cert.deviation_km - exempt_km)          # the tolerance applies to what is left once exempt segments are taken out:
    return round(km * cert.rate_per_km + 1e-9, 2) if km > TOLERANCE_KM else 0.0   # a residue of ≤ 1 km is GPS jitter, not a deviation


# --------------------------------------------------------------------------- no-show

def evaluate_no_show(case: Case, table: FactTable) -> Certificate:
    """NS-0 … NS-9. Driver cancels for a no-show: the $5.00 fee stands only if the driver (i) arrived within 200 m,
    (ii) waited the free 5 minutes from the later of arrival and the scheduled time, (iii) messaged AND called the
    rider, (iv) stayed throughout. Rider cancels: NS-8 when the driver had not arrived by scheduled + 5 min, else NS-4."""
    vals = _vals(table)
    T, incl, src = no_show_threshold(case)
    cert = Certificate(dispute_type="no_show", fee=cancel_fee(case), grace=grace_s(case), wait_threshold=T, wait_inclusive=incl, wait_source=src)
    cert.fraud_flag = any((v.get("fraud_flags") or 0) >= 1 for v in vals.values() if "party" in v)
    G, FEE, GM, TM = cert.grace, cert.fee, cert.grace / 60, T / 60
    cancel = next((v for v in vals.values() if "s_after_accept" in v), {})
    near = next(((f, v) for f, v in vals.items() if "nearest_m" in v), (None, {}))
    within = next(((f, v) for f, v in vals.items() if "first_within_200m_at" in v), (None, {}))
    here = next(((f, v) for f, v in vals.items() if "driver_pressed_here_at" in v), (None, {}))
    contact = next(((f, v) for f, v in vals.items() if "driver_calls" in v), (None, {}))
    sched = next(((f, v) for f, v in vals.items() if "s_scheduled_to_cancel" in v), (None, {}))
    rider = next((v for v in vals.values() if v.get("party") == "rider"), {})
    cancel_id = next((f for f, v in vals.items() if "s_after_accept" in v), None)
    by = cancel.get("cancelled_by")
    cert.chat_index = _chat_index(vals)
    cert.predicates.append(Predicate("NS-0", "who cancelled", "case", "pass" if by in ("rider", "driver") else "fail", [cancel_id] if cancel_id else [], f"cancelled_by = {by}"))
    if not cancel_id:
        cert.insufficient = "no cancellation on the timeline: who cancelled and when is not on record"
        cert.predicates.append(Predicate("TH-4", "cancellation on record", "case", "fail", [], cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    if by not in ("rider", "driver"):
        cert.insufficient = f"who cancelled is not on record (cancelled_by = {by}): NS-1 (driver declares a no-show) and NS-4 (rider cancels) cannot be told apart"
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    cert.flag_required = False
    if by == "rider":
        # NS-8: the driver was not at the pickup by scheduled + 5 min and the rider cancelled after that
        if sched[0]:
            deadline = _ts(sched[1]["scheduled_at"]).timestamp() + FREE_WAIT_S
            arrived_at = _ts(within[1]["first_within_200m_at"]).timestamp() if within[1].get("first_within_200m_at") else None
            cancelled_at = _ts(cancel["cancelled_at"]).timestamp()
            late = (arrived_at is None or arrived_at > deadline) and cancelled_at > deadline
            cert.predicates.append(Predicate("NS-8", "driver not at the pickup by scheduled time + 5 min, rider cancelled after it", "case", "pass" if late else "fail",
                                             [x for x in (sched[0], within[0], near[0], cancel_id) if x],
                                             ("driver never within 200 m before the cancellation" if arrived_at is None else
                                              f"first within 200 m {(arrived_at - deadline + FREE_WAIT_S) / 60:+.1f} min from the scheduled time")))
            if late:
                no_contact = contact[0] is not None and contact[1].get("driver_messages", 0) == 0 and contact[1].get("driver_calls", 0) == 0
                cert.goodwill_required = no_contact
                cert.predicates.append(Predicate("NS-8", "driver made no contact attempt → $5.00 goodwill credit", "case", "pass" if no_contact else "fail",
                                                 [contact[0]] if contact[0] else [], f"{contact[1].get('driver_messages', 0)} message(s), {contact[1].get('driver_calls', 0)} call(s)"))
                charged = float(cancel.get("cancellation_fee") or 0)
                cert.allowed = ["refund_full", "escalate"] if charged > 0 else ["no_action", "escalate"]
                cert.amount = charged if charged > 0 else None
                cert.amount_formula = f"the cancellation fee charged ${charged:.2f}" if charged > 0 else None
                return cert
        late = cancel.get("s_after_accept", 0) > G
        cert.predicates.append(Predicate("NS-4", f"rider cancelled more than {GM:g} min after matching", "case", "pass" if late else "fail",
                                         [cancel_id], f"{cancel.get('s_after_accept')} s after acceptance"))
        cert.allowed = ["no_action", "escalate"] if late else ["refund_full", "escalate"]
        cert.amount = None if late else FEE
        cert.amount_formula = None if late else f"cancellation fee ${FEE:.2f}"
        return cert
    # driver cancelled as rider no-show → NS-1; it needs the driver's trace over the whole wait
    missing = [f for f, v in vals.items() if v.get("gps_missing")]
    if missing:
        cert.insufficient = "no GPS trace between acceptance and cancellation: where the driver waited cannot be measured"
        cert.predicates.append(Predicate("TH-4", "GPS trace covers the wait", "case", "fail", missing, cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    here_at = here[1].get("driver_pressed_here_at")
    w0, w1 = (here_at or cancel.get("accepted_at") or ""), (cancel.get("cancelled_at") or "")
    holes = [f for f, v in vals.items() if "gps_gap_s" in v and v.get("gap_end", "") > w0 and v.get("gap_start", "") < w1]
    cover = [f for f, v in vals.items() if v.get("uncovered_start_s") or v.get("uncovered_end_s")]
    if holes or cover:
        parts = []
        if holes:
            parts.append(f"GPS has {len(holes)} hole(s) during the wait ({', '.join(str(vals[f]['gps_gap_s']) + ' s' for f in holes)}): the time between two samples is not a measured wait")
        if cover:
            parts.append("GPS trace does not cover the whole wait (starts after the arrival confirmation or ends before the cancellation)")
        gap_txt = "; ".join(parts)
        # TH-4: the missing stretch matters only if it could decide the case. Even granting the driver was at the pickup
        # for the whole uncovered time, the fee is still void when no arrival was confirmed, the contact duty (iii) was
        # not met, or the time from the start of the free wait to the cancellation is short of the threshold.
        msgs0, calls0 = contact[1].get("driver_messages", 0), contact[1].get("driver_calls", 0)
        here_at0 = here[1].get("driver_pressed_here_at")
        start0 = max(x for x in [here_at0, sched[1].get("scheduled_at") if not src.startswith("case record") else None] if x) if here_at0 else None
        best_wait = (_ts(cancel["cancelled_at"]) - _ts(start0)).total_seconds() if start0 else 0
        void_anyway = [w for w, bad in (("no arrival confirmation", not here_at0),
                                        (f"the driver did not both message and call ({msgs0} message(s), {calls0} call(s))", not (msgs0 >= 1 and calls0 >= 1)),
                                        (f"even counting the uncovered time, the wait is {best_wait:.0f} s, short of {T} s", here_at0 and not ((best_wait >= T) if incl else (best_wait > T))))
                       if bad]
        if void_anyway:
            cert.predicates.append(Predicate("NS-1", "(iv) GPS covers the wait", "case", "fail", holes + cover, gap_txt + " — but it cannot change the outcome"))
            cert.predicates.append(Predicate("NS-2", "fee void whatever the uncovered time shows", "case", "pass", [x for x in (here[0], contact[0], cancel_id) if x], "; ".join(void_anyway)))
            cert.allowed = ["refund_full", "escalate"]; cert.amount = FEE; cert.amount_formula = f"cancellation fee ${FEE:.2f}"
            cert.flag_required = False
            return cert
        cert.insufficient = gap_txt
        cert.predicates.append(Predicate("NS-1", "(iv) stayed at the pickup throughout: GPS covers the wait without a hole", "case", "fail", holes + cover, cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    i_ok = bool(here_at)
    d_tap = here[1].get("m_from_pickup_at_tap")
    at_pickup = d_tap is not None and d_tap <= PICKUP_RADIUS_M
    cont = here[1].get("within_200m_after_tap_s", 0) or 0
    late_start = 0
    if here_at and not src.startswith("case record") and sched[1].get("scheduled_at") and _ts(sched[1]["scheduled_at"]) > _ts(here_at):
        # the official free wait runs from the later of arrival and the scheduled time; a record-stated threshold is
        # measured the way the record measures it (DISP-002: from arrival, "threshold reached" at the cancellation)
        late_start = round((_ts(sched[1]["scheduled_at"]) - _ts(here_at)).total_seconds())
    wait = cont - late_start
    ii_ok = (wait >= T) if incl else (wait > T)
    tail = here[1].get("tail_uncovered_s", 0) or 0
    if here_at and not ii_ok and tail and not here[1].get("left_radius"):
        with_tail = wait + tail
        if (with_tail >= T) if incl else (with_tail > T):
            cert.insufficient = (f"GPS stops {tail} s before the cancellation: {wait} s of waiting are measured, the threshold is {T} s, "
                                 f"and the uncovered {tail} s would decide it")
            cert.predicates.append(Predicate("NS-1", "(iv) wait measured up to the cancellation", "case", "fail", [here[0]] if here[0] else [], cert.insufficient))
            cert.allowed = ["escalate"]; cert.mechanical = False
            return cert
    msgs, calls = contact[1].get("driver_messages", 0), contact[1].get("driver_calls", 0)
    iii_ok = msgs >= 1 and calls >= 1
    auto = here[1].get("arrival_confirmed_by") == "platform_auto"
    kind = "platform_auto arrival" if auto else "driver_tap"
    when = (here_at or "—")[11:19]
    cert.predicates.append(Predicate("NS-1", f"(i) arrived: arrival confirmed ({kind}) within {PICKUP_RADIUS_M} m of the pickup", "case", "pass" if (i_ok and at_pickup) else "fail",
                                     [x for x in (here[0], near[0]) if x],
                                     (f"{kind} at {when}, {d_tap if d_tap is not None else '—'} m from pickup (closest approach overall {near[1].get('nearest_m')} m)" if i_ok
                                      else "no arrival confirmation on record")))
    cert.predicates.append(Predicate("NS-1", f"(ii) waited {'at least' if incl else 'more than'} {TM:g} min from the later of arrival and the scheduled time ({src})", "case",
                                     "pass" if ii_ok else "fail", [x for x in (here[0], sched[0]) if x],
                                     f"{wait} s continuously at the pickup" + (f" counted from the scheduled time ({late_start} s after arrival)" if late_start else " counted from arrival")
                                     + f"; threshold {T} s ({'≥' if incl else '>'})"))
    cert.predicates.append(Predicate("NS-1", "(iii) before cancelling, the driver sent ≥ 1 in-app message AND made ≥ 1 in-app call", "case", "pass" if iii_ok else "fail",
                                     [contact[0]] if contact[0] else [], f"{msgs} message(s), {calls} call(s)"))
    if i_ok and at_pickup and ii_ok and iii_ok:
        prior = rider.get("no_shows_30d")
        repeat = prior is not None and prior + 1 >= 3
        cert.predicates.append(Predicate("NS-9", "rider's 3rd no-show within 30 days → flag_account", "case", "pass" if repeat else "fail",
                                         [f for f, v in vals.items() if v.get("party") == "rider"],
                                         f"{prior if prior is not None else 'no'} prior no-show(s) in 30 days on record"))
        app_reason = cancel.get("app_reason")
        driver_words = [f for f, v in vals.items() if v.get("from") == "driver" and (("idx" in v and v.get("kind", "message") == "message") or v.get("statement"))]
        if app_reason == "rider_no_show" and not driver_words:
            cert.allowed = ["no_action", "escalate"]; cert.flag_required = repeat
        else:
            # NS-0: NS-1 governs only a cancellation FOR a rider no-show. The app reason is the driver's own claim; his
            # messages and statement may say otherwise (NS-3: a reason of his own → no fee). That is a reading of words.
            eid = "NS-0:reason"
            cert.elements[eid] = {"default": "met" if app_reason == "rider_no_show" else None,
                                  "outcome": {"met": "no_action", "not_met": "refund_full"}, "flag_if_met": repeat}
            cert.predicates.append(Predicate("NS-0", f"[{eid}] the driver cancelled BECAUSE the rider did not show (NS-1), not for a reason of his own (NS-3)", "case", "judge",
                                             [x for x in [cancel_id] if x] + driver_words,
                                             f"app reason: {app_reason or 'none picked'} (the driver's claim); read his messages and statement: met → NS-1 holds, the fee stands; "
                                             "not_met ONLY when his own words give a reason of his own for cancelling — car trouble, a personal or family matter, another job, "
                                             "refusing the trip — → NS-3, refund the fee; undetermined → escalate. Where the car or the rider waited, and whether he was at "
                                             "the pickup, are not reasons of his own: NS-1 (i)–(iv) above already settle them"))
            cert.allowed = ["no_action", "refund_full", "escalate"]; cert.amount = FEE
            cert.flag_required = None
            cert.mechanical = False
    else:
        cert.allowed = ["refund_full", "escalate"]; cert.amount = FEE; cert.amount_formula = f"cancellation fee ${FEE:.2f}"
        cert.flag_required = bool(i_ok and not at_pickup)
        cert.predicates.append(Predicate("NS-2", "arrival confirmed while not at pickup → flag_account", "case",
                                         "pass" if cert.flag_required else "fail", [x for x in (here[0], near[0]) if x], "fake arrival confirmation" if cert.flag_required else "no fake confirmation"))
    return cert


# --------------------------------------------------------------------------- surge

def evaluate_surge(case: Case, table: FactTable) -> Certificate:
    """SURGE-1 … SURGE-3: surge rose between quote and trip start and the rider was not properly notified → refund
    the surge part (trip multiplier − quote multiplier) × surgeable subtotal; otherwise no refund."""
    vals = _vals(table)
    cert = Certificate(dispute_type="fare_dispute")
    cert.chat_index = _chat_index(vals)
    cert.fraud_flag = any((v.get("fraud_flags") or 0) >= 1 for v in vals.values() if "party" in v)
    diff = next(((f, v) for f, v in vals.items() if "surge_part" in v), (None, {}))
    notice = next(((f, v) for f, v in vals.items() if "rider_notified" in v), (None, {}))
    actual = next(((f, v) for f, v in vals.items() if "trip_multiplier" in v and "actual_subtotal" in v), (None, {}))
    if not diff[0]:
        cert.insufficient = "the record does not give both the quote-time and the trip-start surge multiplier"
        cert.predicates.append(Predicate("TH-4", "quote and trip multipliers on record", "case", "fail", [], cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    v = diff[1]
    rose = v["rose"]
    cert.predicates.append(Predicate("SURGE-2", "surge increased between quote and trip start", "case", "pass" if rose else "fail", [diff[0]],
                                     f"{v['quote_multiplier']:g}× → {v['trip_multiplier']:g}×"))
    if not rose:
        cert.allowed = ["no_action", "escalate"]; cert.flag_required = False
        return cert
    if actual[1].get("actual_subtotal") is None:
        cert.insufficient = "surge rose but the record gives no surgeable subtotal: the surge part cannot be computed"
        cert.predicates.append(Predicate("TH-4", "surgeable subtotal on record", "case", "fail", [actual[0]] if actual[0] else [], cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    n = notice[1]
    cert.flag_required = False
    cert.amount = v["surge_part"]
    cert.amount_formula = f"({v['trip_multiplier']:g} − {v['quote_multiplier']:g}) × surgeable subtotal = ${v['surge_part']:.2f}"
    timely = bool(n.get("rider_notified")) and bool(n.get("before_trip_start")) and n.get("in_app", True)
    when = ("not notified" if not n.get("rider_notified") else
            ("notified after the trip started" if not n.get("before_trip_start") else
             ("notified, but not in-app" if not n.get("in_app", True) else "notified in-app at or before pickup")))
    cert.predicates.append(Predicate("SURGE-1", "rider notified in-app at or before pickup", "case", "pass" if timely else "fail",
                                     [notice[0]] if notice[0] else [], when))
    if not timely:
        cert.allowed = ["refund_partial", "escalate"]
        return cert
    if not n.get("has_text"):
        cert.insufficient = "the rider was notified in time, but the text of the notice is not on record: whether it stated what SURGE-1 requires cannot be read"
        cert.predicates.append(Predicate("TH-4", "notice text on record", "case", "fail", [notice[0]], cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    eid = "SURGE-1:notice"
    cert.elements[eid] = {"default": None, "outcome": {"met": "no_action", "not_met": "refund_partial"}}
    cert.predicates.append(Predicate("SURGE-1", f"[{eid}] the notice states ALL THREE: the new multiplier, the revised fare, and that the rider may cancel without penalty", "case", "judge",
                                     [notice[0]], "read the quoted notice text: met → the higher fare stands (no_action); not_met (any of the three missing, vague "
                                     "or contradicted within the notice itself, e.g. 'fees may apply') → refund the surge part; undetermined → escalate. The clause "
                                     "asks the notice to STATE a revised estimated fare; an estimate that differs from the fare finally charged is still a stated "
                                     "estimate, and a rider's statement that no notice arrived does not outweigh the platform's log"))
    cert.allowed = ["refund_partial", "no_action", "escalate"]
    cert.mechanical = False
    return cert


# --------------------------------------------------------------------------- safety

def evaluate_safety(case: Case, table: FactTable) -> Certificate:
    """A complaint filed as a safety incident: never ruled automatically, whatever the chat says."""
    vals = _vals(table)
    cert = Certificate(dispute_type="safety")
    cert.chat_index = _chat_index(vals)
    cert.predicates.append(Predicate("SAFE-1", "complaint filed as a safety incident", "case", "pass", [], "no automatic ruling; the judge writes a factual summary for the reviewer"))
    cert.allowed = ["escalate"]
    cert.flag_required = None
    cert.mechanical = False
    return cert


def safety_screen_item(table: FactTable) -> Predicate:
    """Every case: the judge reads every message, statement and the complaint for threats, intimidation, harassment or
    dangerous driving (SAFE-1 / SAFE-2). Code cannot read meaning; it only points at lines a hint word marks."""
    vals = _vals(table)
    hinted = [fid for fid, v in vals.items() if v.get("keyword_hint")]
    note = (f"hint word in {', '.join(hinted)} — a locator, not a finding; read it in context" if hinted
            else "no hint word; read the messages anyway, a threat needs no keyword")
    return Predicate("SAFE-1", "safety screen: any threat, intimidation, harassment or dangerous-driving allegation in the chat, statement or complaint", "case",
                     "judge", hinted, f"answer in safety_concern (none / suspected / confirmed) with safety_basis; suspected or confirmed → escalate. {note}")


def evaluate(case: Case, table: FactTable) -> Certificate:
    if table.dispute_type == "safety":
        return evaluate_safety(case, table)
    cert = {"no_show": evaluate_no_show, "fare_dispute": evaluate_surge}.get(table.dispute_type, evaluate_route)(case, table)
    cert.predicates.append(safety_screen_item(table))
    if "escalate" not in cert.allowed:
        cert.allowed.append("escalate")
    return cert


# --------------------------------------------------------------------------- eligibility

def code_confidence(cert: Certificate, ruling: Optional[Ruling] = None, stipulated: dict | None = None,
                    stipulated_elements: dict | None = None) -> float:
    """TH-3, computed by code rather than reported by the model.
    evidence complete — an incomplete record never reaches here (it only escalates);
    policy clarity    — 1.0 when every element is settled by code, or the judge's reading of the words agrees with the
                        record (the app's own reason) or with what BOTH advocates read after arguing it; 0.90 when the
                        outcome rests on a reading that nothing else confirms;
    credibility       — ×0.97 when a party carries a fraud flag."""
    stipulated, stipulated_elements = stipulated or {}, stipulated_elements or {}
    open_reading = False
    if ruling is None:
        open_reading = not cert.mechanical
    else:
        for sf in ruling.segment_findings:
            sg = cert.segments.get(sf.fact_id)
            if sg is not None and sg["exempt"] is None and GROUND_CONSEQUENCE.get(stipulated.get(sf.fact_id)) != sf.finding:
                open_reading = True
        for ef in ruling.element_findings:
            el = cert.elements.get(ef.element)
            if el is not None and el.get("default") != ef.finding and stipulated_elements.get(ef.element) != ef.finding:
                open_reading = True
    return round((0.90 if open_reading else 1.0) * (0.97 if cert.fraud_flag else 1.0), 3)


def threshold_check(cert: Certificate, amount: Optional[float], ruling: Optional[Ruling] = None, stipulated: dict | None = None,
                    stipulated_elements: dict | None = None) -> tuple[bool, str]:
    """TH-1 / TH-3: may this ruling execute without a person? (ok, one-line reason). Safety and missing records are
    handled before this point; route disputes follow the amount bands (official sample DISP-001, policy section 9)."""
    amt = float(amount or 0) + (GOODWILL if cert.goodwill_required else 0)
    conf = code_confidence(cert, ruling, stipulated, stipulated_elements)
    need = 0.95 if cert.fraud_flag else (0.80 if amt >= TH_CONFIDENT else 0.0)
    if amt > TH_MANUAL:
        return False, f"TH-1: ${amt:.2f} is above ${TH_MANUAL:.0f} — a person decides; the system prepares the case file"
    if conf < need:
        why = "a party carries a fraud flag (TH-3: 95%)" if cert.fraud_flag else f"${amt:.2f} is in the $10–$50 band (TH-1: 80%)"
        return False, f"code confidence {conf:.0%} below the {need:.0%} needed: {why}"
    band = "under $10: the system decides" if amt < TH_CONFIDENT else f"${amt:.2f}, confidence {conf:.0%} ≥ {need:.0%}"
    return True, f"TH-1/TH-3: {band}; code confidence {conf:.0%}" + (" (fraud flag on record)" if cert.fraud_flag else "")


def escalate_grounds(ruling: Ruling) -> list[str]:
    """The judge-stated grounds on which an escalate stands on its own: code records them and never overrides them."""
    g = []
    if ruling.safety_concern != "none":
        g.append(f"safety concern {ruling.safety_concern} ({', '.join(ruling.safety_basis) or 'no basis listed'})")
    und = [sf.fact_id for sf in ruling.segment_findings if sf.finding == "undetermined"]
    if und:
        g.append(f"segment finding undetermined for {', '.join(und)}")
    und_e = [ef.element for ef in ruling.element_findings if ef.finding == "undetermined"]
    if und_e:
        g.append(f"undetermined reading of {', '.join(und_e)}")
    if ruling.evidence_status != "sufficient":
        g.append(f"evidence {ruling.evidence_status}: {ruling.evidence_gap or 'no detail given'}")
    return g


def _evidence_form(cert: Certificate, ruling: Ruling) -> list[str]:
    """The three-valued evidence_status and the evidence_gap words must agree with each other and with the trace."""
    r = []
    if ruling.evidence_status == "sufficient" and ruling.evidence_gap:
        r.append(f"evidence_status sufficient but evidence_gap carries text ({ruling.evidence_gap[:80]}): set evidence_gap to null, or set the status to insufficient / unknown")
    if ruling.evidence_status == "insufficient" and not ruling.evidence_gap:
        r.append("evidence_status insufficient but evidence_gap is empty: say what record is missing")
    if cert.insufficient and ruling.evidence_status == "sufficient":
        r.append(f"the trace finds the evidence insufficient ({cert.insufficient}) but evidence_status says sufficient")
    return r


def tie_possible(cert: Certificate, fid: str) -> bool:
    """Could any record tie this open segment to a named road (RD-5)? Road names on the segment's samples, a stop measured
    inside it, or a message (not the driver's later statement) sent once it had started. With none on record,
    "named_road_tied" is not a reading the record can support."""
    sg = cert.segments.get(fid) or {}
    if sg.get("stops") or sg.get("roads"):
        return True
    start = sg.get("start")
    return any(c["ts"] and not c["statement"] and start is not None and c["ts"] >= start for c in cert.chat_index.values())


def check_ruling(cert: Certificate, ruling: Ruling, stipulated: dict | None = None, argued: dict | None = None) -> tuple[bool, list[str]]:
    """Is the judge's ruling consistent with the certificate? (eligible_for_automation, reasons).

    An escalate is never inconsistent: it executes nothing. Everything else must sit inside what code measured.
    stipulated / argued exist only when advocates argued the case (the full court): stipulated = {segment: ground both
    sides state}; argued = {segment: {side: [grounds that side put forward]}}. A judge-decided finding that executes
    must rest on a ground some party argued; a ground no party argued is sent back, undetermined is always open."""
    reasons = _evidence_form(cert, ruling)
    if ruling.ruling == "escalate" or ruling.escalate:
        # An escalate executes nothing, but it must rest on a ground the trace leaves open: a safety concern, an
        # undetermined finding on a segment code did NOT settle, or missing evidence. "Undetermined" on a code-settled
        # segment, or a gap in a case the trace settles end to end, is not a ground — the judge is asked once more.
        if cert.allowed == ["escalate"] or cert.insufficient or ruling.safety_concern != "none":
            return (not reasons), reasons
        settled = {fid for fid, sg in cert.segments.items() if sg["exempt"] is not None}
        for sf in ruling.segment_findings:
            sg = cert.segments.get(sf.fact_id) or {}
            if sf.finding == "undetermined" and sg.get("exempt") is None and sg.get("roads") and sf.ground in ("named_road_untied", "named_road_tied", "named_road_elsewhere"):
                # the record names the roads this segment drove: a named-road agreement is settled by code, not left open
                reasons.append(f"segment {sf.fact_id}: the record lists the roads driven ({' → '.join(sg['roads'])}); put the agreed road in "
                               f"named_road and find named_road_tied or named_road_elsewhere — an agreement to a named road is not undetermined here")
        bad_und = [sf.fact_id for sf in ruling.segment_findings if sf.finding == "undetermined" and sf.fact_id in settled]
        open_und = [sf.fact_id for sf in ruling.segment_findings if sf.finding == "undetermined" and sf.fact_id not in settled
                    and not (sf.ground in ("named_road_untied", "named_road_tied", "named_road_elsewhere") and (cert.segments.get(sf.fact_id) or {}).get("roads"))]
        for fid in bad_und:
            reasons.append(f"finding undetermined for {fid}, but the trace settled that segment ({cert.segments[fid]['why']}): not a ground to escalate")
        for sf in ruling.segment_findings:
            # a point both advocates agree on is not open: undetermined on a stipulated ground is sent back once (the judge
            # may hold to it by naming the fact that refutes the stipulation; a second escalate stands)
            if sf.fact_id in open_und and stipulated and sf.fact_id in stipulated and sf.ground == stipulated[sf.fact_id] \
                    and GROUND_CONSEQUENCE[stipulated[sf.fact_id]] != "undetermined":
                want = GROUND_CONSEQUENCE[stipulated[sf.fact_id]]
                reasons.append(f"segment {sf.fact_id}: both advocates read the record as '{sf.ground}' (stipulated → {want}); undetermined on a point "
                               f"both sides agree on is not a ground to escalate — enter the finding '{want}', or name the fact that refutes the stipulation")
        gap = ruling.evidence_status != "sufficient"
        open_und += [ef.element for ef in ruling.element_findings if ef.finding == "undetermined" and ef.element in cert.elements]
        if not open_und and not bad_und and not gap:
            reasons.append("escalate without a ground: no safety concern, no undetermined finding, evidence_status sufficient")
        elif not open_und and not bad_und and gap and cert.mechanical:
            reasons.append("escalate on an evidence gap, but the trace settles this case end to end from the record: name the missing fact a clause needs, record a safety concern, or rule as the trace allows")
        return (not reasons), reasons
    if cert.insufficient:
        reasons.append(f"evidence insufficient ({cert.insufficient}) → only escalate")
    if ruling.evidence_status != "sufficient":
        reasons.append(f"evidence_status {ruling.evidence_status} but the ruling is {ruling.ruling}: only escalate can carry that status")
    if ruling.ruling not in cert.allowed:
        reasons.append(f"ruling {ruling.ruling} not in allowed {cert.allowed}")
    if ruling.safety_concern != "none":
        reasons.append(f"safety concern {ruling.safety_concern} recorded by the judge but the ruling is not escalate")
    if cert.dispute_type == "route_deviation" and cert.segments:
        seen_ids = [sf.fact_id for sf in ruling.segment_findings]
        for dup in sorted({f for f in seen_ids if seen_ids.count(f) > 1}):
            reasons.append(f"segment {dup} has {seen_ids.count(dup)} findings: give exactly one")
        findings = {sf.fact_id: sf for sf in ruling.segment_findings}
        for fid, sg in cert.segments.items():
            sf = findings.get(fid)
            if sf is None:
                reasons.append(f"judge gave no finding for segment {fid}")
                continue
            if sg["exempt"] is not None and sf.exempt != sg["exempt"]:
                reasons.append(f"judge finding for {fid} ({sf.finding}) contradicts code ({sg['why']})")
                continue
            if sg["exempt"] is None and sf.ground == "incident":
                reasons.append(f"segment {fid}: a traffic reason does not exempt a segment (RD-2); only the rider's agreement or request does (RD-5 / RD-3)")
                continue
            road_settled = False
            if sg["exempt"] is None and sg.get("roads") and sf.ground == "general_route_consent" and sf.excluded_road:
                # a general yes with a road ruled out ("ok, but not via Y"): code checks whether Y was driven
                excl = road_match(sf.excluded_road, sg["roads"])
                want_f = "counts" if excl else "exempt"
                road_settled = True
                if sf.finding != want_f:
                    reasons.append(f"segment {fid}: a general agreement that rules out '{sf.excluded_road}'; the segment drove {' → '.join(sg['roads'])}, "
                                   f"so '{sf.excluded_road}' was {'driven → the agreement does not cover it (counts)' if excl else 'NOT driven → the agreement covers it (exempt)'}; "
                                   f"the finding is {sf.finding}")
                    continue
            if sg["exempt"] is None and sg.get("roads") and sf.ground in ("named_road_tied", "named_road_untied", "named_road_elsewhere"):
                # RD-5: the judge reads WHICH road the rider agreed to and which road the words rule out; code applies the policy to the
                # roads the segment drove: agreed road driven and no excluded road driven → covered (exempt); otherwise counts
                if not sf.named_road:
                    reasons.append(f"segment {fid}: ground '{sf.ground}' needs named_road (the road the rider agreed to); code checks it against {' → '.join(sg['roads'])}")
                    continue
                if sf.ground == "named_road_untied":
                    reasons.append(f"segment {fid}: the record lists the roads driven ({' → '.join(sg['roads'])}): find named_road_tied or named_road_elsewhere")
                    continue
                driven = road_match(sf.named_road, sg["roads"])
                excl = bool(sf.excluded_road) and road_match(sf.excluded_road, sg["roads"])
                covered = driven and not excl
                if sf.ground == "named_road_tied" and not covered:
                    reasons.append(f"segment {fid}: roads driven {' → '.join(sg['roads'])}; " + (f"the rider ruled out '{sf.excluded_road}' and the segment drove it"
                                   if excl else f"'{sf.named_road}' is not among them") + " → the agreement does not cover the segment (named_road_elsewhere, counts)")
                    continue
                if sf.ground == "named_road_tied" and covered and sf.finding != "exempt":
                    reasons.append(f"segment {fid}: ground named_road_tied — '{sf.named_road}' was driven, so the agreement covers the segment (exempt); the finding is {sf.finding}")
                    continue
                if sf.ground == "named_road_elsewhere" and covered:
                    reasons.append(f"segment {fid}: you name '{sf.named_road}' as the road the rider agreed to, and the segment drove it ({' → '.join(sg['roads'])})"
                                   + (f" and not the excluded '{sf.excluded_road}'" if sf.excluded_road else "") + ". If the rider DID agree to it, the agreement covers "
                                   "the segment (named_road_tied, exempt). If the rider refused or never agreed, the ground is consent_after_or_none and named_road "
                                   "stays empty. A road the rider ruled out goes in excluded_road, never in named_road")
                    continue
                road_settled = True
            if sg["exempt"] is None:
                # a judge-decided segment: the words name the ground, the policy fixes the consequence
                # a ground both advocates state is advice, not a binding: the judge may read the words otherwise (the agreement
                # then does not raise the code confidence, TH-3)
                want = sf.finding if road_settled else GROUND_CONSEQUENCE.get(sf.ground)   # roads already decided the consequence
                if want is None:
                    reasons.append(f"segment {fid}: finding {sf.finding} rests on no named ground (ground 'other'): name the policy branch the words fall under "
                                   f"(rider_named_stop, general_route_consent, named_road_tied / _untied / _elsewhere, driver_errand, scope_other, consent_after_or_none)")
                    continue
                if sf.finding != want:
                    reasons.append(f"segment {fid}: ground '{sf.ground}' means {want} under the policy, but the finding is {sf.finding}: "
                                   f"either the ground or the finding is wrong")
                    continue
                # the readings the advocates argued inform the judge but do not limit it: both sides can miss the right reading
                put_forward = {g for gs in (argued or {}).get(fid, {}).values() for g in gs if g in GROUND_CONSEQUENCE}
                if put_forward and sf.finding == "exempt" and sf.ground in ("general_route_consent", "named_road_tied") and not sg.get("roads"):
                    # (with road names on record code settles a named road against the roads driven, so only a segment the
                    # record names no roads for keeps this guard)
                    # an exemption rests on what the rider agreed to; when one side reads the words as a general route choice and
                    # the other as an agreement to a named road, the kind of agreement itself is contested and no exemption executes
                    kinds = {"general" if g == "general_route_consent" else "named" for g in put_forward
                             if g in ("general_route_consent", "named_road_tied", "named_road_untied", "named_road_elsewhere")}
                    if len(kinds) == 2:
                        sides = "; ".join(f"{side}: {', '.join(gs) or '—'}" for side, gs in argued[fid].items())
                        reasons.append(f"segment {fid}: exempt on '{sf.ground}', but the advocates disagree on what the rider agreed to ({sides}): a general "
                                       f"route choice and a named road are different agreements, and an exemption cannot execute while the kind of agreement "
                                       f"is contested — find the segment undetermined (a person decides)")
                        continue
            if sf.finding == "undetermined":
                if sg.get("changes_outcome", True):
                    reasons.append(f"segment {fid} undetermined and the finding changes the outcome → a person decides (escalate)")
                continue      # a finding that moves neither the amount nor the flag may stay undetermined on a ruled case
            if sg["exempt"] is None and sf.finding == "exempt":
                # form check on the judge's reading: it must be an RD-3 / RD-5 reading (RD-4 is settled by code, and the
                # trace said no incident qualifies) resting on a rider message that exists and came before the segment
                if "RD-4" in (sf.reason or "") and not any(c in (sf.reason or "") for c in ("RD-5", "RD-3")):
                    reasons.append(f"exempt finding for {fid} rests on RD-4, which the trace settled against this segment")
                    continue
                basis = [b for b in sf.basis if b in cert.chat_index]
                if not basis:
                    reasons.append(f"exempt finding for {fid} rests on no chat fact (basis empty or not a message)")
                else:
                    seg_start = sg.get("start")
                    rider_before = [b for b in basis if cert.chat_index[b]["from"] in ("rider", "recorded_call") and not cert.chat_index[b]["statement"]
                                    and cert.chat_index[b]["ts"] and (seg_start is None or cert.chat_index[b]["ts"] < seg_start)]
                    only_statement = all(cert.chat_index[b]["statement"] for b in basis)
                    if only_statement:
                        reasons.append(f"exempt finding for {fid} rests only on the driver's statement — not consent (RD-5)")
                    elif not rider_before:
                        reasons.append(f"exempt finding for {fid} cites no rider message sent before the segment started")
        amt = expected_amount(cert, {fid: sf.exempt for fid, sf in findings.items()})
        if ruling.ruling == "refund_partial":
            if amt is None:
                reasons.append("amount undeterminable: a segment finding is missing or undetermined")
            elif amt <= 0:
                reasons.append("refund_partial, but with these findings what is left of the deviation is within the 1 km tolerance (RD-1) → no refund: the outcome is no_action")
            elif ruling.amount is None or abs(round(ruling.amount * 100) - round(amt * 100)) > 1:
                reasons.append(f"amount {ruling.amount} ≠ formula {amt:.2f}")
        if ruling.ruling == "no_action" and amt not in (None, 0.0):
            reasons.append(f"no_action but a non-exempt segment implies ${amt:.2f}")
    elif cert.dispute_type in ("no_show", "fare_dispute") and ruling.ruling in ("refund_full", "refund_partial"):
        want_amt = cert.amount if cert.amount is not None else cert.fee
        if ruling.amount is None or abs(round(ruling.amount * 100) - round(want_amt * 100)) > 1:
            reasons.append(f"amount {ruling.amount} ≠ {cert.amount_formula or 'the amount code fixes'} ({want_amt:.2f})")
    if cert.dispute_type == "no_show":
        gw = ruling.goodwill_credit or 0
        if cert.goodwill_required and abs(gw - GOODWILL) > 0.005:
            reasons.append(f"NS-8: the driver neither arrived nor tried to make contact → goodwill_credit {GOODWILL:.2f} required")
        if not cert.goodwill_required and gw:
            reasons.append("goodwill_credit given but NS-8 does not call for it")
    efs = {ef.element: ef for ef in ruling.element_findings}
    findings_by_id = {sf.fact_id: sf for sf in ruling.segment_findings}
    for eid, el in cert.elements.items():
        ef = efs.get(eid)
        if ef is None:
            reasons.append(f"no element_findings entry for {eid}: read the text the trace points to and record met / not_met / undetermined")
            continue
        if ef.finding == "undetermined":
            reasons.append(f"{eid} undetermined → a person decides (escalate)")
            continue
        if el.get("segment"):
            sf = findings_by_id.get(el["segment"])
            if ef.finding == "met" and sf is not None and sf.finding != "exempt":
                reasons.append(f"{eid} read as met: the rider named the place and the car stopped there, so under RD-3 the WHOLE segment {el['segment']} is "
                               f"exempt — the way there included; the finding is {sf.finding}")
        else:
            want = el["outcome"][ef.finding]
            if ruling.ruling != want:
                reasons.append(f"{eid} read as {ef.finding}, which means {want} under the policy, but the ruling is {ruling.ruling}")
        if not ef.basis:
            reasons.append(f"{eid}: the reading names no fact it rests on (basis empty)")
    flag_required = cert.flag_required
    if any("flag_if_met" in el for el in cert.elements.values()):
        flag_required = any(el.get("flag_if_met") and efs.get(eid) is not None and efs[eid].finding == "met" for eid, el in cert.elements.items())
    if cert.flag_conditional and cert.dispute_type == "route_deviation":
        findings = {sf.fact_id: sf.exempt for sf in ruling.segment_findings}
        flag_required = bool(expected_amount(cert, findings))       # upheld = a refund is due
    if flag_required is not None:
        has_flag = bool(getattr(ruling, "flag_account", False))   # structured field only: free text never creates an account action
        if flag_required and not has_flag:
            reasons.append("flag_account required by the certificate but not recommended")
        if not flag_required and has_flag:
            reasons.append("flag_account recommended but no clause requires it")
    return (not reasons), reasons
