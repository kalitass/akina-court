"""Policy execution engine (code, no LLM): evaluates the numbered clauses as predicates over fact values.

Each predicate is three-state:
    pass     the facts satisfy the clause element (evidence ids listed)
    fail     the facts contradict it
    judge    the element is interpretive (scope of a rider's consent, whether "a 7-Eleven on the way" covers a
             2.8 km route change) — the Judge decides it and must say so in Ruling.segment_findings

From the predicates the engine derives the ALLOWED outcomes and the exact amount formula. core.verify then checks the
Judge's ruling against this certificate: a ruling outside the allowed set, an amount off by more than $0.01, or a
required predicate left undecided → the case is not eligible for automation and is routed to human review.

This is the "code locks, judge explains" firewall: mechanical elements are decided by code, interpretive elements
by the judge, and the two must agree.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from core.facts.tools import _project
from core.schemas import Case, FactTable, Ruling

Status = Literal["pass", "fail", "judge", "n/a"]
NEAR_ROUTE_M = 300          # data-layer parameter (gap G3)
PICKUP_RADIUS_M = 200       # data-layer parameter (gap G2)
GRACE_S = 180               # NS-1(iii), NS-4: "more than 3 minutes" (Ryde default; a case record may state its own free-wait window)
CANCEL_FEE = 6.61           # Ryde default; a case record may carry its own cancellation fee


def grace_s(case: "Case") -> int:
    """Free-wait window in seconds: the case record's own rule when it states one, else Ryde's 3 minutes."""
    pp = getattr(case, "policy_params", None)
    m = getattr(pp, "free_wait_min", None) if pp else None
    return int(m * 60) if m else GRACE_S


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
    grace: int = GRACE_S                                    # free-wait window (s) this case was evaluated with
    flag_conditional: bool = False                          # route: flag iff the judge finds ≥1 non-exempt segment
    mechanical: bool = True                                 # True = outcome fully determined by code

    def what_would_change(self) -> list[str]:
        """Deterministic 'what would change this ruling' sentences, derived from the failed / passed predicates."""
        out = []
        if self.dispute_type == "no_show":
            st = {(p.clause, p.element[:5]): p for p in self.predicates}
            if "no_action" in self.allowed and any(p.clause == "NS-4" for p in self.predicates):
                out.append(f"Had the rider cancelled within {self.grace // 60} minutes of matching, NS-4 would have waived the ${self.fee:.2f} fee.")
            for p in self.predicates:
                if p.clause == "NS-1" and p.status == "fail":
                    out.append(f"Had NS-1 {p.element.split(' ')[0]} held ({p.element}), the fee would stand and no refund would be due.")
                if p.clause == "NS-1" and p.status == "pass" and "refund_full" not in self.allowed:
                    pass
            if "no_action" in self.allowed and any(p.clause == "NS-1" and p.status == "pass" for p in self.predicates):
                out.append(f"Had the driver tapped I'm Here more than 200 m away, or left before {self.grace // 60} minutes, NS-2 would refund the fee in full.")
        elif self.dispute_type == "route_deviation":
            for fid, sg in self.segments.items():
                if sg["exempt"] is False:
                    out.append(f"Had an LTA incident been recorded on the stretch {fid} replaced, before it started, RD-4 would exempt it (−${sg['extra_km'] * (self.rate_per_km or 0):.2f}).")
                if sg["exempt"] is None:
                    out.append(f"{fid}: if the judge finds the rider's agreement covered this route, it is exempt; otherwise ${sg['extra_km'] * (self.rate_per_km or 0):.2f} is refunded.")
            if self.flag_required is False and any(p.clause == "RD-6" for p in self.predicates):
                out.append("Had the driver carried a prior upheld route dispute in the last 90 days, RD-6 would add an account flag.")
        return out

    def lines(self) -> list[str]:
        out = []
        for p in self.predicates:
            mark = {"pass": "✓", "fail": "✗", "judge": "?", "n/a": "–"}[p.status]
            out.append(f"{mark} {p.clause} {p.element} [{p.subject}] {p.detail} ({', '.join(p.evidence) or 'no evidence'})")
        if self.dispute_type == "no_show" and (self.fee != CANCEL_FEE or self.grace != GRACE_S):
            out.append(f"parameters from the case record: cancellation fee ${self.fee:.2f}, free wait {self.grace / 60:g} min "
                       f"(read these wherever the NS clauses say ${CANCEL_FEE:.2f} / {GRACE_S // 60} min)")
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


def _incident_on_stretch(case: Case, inc: dict, lo_km: float, hi_km: float) -> bool:
    d, along = _project(inc["lat"], inc["lon"], case.route.polyline)
    return d <= NEAR_ROUTE_M and (lo_km - 0.3) <= along <= (hi_km + 0.3)


def evaluate_route(case: Case, table: FactTable) -> Certificate:
    vals = _vals(table)
    cert = Certificate(dispute_type="route_deviation")
    segs = {fid: v for fid, v in vals.items() if "extra_km" in v and "start" in v}
    fare = next((v for v in vals.values() if "total" in v and "base_fare" in v), {})
    metered = case.trip.service_type == "RydeTAXI"
    rate = (fare["distance_fare"] / fare["distance_km"]) if (metered and fare.get("distance_km")) else None   # exact; rounded once
    cert.rate_per_km = rate
    incidents = [(fid, v) for fid, v in vals.items() if "reported_at" in v]
    chats = [(fid, v) for fid, v in vals.items() if "flags" in v and "idx" in v]
    if not segs:
        cert.predicates.append(Predicate("RD-1", "off-route segment exists", "case", "fail", [], "no off-route segment measured"))
        cert.allowed = ["no_action"]
        return cert
    cert.predicates.append(Predicate("RD-1", "off-route segment(s) exist", "case", "pass", list(segs), f"{len(segs)} segment(s)"))
    for fid, seg in segs.items():
        start = _ts(seg["start"])
        lo, hi = _segment_replaced_stretch(case, seg)
        # RD-4: an incident on the replaced stretch, reported before the segment started
        rd4 = [iid for iid, inc in incidents if _ts(inc["reported_at"]) < start and _incident_on_stretch(case, inc, lo, hi)]
        if rd4:
            cert.predicates.append(Predicate("RD-4", "(a) incident on the replaced stretch, reported before the detour", fid, "pass", rd4,
                                             f"incident within {NEAR_ROUTE_M} m of optimal km {lo:.1f}–{hi:.1f}"))
        else:
            cert.predicates.append(Predicate("RD-4", "(a) incident on the replaced stretch, reported before the detour", fid, "fail", [iid for iid, _ in incidents],
                                             "no qualifying incident (speed band alone does not exempt)"))
        # RD-5: a driver request + rider agreement before the segment start → scope is for the judge (moot if RD-4 settled it)
        agree = [cid for cid, c in chats if "agreement" in c["flags"] and c.get("from") == "rider" and _ts(c["ts"]) < start]
        req = [cid for cid, c in chats if "request" in c["flags"] and c.get("from") == "driver" and _ts(c["ts"]) < start]
        stop_req = [cid for cid, c in chats if "request" in c["flags"] and c.get("from") == "rider" and _ts(c["ts"]) < start]
        if rd4:
            cert.predicates.append(Predicate("RD-5", "consent scope", fid, "n/a", agree + req, "not needed: RD-4 already exempts this segment"))
            cert.predicates.append(Predicate("RD-3", "rider-requested stop", fid, "n/a", stop_req, "not needed: RD-4 already exempts this segment"))
        else:
            if agree and req:
                texts = "; ".join(f"{cid}: {table_text(table, cid)}" for cid in req + agree)
                cert.predicates.append(Predicate("RD-5", "rider agreed to a route change before the detour; scope of consent", fid, "judge", req + agree,
                                                 f"RULE: if the driver named a road/area/route before leaving and the rider agreed, this segment is exempt (exempt=true) "
                                                 f"unless it plainly goes somewhere other than what was named. Evidence — {texts}"))
            else:
                cert.predicates.append(Predicate("RD-5", "rider agreed to a route change before the detour", fid, "fail", agree + req, "no prior driver request + rider agreement"))
            if stop_req:
                stop_ids = [sid for sid, v in vals.items() if "duration_s" in v and "m_from_pickup" in v and seg["start"] <= v.get("start", "") <= seg["end"]]
                texts = "; ".join(f"{cid}: {table_text(table, cid)}" for cid in stop_req + stop_ids)
                cert.predicates.append(Predicate("RD-3", "rider-requested stop; whether it named this location", fid, "judge", stop_req + stop_ids,
                                                 f"RULE (RD-3(a)): if the rider NAMED a specific place and the car stopped there, the WHOLE segment driven to reach it is exempt "
                                                 f"(exempt=true: a rider-named stop is not a detour, its extra km are not refundable; only the waiting fee rules apply). "
                                                 f"If the rider named no place ('a 7-Eleven on the way'), the driver's choice of a far location is NOT exempt (exempt=false). Evidence — {texts}"))
            else:
                cert.predicates.append(Predicate("RD-3", "rider-requested stop", fid, "fail", [], "no rider stop request before the segment"))
        if rd4:
            cert.segments[fid] = {"exempt": True, "extra_km": seg["extra_km"], "why": f"RD-4 via {', '.join(rd4)}"}
        elif (agree and req) or stop_req:
            cert.segments[fid] = {"exempt": None, "extra_km": seg["extra_km"], "why": "judge decides RD-5/RD-3 scope"}
            cert.mechanical = False
        else:
            cert.segments[fid] = {"exempt": False, "extra_km": seg["extra_km"], "why": "no exemption candidate"}
    definite_bad = [f for f, s in cert.segments.items() if s["exempt"] is False]
    undecided = [f for f, s in cert.segments.items() if s["exempt"] is None]
    if not metered:
        cert.predicates.append(Predicate("RD-2", "metered service (detour km enters the fare)", "case", "fail", [], f"{case.trip.service_type} is a fixed fare"))
        cert.allowed = ["no_action"]
    elif definite_bad:
        cert.allowed = ["refund_partial"]
    elif undecided:
        cert.allowed = ["refund_partial", "no_action"]
    else:
        cert.allowed = ["no_action"]
    if metered and rate:
        cert.amount_formula = f"Σ extra_km of non-exempt segments × ${rate:.4f}/km (distance_fare ÷ distance_km), rounded to cents"
    drv = next((v for v in vals.values() if v.get("party") == "driver"), {})
    prior = drv.get("route_disputes_upheld_90d", 0) >= 1
    cert.predicates.append(Predicate("RD-6", "prior upheld route dispute in 90 d (repeated breach → flag_account)", "case",
                                     "pass" if prior else "fail", [f for f, v in vals.items() if v.get("party") == "driver"],
                                     f"route_disputes_upheld_90d = {drv.get('route_disputes_upheld_90d', 0)}"))
    # RD-6 needs the case UPHELD (≥1 non-exempt segment). Definite → known now; undecided → depends on the judge's findings.
    cert.flag_required = bool(prior) if definite_bad else (None if (undecided and prior) else False)
    cert.flag_conditional = bool(undecided and prior and not definite_bad)
    return cert


def expected_amount(cert: Certificate, findings: dict[str, bool]) -> Optional[float]:
    """Amount implied by the certificate once the judge's segment findings fill the undecided slots."""
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
    cert = Certificate(dispute_type="no_show", fee=cancel_fee(case), grace=grace_s(case))
    G, FEE, GM = cert.grace, cert.fee, cert.grace / 60
    cancel = next((v for v in vals.values() if "s_after_accept" in v), {})
    near = next(((f, v) for f, v in vals.items() if "nearest_m" in v), (None, {}))
    within = next(((f, v) for f, v in vals.items() if "within_200m_s" in v), (None, {}))
    here = next(((f, v) for f, v in vals.items() if "driver_pressed_here_at" in v), (None, {}))
    cancel_id = next((f for f, v in vals.items() if "s_after_accept" in v), None)
    by = cancel.get("cancelled_by")
    cert.predicates.append(Predicate("NS-0", "who cancelled", "case", "pass", [cancel_id] if cancel_id else [], f"cancelled_by = {by}"))
    if by == "rider":
        late = cancel.get("s_after_accept", 0) > G
        cert.predicates.append(Predicate("NS-4", f"rider cancelled more than {GM:g} min after matching", "case", "pass" if late else "fail",
                                         [cancel_id], f"{cancel.get('s_after_accept')} s after acceptance"))
        cert.allowed = ["no_action"] if late else ["refund_full"]
        cert.amount_formula = None if late else f"cancellation fee ${FEE:.2f}"
        cert.flag_required = False
        return cert
    # driver cancelled as rider no-show → NS-1 three elements
    i_ok = bool(here[1].get("driver_pressed_here_at"))
    d_tap = here[1].get("m_from_pickup_at_tap")
    ii_ok = d_tap is not None and d_tap <= PICKUP_RADIUS_M
    cont = here[1].get("within_200m_after_tap_s", 0) or 0
    iii_ok = cont > G
    auto = here[1].get("arrival_confirmed_by") == "platform_auto"
    cert.predicates.append(Predicate("NS-1", "(i) arrival confirmed: driver tapped I'm Here, or the platform auto-confirmed arrival", "case", "pass" if i_ok else "fail", [here[0]] if here[0] else [],
                                     (f"platform auto-arrival at " if auto else f"tapped at ") + f"{(here[1].get('driver_pressed_here_at') or '—')[11:19]}"))
    cert.predicates.append(Predicate("NS-1", f"(ii) within {PICKUP_RADIUS_M} m of pickup AT THE MOMENT of the tap", "case", "pass" if ii_ok else "fail",
                                     [x for x in (here[0], near[0]) if x], f"{d_tap if d_tap is not None else '—'} m from pickup when tapped (closest approach overall {near[1].get('nearest_m')} m)"))
    cert.predicates.append(Predicate("NS-1", f"(iii) stayed at the pickup > {GM:g} min after the tap, until cancelling", "case", "pass" if iii_ok else "fail",
                                     [here[0]] if here[0] else [], f"{cont} s continuously inside the radius after the tap"))
    if i_ok and ii_ok and iii_ok:
        cert.allowed = ["no_action"]; cert.flag_required = False
    else:
        cert.allowed = ["refund_full"]; cert.amount_formula = f"cancellation fee ${FEE:.2f}"
        cert.flag_required = bool(i_ok and not ii_ok)
        cert.predicates.append(Predicate("NS-2", "tapped I'm Here while not at pickup → flag_account", "case",
                                         "pass" if cert.flag_required else "fail", [x for x in (here[0], near[0]) if x], "fake arrival tap" if cert.flag_required else "no fake tap"))
    return cert


