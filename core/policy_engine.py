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

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from core.facts.tools import _project
from core.schemas import GROUND_CONSEQUENCE, Case, FactTable, Ruling

Status = Literal["pass", "fail", "judge", "n/a"]
NEAR_ROUTE_M = 300          # data-layer parameter (gap G3)
PICKUP_RADIUS_M = 200       # data-layer parameter (gap G2)
GRACE_S = 180               # NS-1(iii), NS-4: "more than 3 minutes" (Ryde default; a case record may state its own free-wait window)
CANCEL_FEE = 6.61           # Ryde default; a case record may carry its own cancellation fee


def grace_s(case: "Case") -> int:
    """NS-4 rider-cancel grace in seconds: Ryde's 3 minutes. A record's free-wait window is a different parameter
    (when waiting fees start) and does not change it."""
    return GRACE_S


def no_show_threshold(case: "Case") -> tuple[int, bool, str]:
    """NS-1 (iii) wait threshold as (seconds, inclusive, source).

    The case record's own no-show threshold when it states one (the organisers' sample: 8 min, and its timeline says
    "threshold reached", so reaching it counts: at least 8 min); else Ryde's default NS-1 rule: more than 3 min.
    free_wait_min is never used as a stand-in: it says when waiting fees start, not when a no-show may be declared."""
    pp = getattr(case, "policy_params", None)
    m = getattr(pp, "no_show_threshold_min", None) if pp else None
    if m:
        return int(m * 60), True, f"case record: no-show threshold {m:g} min, reached = at least {m:g} min"
    return GRACE_S, False, f"NS-1 default: more than {GRACE_S // 60} min"


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

    def what_would_change(self, findings: Optional[dict] = None) -> list[str]:
        """Deterministic 'what would change this ruling' sentences, derived from the failed / passed predicates.
        `findings` (segment fact id -> "exempt" / "counts" / "undetermined"), when given, phrases a judge-decided segment
        as what was found rather than as an open question."""
        out = []
        findings = findings or {}
        if self.dispute_type == "no_show":
            st = {(p.clause, p.element[:5]): p for p in self.predicates}
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
            if "no_action" in self.allowed and any(p.clause == "NS-1" and p.status == "pass" for p in self.predicates):
                out.append(f"Had the driver confirmed arrival more than 200 m away, or left before {self.wait_threshold / 60:g} minutes, NS-2 would refund the fee in full.")
        elif self.dispute_type == "route_deviation":
            for fid, sg in self.segments.items():
                money = (lambda km: f"${km * self.rate_per_km:.2f}") if self.rate_per_km else None
                if sg["exempt"] is False:
                    out.append(f"Had an LTA incident been recorded on the stretch {fid} replaced, before it started, RD-4 would exempt it"
                               + (f" (−{money(sg['extra_km'])})." if money else " (fixed fare: no amount changes, the RD-1 breach would not be recorded)."))
                if sg["exempt"] is None and findings.get(fid) == "exempt":
                    out.append(f"{fid}: the judge found the rider's own message covers this segment, so it is exempt; without that message "
                               + (f"{money(sg['extra_km'])} would be refunded." if money else "the RD-1 breach would be recorded."))
                elif sg["exempt"] is None and findings.get(fid) == "counts":
                    out.append(f"{fid}: the judge found no rider agreement covering this segment, so "
                               + (f"{money(sg['extra_km'])} is refunded" if money else "the RD-1 breach is recorded")
                               + "; a rider message agreeing to it before it started would have exempted it.")
                elif sg["exempt"] is None and findings.get(fid) == "undetermined":
                    out.append(f"{fid}: the record does not settle whether the rider's agreement covers this segment; a person decides"
                               + (f" whether {money(sg['extra_km'])} is refunded." if money else "."))
                elif sg["exempt"] is None:
                    out.append(f"{fid}: if the judge finds the rider agreed to this route or named this stop beforehand, it is exempt; if not, "
                               + (f"{money(sg['extra_km'])} is refunded" if money else "the RD-1 breach is recorded (fixed fare: no refund)")
                               + "; if the record cannot settle it, a person decides.")
            if not self.segments and any(p.clause == "RD-1" and p.status == "fail" for p in self.predicates):
                out.append("Had the trace left the quoted route by more than 200 m for a stretch adding at least 0.2 km, RD-1 would apply and the extra kilometres would be weighed.")
            if self.flag_required is False and any(p.clause == "RD-6" for p in self.predicates):
                out.append("Had the driver carried a prior upheld route dispute in the last 90 days, RD-6 would add an account flag.")
        return out

    def lines(self) -> list[str]:
        out = []
        for p in self.predicates:
            mark = {"pass": "✓", "fail": "✗", "judge": "?", "n/a": "–"}[p.status]
            out.append(f"{mark} {p.clause} {p.element} [{p.subject}] {p.detail} ({', '.join(p.evidence) or 'no evidence'})")
        if self.dispute_type == "no_show" and (self.fee != CANCEL_FEE or self.wait_source.startswith("case record")):
            out.append(f"parameters from the case record: cancellation fee ${self.fee:.2f}; NS-1 (iii) wait threshold {self.wait_threshold / 60:g} min "
                       f"({'at least' if self.wait_inclusive else 'more than'}; {self.wait_source}) — read these wherever NS-1 / NS-2 say ${CANCEL_FEE:.2f} / {GRACE_S // 60} min. "
                       f"NS-4 (rider cancels) keeps Ryde's {GRACE_S // 60} min.")
        if self.insufficient:
            out.append(f"evidence insufficient: {self.insufficient}")
        out.append(f"allowed outcomes: {', '.join(self.allowed) or '—'}" + (f"; amount = {self.amount_formula}" if self.amount_formula else ""))
        if self.flag_conditional:
            out.append("flag_account required: only if a segment is found non-exempt (RD-6 prior upheld dispute on file)")
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
    return {fid: {"from": v.get("from"), "ts": v.get("ts"), "statement": bool(v.get("statement"))}
            for fid, v in vals.items() if ("idx" in v and "from" in v) or v.get("statement")}