# --------------------------------------------------------------------------- safety

def evaluate_safety(case: Case, table: FactTable) -> Certificate:
    vals = _vals(table)
    cert = Certificate(dispute_type="safety")
    threats = [f for f, v in vals.items() if v.get("threat")]
    cert.predicates.append(Predicate("SAFE-1", "threat / intimidation language present", "case", "pass" if threats else "fail", threats,
                                     "threat keyword table (core/facts/tools.py)"))
    cert.allowed = ["escalate"]
    cert.flag_required = None
    return cert


def evaluate(case: Case, table: FactTable) -> Certificate:
    vals = _vals(table)
    if table.dispute_type == "safety" or any(v.get("threat") for v in vals.values()):
        return evaluate_safety(case, table)
    if table.dispute_type == "no_show":
        return evaluate_no_show(case, table)
    return evaluate_route(case, table)


# --------------------------------------------------------------------------- eligibility

def check_ruling(cert: Certificate, ruling: Ruling) -> tuple[bool, list[str]]:
    """Is the judge's ruling consistent with the certificate? (eligible_for_automation, reasons)."""
    reasons = []
    if ruling.ruling not in cert.allowed:
        reasons.append(f"ruling {ruling.ruling} not in allowed {cert.allowed}")
    if cert.dispute_type == "route_deviation" and cert.segments:
        findings = {sf.fact_id: sf.exempt for sf in ruling.segment_findings}
        for fid, s in cert.segments.items():
            if fid not in findings:
                reasons.append(f"judge gave no finding for segment {fid}")
            elif s["exempt"] is not None and findings[fid] != s["exempt"]:
                reasons.append(f"judge finding for {fid} ({'exempt' if findings[fid] else 'not exempt'}) contradicts code ({s['why']})")
        amt = expected_amount(cert, findings)
        if ruling.ruling == "refund_partial":
            if amt is None:
                reasons.append("amount undeterminable: a segment finding is missing")
            elif amt <= 0:
                reasons.append("refund_partial but every segment is exempt → amount would be 0")
            elif ruling.amount is None or abs(ruling.amount - amt) > 0.011:
                reasons.append(f"amount {ruling.amount} ≠ formula {amt:.2f}")
        if ruling.ruling == "no_action" and amt not in (None, 0.0):
            reasons.append(f"no_action but a non-exempt segment implies ${amt:.2f}")
    elif cert.dispute_type == "no_show" and ruling.ruling == "refund_full":
        if ruling.amount is None or abs(ruling.amount - cert.fee) > 0.011:
            reasons.append(f"amount {ruling.amount} ≠ cancellation fee {cert.fee}")
    flag_required = cert.flag_required
    if cert.flag_conditional and cert.dispute_type == "route_deviation":
        findings = {sf.fact_id: sf.exempt for sf in ruling.segment_findings}
        upheld = any((s["exempt"] if s["exempt"] is not None else findings.get(fid)) is False for fid, s in cert.segments.items())
        flag_required = upheld
    if flag_required is not None and ruling.ruling != "escalate":
        has_flag = bool(getattr(ruling, "flag_account", False))   # structured field only: free text never creates an account action
        if flag_required and not has_flag:
            reasons.append("flag_account required by the certificate but not recommended")
        if not flag_required and has_flag:
            reasons.append("flag_account recommended but no clause requires it")
    return (not reasons), reasons