def evaluate_route(case: Case, table: FactTable) -> Certificate:
    vals = _vals(table)
    cert = Certificate(dispute_type="route_deviation")
    cert.chat_index = _chat_index(vals)
    segs = {fid: v for fid, v in vals.items() if "extra_km" in v and "start" in v}
    fare = next((v for v in vals.values() if "total" in v and "base_fare" in v), {})
    metered = case.trip.service_type == "RydeTAXI"
    rate = (fare["distance_fare"] / fare["distance_km"]) if (metered and fare.get("distance_km")) else None   # exact; rounded once
    cert.rate_per_km = rate
    incidents = [(fid, v) for fid, v in vals.items() if "reported_at" in v]
    messages = [(fid, v) for fid, v in vals.items() if "idx" in v and "from" in v]
    record = next((v for v in vals.values() if "complete" in v and "count" in v), {"complete": True, "count": 0})
    statement = next((fid for fid, v in vals.items() if v.get("statement")), None)
    # ---- evidence sufficiency: the route question needs a trace that covers the trip
    missing = [fid for fid, v in vals.items() if v.get("gps_missing")]
    gaps = [fid for fid, v in vals.items() if "gps_gap_s" in v]
    cover = [fid for fid, v in vals.items() if v.get("uncovered_start_s") or v.get("uncovered_end_s")]
    if missing or gaps or cover:
        what = ("no GPS trace for the trip" if missing else "; ".join(
            ([f"GPS trace has {len(gaps)} hole(s); an off-route stretch inside a hole cannot be measured"] if gaps else [])
            + (["GPS trace does not cover the whole trip (starts late or ends early); the uncovered stretch cannot be measured"] if cover else [])))
        cert.predicates.append(Predicate("RD-1", "GPS trace covers the trip", "case", "fail", missing + gaps + cover, what))
        cert.insufficient = what
        cert.allowed = ["escalate"]
        cert.mechanical = False
        return cert
    if not segs:
        cert.predicates.append(Predicate("RD-1", "off-route segment exists", "case", "fail", [], "no off-route segment measured (trace follows the quoted route)"))
        cert.allowed = ["no_action", "escalate"]
        cert.flag_required = False          # nothing upheld: no clause calls for a flag, and one recommended anyway is rejected
        return cert
    cert.predicates.append(Predicate("RD-1", "off-route segment(s) exist", "case", "pass", list(segs), f"{len(segs)} segment(s)"))
    comm_ids = [fid for fid, _ in messages] + ([statement] if statement else [])
    drv = next((v for v in vals.values() if v.get("party") == "driver"), {})
    prior = drv.get("route_disputes_upheld_90d", 0) >= 1
    changes_outcome = bool(metered and rate is not None) or prior      # a finding moves the amount (metered) or the RD-6 flag (prior)
    changes_txt = ("This finding changes the amount." if (metered and rate is not None) else "This finding changes no amount (fixed fare)"
                   + (" but decides the RD-6 flag (the driver has a prior)." if prior else " and no flag: if you cannot settle it, undetermined is allowed and the case may still be ruled."))
    for fid, seg in segs.items():
        start = _ts(seg["start"])
        lo, hi = _segment_replaced_stretch(case, seg)
        # RD-4: an incident on the replaced stretch, reported before the segment started — measurable, so code settles it
        rd4 = [iid for iid, inc in incidents if _ts(inc["reported_at"]) < start and _incident_on_stretch(case, inc, lo, hi)]
        if rd4:
            cert.predicates.append(Predicate("RD-4", "(a) incident on the replaced stretch, reported before the detour", fid, "pass", rd4,
                                             f"incident within {NEAR_ROUTE_M} m of optimal km {lo:.1f}–{hi:.1f}"))
            cert.predicates.append(Predicate("RD-5", "consent scope", fid, "n/a", [], "not needed: RD-4 already exempts this segment"))
            cert.predicates.append(Predicate("RD-3", "rider-requested stop", fid, "n/a", [], "not needed: RD-4 already exempts this segment"))
            cert.segments[fid] = {"exempt": True, "extra_km": seg["extra_km"], "start": seg["start"], "why": f"RD-4 via {', '.join(rd4)}"}
            continue
        cert.predicates.append(Predicate("RD-4", "(a) incident on the replaced stretch, reported before the detour", fid, "fail", [iid for iid, _ in incidents],
                                         "no qualifying incident (speed band alone does not exempt)"))
        # RD-5 / RD-3: whether the rider agreed to this route, or named this stop, is a reading of what was said.
        # Code only establishes WHETHER there is anything to read and whether it is timed.
        before = [cid for cid, c in messages if c.get("ts") and _ts(c["ts"]) < start]
        untimed = [cid for cid, c in messages if not c.get("ts")]
        if not comm_ids:
            cert.predicates.append(Predicate("RD-5", "rider agreed to this route before the detour", fid, "fail", [], "no chat message and no driver statement on record: nothing to read as consent"))
            cert.predicates.append(Predicate("RD-3", "rider-requested stop", fid, "fail", [], "no chat message on record"))
            cert.segments[fid] = {"exempt": False, "extra_km": seg["extra_km"], "start": seg["start"], "why": "no communication on record"}
            continue
        stop_ids = [sid for sid, v in vals.items() if "duration_s" in v and "m_from_pickup" in v and seg["start"] <= v.get("start", "") <= seg["end"]]
        texts = "; ".join(f"{cid}: {table_text(table, cid)}" for cid in before + untimed + ([statement] if statement else []))
        timing = ("" if record.get("complete", True) else f" {len(untimed)} message(s) carry no time: if the finding turns on them, it is undetermined.")
        cert.predicates.append(Predicate("RD-5", "rider agreed to this route before the detour; scope of that agreement", fid, "judge", before + untimed + ([statement] if statement else []),
                                         f"RULE: exempt only if a RIDER message sent before {start:%H:%M:%S} agrees AND the agreement covers this segment. Three kinds of agreement: "
                                         f"(1) GENERAL route choice ('take whichever way is faster') covers a route chosen to get there, not an errand of the driver's own (a stop away from the route, a loop that reaches nothing: counts). "
                                         f"(2) A SPECIFIC named road or area ('go round via X') covers driving on X only: the record must tie this segment to X (a stop on X, a message placing the car on X, a road name in a fact); "
                                         f"timing alone does not, and the fact table carries no road names for the driven path — if nothing ties them, the finding is undetermined (G13); "
                                         f"if the record places this segment somewhere else (a stop away from X, the driver's own statement naming another road or place, a stop the driver chose the location of), the agreement to X does not cover it: counts. "
                                         f"(3) Scope unclear: undetermined. A driver's claim of agreement that appears only in his statement is not consent (G11); a complete chat record with no rider agreement before the segment: counts.{timing} "
                                         f"{changes_txt} Evidence — {texts}"))
        cert.predicates.append(Predicate("RD-3", "rider-requested stop; whether the rider named this place", fid, "judge", before + stop_ids,
                                         f"RULE (RD-3(a)): exempt if a RIDER message before the segment named a specific place and the car stopped there (the whole way there is exempt; "
                                         f"how long the stop lasted or how far the place was does not reduce it). "
                                         f"A stop the rider asked for without naming a place ('a 7-Eleven on the way') does not excuse the driver's choice of a far one → counts."
                                         + (f" Stops in this segment: {', '.join(stop_ids)}." if stop_ids else " No stop measured in this segment.")))
        cert.segments[fid] = {"exempt": None, "extra_km": seg["extra_km"], "start": seg["start"], "why": "judge reads RD-5 / RD-3 from the chat and statement",
                              "changes_outcome": changes_outcome}
        cert.mechanical = False
    definite_bad = [f for f, sg in cert.segments.items() if sg["exempt"] is False]
    undecided = [f for f, sg in cert.segments.items() if sg["exempt"] is None]
    if not metered:
        cert.predicates.append(Predicate("RD-2", "metered service (detour km enters the fare)", "case", "fail", [], f"{case.trip.service_type} is a fixed fare"))
        cert.allowed = ["no_action", "escalate"]
    elif metered and rate is None:
        cert.predicates.append(Predicate("RD-2", "per-km rate derivable from the fare record", "case", "fail", [], "metered trip but the fare record has no distance / distance fare: refund cannot be computed"))
        cert.insufficient = "metered trip without a distance fare on record: the RD-2 amount cannot be computed"
        cert.allowed = ["escalate"]
        cert.mechanical = False
    elif definite_bad and not undecided:
        cert.allowed = ["refund_partial", "escalate"]
    elif definite_bad or undecided:
        cert.allowed = ["refund_partial", "no_action", "escalate"]
    else:
        cert.allowed = ["no_action", "escalate"]
    if metered and rate:
        cert.amount_formula = f"Σ extra_km of non-exempt segments × ${rate:.4f}/km (distance_fare ÷ distance_km), rounded to cents"
    cert.predicates.append(Predicate("RD-6", "prior upheld route dispute in 90 d (repeated breach → flag_account)", "case",
                                     "pass" if prior else "fail", [f for f, v in vals.items() if v.get("party") == "driver"],
                                     f"route_disputes_upheld_90d = {drv.get('route_disputes_upheld_90d', 0)}"))
    # RD-6 needs the case UPHELD (≥1 non-exempt segment). Definite → known now; undecided → depends on the judge's findings.
    cert.flag_required = bool(prior) if (definite_bad and not undecided) else (None if (undecided and prior) else False)
    cert.flag_conditional = bool(undecided and prior)
    return cert


def expected_amount(cert: Certificate, findings: dict[str, Optional[bool]]) -> Optional[float]:
    """Amount implied by the certificate once the judge's segment findings fill the undecided slots.
    None when a slot is missing or undetermined: then no amount can execute."""
    if cert.rate_per_km is None:
        return None
    total = 0.0
    for fid, s in cert.segments.items():
        exempt = s["exempt"] if s["exempt"] is not None else findings.get(fid)
        if exempt is None:
            return None
        if not exempt:
            total += s["extra_km"] * cert.rate_per_km
    return round(total + 1e-9, 2)


# --------------------------------------------------------------------------- no-show

def evaluate_no_show(case: Case, table: FactTable) -> Certificate:
    vals = _vals(table)
    T, incl, src = no_show_threshold(case)
    cert = Certificate(dispute_type="no_show", fee=cancel_fee(case), grace=grace_s(case), wait_threshold=T, wait_inclusive=incl, wait_source=src)
    G, FEE, GM, TM = cert.grace, cert.fee, cert.grace / 60, T / 60
    cancel = next((v for v in vals.values() if "s_after_accept" in v), {})
    near = next(((f, v) for f, v in vals.items() if "nearest_m" in v), (None, {}))
    here = next(((f, v) for f, v in vals.items() if "driver_pressed_here_at" in v), (None, {}))
    cancel_id = next((f for f, v in vals.items() if "s_after_accept" in v), None)
    by = cancel.get("cancelled_by")
    cert.chat_index = _chat_index(vals)
    cert.predicates.append(Predicate("NS-0", "who cancelled", "case", "pass" if by in ("rider", "driver") else "fail", [cancel_id] if cancel_id else [], f"cancelled_by = {by}"))
    if not cancel_id:
        cert.insufficient = "no cancellation on the timeline: who cancelled and when is not on record"
        cert.predicates.append(Predicate("NS-0", "cancellation on record", "case", "fail", [], cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    if by not in ("rider", "driver"):
        cert.insufficient = f"who cancelled is not on record (cancelled_by = {by}): NS-1 (driver declares a no-show) and NS-4 (rider cancels) cannot be told apart"
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    if by == "rider":
        late = cancel.get("s_after_accept", 0) > G
        cert.predicates.append(Predicate("NS-4", f"rider cancelled more than {GM:g} min after matching", "case", "pass" if late else "fail",
                                         [cancel_id], f"{cancel.get('s_after_accept')} s after acceptance"))
        cert.allowed = ["no_action", "escalate"] if late else ["refund_full", "escalate"]
        cert.amount_formula = None if late else f"cancellation fee ${FEE:.2f}"
        cert.flag_required = False
        return cert
    # driver cancelled as rider no-show → NS-1 three elements; they need the driver's trace over the whole wait
    missing = [f for f, v in vals.items() if v.get("gps_missing")]
    if missing:
        cert.insufficient = "no GPS trace between acceptance and cancellation: where the driver waited cannot be measured"
        cert.predicates.append(Predicate("NS-1", "GPS trace covers the wait", "case", "fail", missing, cert.insufficient))
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
        cert.insufficient = "; ".join(parts)
        cert.predicates.append(Predicate("NS-1", "GPS trace covers the wait without a hole", "case", "fail", holes + cover, cert.insufficient))
        cert.allowed = ["escalate"]; cert.mechanical = False
        return cert
    if here_at:
        cert.predicates.append(Predicate("NS-1", "GPS trace covers the wait without a hole", "case", "pass",
                                         [f for f, v in vals.items() if "median_interval_s" in v or "within_200m_s" in v or "driver_pressed_here_at" in v],
                                         "samples run from the arrival confirmation to the cancellation with no gap beyond the hole threshold"))
    i_ok = bool(here_at)
    d_tap = here[1].get("m_from_pickup_at_tap")
    ii_ok = d_tap is not None and d_tap <= PICKUP_RADIUS_M
    cont = here[1].get("within_200m_after_tap_s", 0) or 0
    iii_ok = (cont >= T) if incl else (cont > T)
    tail = here[1].get("tail_uncovered_s", 0) or 0
    if here_at and not iii_ok and tail and not here[1].get("left_radius"):
        with_tail = cont + tail
        if (with_tail >= T) if incl else (with_tail > T):
            # the samples alone do not reach the threshold; the samples plus the uncovered tail would. The tail is not
            # on record, so neither "waited long enough" nor "did not" can be measured.
            cert.insufficient = (f"GPS stops {tail} s before the cancellation: {cont} s of waiting are measured, the threshold is {T} s, "
                                 f"and the uncovered {tail} s would decide it (G12)")
            cert.predicates.append(Predicate("NS-1", "(iii) wait measured up to the cancellation", "case", "fail", [here[0]] if here[0] else [], cert.insufficient))
            cert.allowed = ["escalate"]; cert.mechanical = False
            return cert
    auto = here[1].get("arrival_confirmed_by") == "platform_auto"
    kind = "platform_auto arrival" if auto else "driver_tap"
    when = (here_at or "—")[11:19]
    cert.predicates.append(Predicate("NS-1", "(i) arrival confirmed: driver tapped I'm Here, or the platform auto-confirmed arrival", "case", "pass" if i_ok else "fail", [here[0]] if here[0] else [],
                                     (f"{kind} at {when} (no manual tap in this record)" if auto else (f"{kind} at {when}" if i_ok else "no arrival confirmation on record"))))
    cert.predicates.append(Predicate("NS-1", f"(ii) within {PICKUP_RADIUS_M} m of pickup AT THE MOMENT of the arrival confirmation", "case", "pass" if ii_ok else "fail",
                                     [x for x in (here[0], near[0]) if x], f"{d_tap if d_tap is not None else '—'} m from pickup at the {kind} (closest approach overall {near[1].get('nearest_m')} m)"))
    cert.predicates.append(Predicate("NS-1", f"(iii) stayed at the pickup {'at least' if incl else 'more than'} {TM:g} min after the arrival confirmation, until cancelling ({src})", "case", "pass" if iii_ok else "fail",
                                     [here[0]] if here[0] else [], f"{cont} s continuously inside the radius after the {kind} at {when}; threshold {T} s ({'≥' if incl else '>'})"))
    if i_ok and ii_ok and iii_ok:
        cert.allowed = ["no_action", "escalate"]; cert.flag_required = False
    else:
        cert.allowed = ["refund_full", "escalate"]; cert.amount_formula = f"cancellation fee ${FEE:.2f}"
        cert.flag_required = bool(i_ok and not ii_ok)
        cert.predicates.append(Predicate("NS-2", "arrival confirmed while not at pickup → flag_account", "case",
                                         "pass" if cert.flag_required else "fail", [x for x in (here[0], near[0]) if x], "fake arrival confirmation" if cert.flag_required else "no fake confirmation"))
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
    cert = evaluate_no_show(case, table) if table.dispute_type == "no_show" else evaluate_route(case, table)
    cert.predicates.append(safety_screen_item(table))
    if "escalate" not in cert.allowed:
        cert.allowed.append("escalate")
    return cert


# --------------------------------------------------------------------------- eligibility

def escalate_grounds(ruling: Ruling) -> list[str]:
    """The judge-stated grounds on which an escalate stands on its own: code records them and never overrides them."""
    g = []
    if ruling.safety_concern != "none":
        g.append(f"safety concern {ruling.safety_concern} ({', '.join(ruling.safety_basis) or 'no basis listed'})")
    und = [sf.fact_id for sf in ruling.segment_findings if sf.finding == "undetermined"]
    if und:
        g.append(f"segment finding undetermined for {', '.join(und)}")
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


def check_ruling(cert: Certificate, ruling: Ruling) -> tuple[bool, list[str]]:
    """Is the judge's ruling consistent with the certificate? (eligible_for_automation, reasons).

    An escalate is never inconsistent: it executes nothing. Everything else must sit inside what code measured."""
    reasons = _evidence_form(cert, ruling)
    if ruling.ruling == "escalate" or ruling.escalate:
        # An escalate executes nothing, but it must rest on a ground the trace leaves open: a safety concern, an
        # undetermined finding on a segment code did NOT settle, or missing evidence. "Undetermined" on a code-settled
        # segment, or a gap in a case the trace settles end to end, is not a ground — the judge is asked once more.
        if cert.allowed == ["escalate"] or cert.insufficient or ruling.safety_concern != "none":
            return (not reasons), reasons
        settled = {fid for fid, sg in cert.segments.items() if sg["exempt"] is not None}
        bad_und = [sf.fact_id for sf in ruling.segment_findings if sf.finding == "undetermined" and sf.fact_id in settled]
        open_und = [sf.fact_id for sf in ruling.segment_findings if sf.finding == "undetermined" and sf.fact_id not in settled]
        for fid in bad_und:
            reasons.append(f"finding undetermined for {fid}, but the trace settled that segment ({cert.segments[fid]['why']}): not a ground to escalate")
        gap = ruling.evidence_status != "sufficient"
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
            if sg["exempt"] is None:
                # a judge-decided segment: the words name the ground, the policy fixes the consequence
                want = GROUND_CONSEQUENCE.get(sf.ground)
                if want is None:
                    reasons.append(f"segment {fid}: finding {sf.finding} rests on no named ground (ground 'other'): name the policy branch the words fall under "
                                   f"(rider_named_stop, general_route_consent, named_road_tied / _untied / _elsewhere, driver_errand, scope_other, consent_after_or_none)")
                    continue
                if sf.finding != want:
                    reasons.append(f"segment {fid}: ground '{sf.ground}' means {want} under the policy, but the finding is {sf.finding}: "
                                   f"either the ground or the finding is wrong")
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
                    rider_before = [b for b in basis if cert.chat_index[b]["from"] == "rider" and not cert.chat_index[b]["statement"]
                                    and cert.chat_index[b]["ts"] and (seg_start is None or cert.chat_index[b]["ts"] < seg_start)]
                    only_statement = all(cert.chat_index[b]["statement"] for b in basis)
                    if only_statement:
                        reasons.append(f"exempt finding for {fid} rests only on the driver's statement — not consent (G11)")
                    elif not rider_before:
                        reasons.append(f"exempt finding for {fid} cites no rider message sent before the segment started")
        amt = expected_amount(cert, {fid: sf.exempt for fid, sf in findings.items()})
        if ruling.ruling == "refund_partial":
            if amt is None:
                reasons.append("amount undeterminable: a segment finding is missing or undetermined")
            elif amt <= 0:
                reasons.append("refund_partial but every segment is exempt → amount would be 0")
            elif ruling.amount is None or abs(round(ruling.amount * 100) - round(amt * 100)) > 1:
                reasons.append(f"amount {ruling.amount} ≠ formula {amt:.2f}")
        if ruling.ruling == "no_action" and amt not in (None, 0.0):
            reasons.append(f"no_action but a non-exempt segment implies ${amt:.2f}")
    elif cert.dispute_type == "no_show" and ruling.ruling == "refund_full":
        if ruling.amount is None or abs(round(ruling.amount * 100) - round(cert.fee * 100)) > 1:
            reasons.append(f"amount {ruling.amount} ≠ cancellation fee {cert.fee}")
    flag_required = cert.flag_required
    if cert.flag_conditional and cert.dispute_type == "route_deviation":
        findings = {sf.fact_id: sf.exempt for sf in ruling.segment_findings}
        upheld = any((sg["exempt"] if sg["exempt"] is not None else findings.get(fid)) is False for fid, sg in cert.segments.items())
        flag_required = upheld
    if flag_required is not None:
        has_flag = bool(getattr(ruling, "flag_account", False))   # structured field only: free text never creates an account action
        if flag_required and not has_flag:
            reasons.append("flag_account required by the certificate but not recommended")
        if not flag_required and has_flag:
            reasons.append("flag_account recommended but no clause requires it")
    return (not reasons), reasons
