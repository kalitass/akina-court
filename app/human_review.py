"""Human review UI backend: the one question the court could not settle, the options code can price, and the person's decision.

    build_packet(record, case)       -> ReviewPacket   what the reviewer reads (question first), rebuilt from the stored run
    apply_decision(packet, decision) -> Ruling         adopt_option / own_judgment as a Ruling; amounts recomputed here
    record_decision(...)                               persist + feedback.record_override (precedent "human", queue resolved)
    request_evidence(...)                              persist the request + await_evidence: the case stays open

Only escalated cases reach a person (the "Needs a human" tab of web/ops.html): a run that was cleared automatically,
including one whose account flag is the only thing left for a person, gets no packet (NotReviewable).

The court's segment findings are scattered over Ruling.segment_findings, safety_concern, evidence_status and
eligibility.reasons, and its option amounts only exist in free text. Here the Certificate is recomputed from the stored
FactTable (policy_engine.evaluate) and every option amount comes from expected_amount with the other segments at their
final finding; a client never supplies an amount for an adopted option. Nothing is pre-selected: `lean` is set only when
a written rule requires one option, never from a model's preference.

The web/API layer is not part of the ruling (core/receipt.py CODE_FILES), so this module lives in app/ and the stored
receipts keep verifying. QueueItem.status (core/stretch/sla.py) has no "awaiting_evidence" value; an evidence request
keeps the queue item open with the new due time, and the review status reads "awaiting_evidence" from the request store.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr, field_validator

from core.notices import fallback_notices
from core.policy_engine import GOODWILL, TH_MANUAL, Certificate, evaluate, expected_amount
from core.schemas import Case, CaseRecord, Ruling, SegmentFinding
from core.stretch import feedback, precedent, sla
from core.stretch._util import RUNS_DIR, now, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
OPS_QUEUE_DIR = ROOT / "bench" / "results" / "court"     # the runs web/ops.html is generated from (bench/ops_page.py)
REVIEWS_NAME, EVIDENCE_NAME = "human_reviews.json", "evidence_requests.json"
MIN_REASON = 15                                          # own_judgment: characters of reason before it is a reason
SAFETY_VOCAB = "proposed"                                # the policy has no outcome vocabulary for a safety finding yet

Who = Literal["rider", "driver", "system"]


class NotReviewable(Exception):
    """The run was cleared automatically (or never ruled): nothing waits for a person."""


class DecisionError(ValueError):
    """A decision the server will not record; the message says what to fix."""


# ---------------------------------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    fact_id: str
    who: Who
    at: str                                       # "18:42" local time, or "after the trip" for a written statement
    text: str                                     # the words as recorded (a quote) or the fact sentence
    quote: bool                                   # True = verbatim words of a party


class ReviewOption(BaseModel):
    id: str                                       # segment: exempt | counts; safety: none | misconduct | threat_or_harassment | unsubstantiated;
                                                  # decision (trace): the outcome itself (refund_partial | refund_full | no_action)
    label: str
    detail: str
    finding: Optional[str] = None                 # segment finding this option records (exempt / counts)
    ground: Optional[str] = None                  # policy ground (core.schemas.Ground) the finding rests on
    clauses: list[str] = []
    ruling: str                                   # resulting action (refund_partial / no_action / ...)
    amount: Optional[float] = None                # computed by code (expected_amount); None = no money moves or not computable
    flag_account: bool = False
    requires_confirmation: bool = False           # an account action the reviewer must confirm a second time
    proposed: bool = False                        # True = vocabulary proposed by this page, not written policy
    lean: Optional[Literal["rule"]] = None        # set only when a written rule requires this option


class SideView(BaseModel):
    side: Literal["rider", "driver"]
    ground: Optional[str] = None                  # the ground the side ends on (rebuttal, else brief) for this question
    ground_brief: Optional[str] = None
    outcome: Optional[str] = None
    amount: Optional[float] = None
    line: str = ""                                # the side's first claim, one line
    weaknesses: list[str] = []                    # what the advocate admitted against its own side


class ReviewQuestion(BaseModel):
    id: str                                       # "seg:F3" | "safety" | "trace"
    kind: Literal["segment_scope", "safety", "decision"]   # decision: the case outcome itself (a stop no structured field carries)
    subject: str                                  # segment fact id or "case"
    title: str
    escalation_reasons: list[str]
    evidence: list[EvidenceItem]
    options: list[ReviewOption]
    adoptable: bool                               # False: the record cannot support any option; own judgment or more evidence
    vocabulary: Literal["policy", "proposed"] = "policy"
    sides: dict[str, SideView] = {}
    focus: Optional[dict] = None                  # {"start", "end"} ISO times the map zooms to


class SettledItem(BaseModel):
    subject: str
    label: str
    by: Literal["code", "judge"]                  # code = the certificate measured it; judge = found by the court and verified
    finding: Optional[str] = None
    amount: Optional[float] = None
    detail: str = ""


class EvidenceGapNote(BaseModel):
    status: str                                   # insufficient | unknown
    gap: str
    facts: list[str] = []


class EvidenceRequest(BaseModel):
    to: Literal["rider", "driver", "platform"]
    items: list[str] = Field(min_length=1)
    due_in_hours: int = Field(ge=1, le=168)
    on_timeout: Literal["decide_on_record", "close_no_action"]
    note: str = ""

    @field_validator("items")
    @classmethod
    def _items(cls, v: list[str]) -> list[str]:
        v = [x.strip() for x in v if x and x.strip()]
        if not v:
            raise ValueError("name at least one item to request")
        return v


class AmountOverride(BaseModel):
    amount: float = Field(ge=0)
    confirmed: bool = False                       # second confirmation: the amount differs from the formula


class HumanDecision(BaseModel):
    outcome: Literal["adopt_option", "own_judgment", "request_evidence"]
    reviewer: str = "reviewer"
    checked: bool = False                         # "I checked <fact> on the map and the quotes"
    choices: dict[str, str] = {}                  # adopt_option: question id -> option id
    findings: dict[str, str] = {}                 # own_judgment: question id -> option id (the finding, not its price)
    reason: str = ""
    cited_facts: list[str] = []
    amount: Optional[float] = None                # never accepted on adopt_option: the server computes it
    amount_override: Optional[AmountOverride] = None
    confirm_account_action: bool = False
    request: Optional[EvidenceRequest] = None
    note: str = ""


class ReviewPacket(BaseModel):
    case_id: str
    dispute_type: str
    filed_by: str
    filed_at: datetime
    statement: str
    trip_summary: str
    service_type: Optional[str] = None
    queue: str
    sla_hours: int
    due_at: Optional[datetime] = None
    status: Literal["open", "awaiting_evidence", "decided"] = "open"
    safety_concern: str
    safety_basis: list[str] = []
    escalation_reasons: list[str]
    questions: list[ReviewQuestion]
    settled: list[SettledItem]
    settled_amount: Optional[float] = None        # refund already fixed by code / the court, outside the open question
    evidence_gap: Optional[EvidenceGapNote] = None
    basis: list[str] = []                         # fact ids the open question rests on
    sides: dict[str, SideView] = {}
    context: list[str] = []                       # fare and 90-day history fact ids
    facts: dict[str, dict] = {}                   # id -> {source, text}
    allowed: list[str] = []
    links: dict[str, str] = {}
    pending_request: Optional[dict] = None
    decision: Optional[dict] = None

    _cert: Optional[Certificate] = PrivateAttr(default=None)
    _record: Optional[CaseRecord] = PrivateAttr(default=None)


# ---------------------------------------------------------------------------------------------------------------------
# which runs reach a person
# ---------------------------------------------------------------------------------------------------------------------

def auto_cleared(record: CaseRecord) -> bool:
    """Same rule as bench/ops_page.py: cleared = the certificate allowed automation and the ruling did not escalate."""
    r = record.ruling
    return r is not None and bool((record.eligibility or {}).get("auto")) and not r.escalate


@lru_cache(maxsize=4)
def ops_queue_ids(court_dir: Path = OPS_QUEUE_DIR) -> tuple[str, ...]:
    """Case ids on the ops page's "Needs a human" tab: stored court runs that ran and were not cleared automatically.
    Cached: the benchmark's stored runs do not change while the service runs."""
    out = []
    for p in sorted(court_dir.glob("B-*.record.json")):
        if re.search(r"\.r\d+\.record\.json$", p.name):
            continue
        run = read_json(court_dir / p.name.replace(".record.json", ".json"), {})
        if not run.get("ok", True):
            continue
        rec = CaseRecord.load(p)
        if rec.ruling is not None and not auto_cleared(rec):
            out.append(rec.case_id)
    return tuple(out)


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------

QUOTE = re.compile(r"[“\"](.+)[”\"]", re.S)
FID = re.compile(r"\bF\d+\b")


def _hm(ts: Optional[str]) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M")
    except ValueError:
        return ""


def _evidence(record: CaseRecord, fid: str) -> Optional[EvidenceItem]:
    f = next((x for x in record.facts.facts if x.id == fid), None)
    if f is None:
        return None
    v = f.value or {}
    m = QUOTE.search(f.text) if f.source == "chat" else None
    who = v.get("from") if v.get("from") in ("rider", "driver") else "system"
    at = "after the trip" if v.get("statement") else _hm(v.get("ts") or v.get("start") or v.get("at"))
    return EvidenceItem(fact_id=fid, who=who, at=at, text=m.group(1) if m else f.text, quote=bool(m))


def _order(item: EvidenceItem, record: CaseRecord) -> str:
    v = next((x.value or {} for x in record.facts.facts if x.id == item.fact_id), {})
    return "9" if v.get("statement") else (v.get("ts") or v.get("start") or v.get("at") or "8")


def _items(record: CaseRecord, ids: list[str], limit: int = 5) -> list[EvidenceItem]:
    seen, out = set(), []
    for fid in ids:
        if fid in seen:
            continue
        seen.add(fid)
        e = _evidence(record, fid)
        if e is not None:
            out.append(e)
    return sorted(out, key=lambda e: _order(e, record))[:limit]


def _vals(record: CaseRecord) -> dict[str, dict]:
    return {f.id: (f.value or {}) for f in record.facts.facts}


def _sides(record: CaseRecord, subject: Optional[str] = None) -> dict[str, SideView]:
    out = {}
    for side in ("rider", "driver"):
        b, r = record.briefs.get(side), record.rebuttals.get(side)
        if b is None:
            continue
        gb = b.segment_grounds.get(subject) if subject else None
        gr = (r.segment_grounds.get(subject) if (r and subject) else None) or gb
        ask = (r.revised_outcome if r and r.revised_outcome else None) or b.requested_outcome
        line = b.claims[0].assertion if b.claims else ""
        out[side] = SideView(side=side, ground=gr, ground_brief=gb, outcome=ask.action, amount=ask.amount,
                             line=line if len(line) <= 220 else line[:219].rstrip() + "…", weaknesses=list(b.weaknesses))
    return out


def _queue(record: CaseRecord) -> sla.Route:
    return sla.route(record.ruling, record.facts.dispute_type, eligibility=record.eligibility)


def _ruled_at(record: CaseRecord) -> Optional[datetime]:
    return record.events[-1].ts if record.events else None


def _prior_route_flag(record: CaseRecord) -> bool:
    drv = next((v for v in _vals(record).values() if v.get("party") == "driver"), {})
    return drv.get("route_disputes_upheld_90d", 0) >= 1


def _money(a: Optional[float]) -> str:
    return "no amount" if a is None else f"${a:.2f}"


# ---------------------------------------------------------------------------------------------------------------------
# packet
# ---------------------------------------------------------------------------------------------------------------------

def _final_findings(record: CaseRecord, cert: Certificate) -> dict[str, Optional[bool]]:
    """Segment fact id -> exempt True/False as settled (code first, then the court's verified finding); None = open."""
    judge = {sf.fact_id: sf.exempt for sf in record.ruling.segment_findings}
    return {fid: (sg["exempt"] if sg["exempt"] is not None else judge.get(fid)) for fid, sg in cert.segments.items()}


def _route_outcome(cert: Certificate, findings: dict[str, Optional[bool]], prior: bool) -> tuple[str, Optional[float], bool]:
    """(ruling, amount, flag_account) once every segment has a finding. Fixed fare: no amount moves."""
    amount = expected_amount(cert, findings)
    upheld = any(v is False for v in findings.values())
    flag = bool(prior and upheld)
    if cert.rate_per_km is None:
        return "no_action", None, flag
    return ("refund_partial" if amount and amount > 0 else "no_action"), amount, flag      # metered: 0.0 is a computed amount


def _segment_question(record: CaseRecord, cert: Certificate, sf: SegmentFinding, final: dict, prior: bool) -> ReviewQuestion:
    fid, sg, v = sf.fact_id, cert.segments.get(sf.fact_id, {}), _vals(record).get(sf.fact_id, {})
    t0, t1, km = _hm(v.get("start")), _hm(v.get("end")), float(v.get("extra_km") or sg.get("extra_km") or 0)
    named = sf.ground in ("named_road_untied", "named_road_tied", "named_road_elsewhere")
    head = f"{fid} · {t0}–{t1} (+{km:.2f} km): "
    title = head + ("was it driven on the road the rider agreed to? Nothing on record ties it to that road." if named
                    else f"does the rider's agreement before {t0} cover this segment?")
    opts = []
    for oid, exempt in (("exempt", True), ("counts", False)):
        fx = dict(final); fx[fid] = exempt
        ruling, amount, flag = _route_outcome(cert, fx, prior)
        open_other = [k for k, x in fx.items() if x is None]
        money = (f"refund {_money(amount)}" if cert.rate_per_km is not None and not open_other
                 else "no refund (fixed fare)" if cert.rate_per_km is None else f"amount depends on {', '.join(open_other)}")
        if exempt:
            ground = "named_road_tied" if named else ("rider_named_stop" if sf.ground == "rider_named_stop" else "general_route_consent")
            label = "Exempt: the rider's agreement covers it" if not named else "Exempt: driven on the agreed road"
            detail = f"{fid} is excused under RD-5; {money} with the other segments as settled."
            clauses = ["RD-5"] + (["RD-3"] if sg.get("stops") else [])
        else:
            ground = "named_road_elsewhere" if named else "scope_other"
            label = "Counts: not covered by the agreement" if not named else "Counts: not the agreed road"
            detail = f"{fid} is not excused; {money} with the other segments as settled" + ("; RD-6 adds an account flag (prior upheld route dispute)." if flag else ".")
            clauses = ["RD-5", "RD-2"] + (["RD-6"] if flag else [])
        opts.append(ReviewOption(id=oid, label=label, detail=detail, finding="exempt" if exempt else "counts", ground=ground,
                                 clauses=clauses, ruling=ruling, amount=amount, flag_account=flag))
    ids = list(sf.basis) + [fid] + [k for k, x in _vals(record).items() if x.get("statement")]
    ids += [k for k, x in _vals(record).items() if "idx" in x and x.get("ts") and v.get("start") and x["ts"] < v["start"]]
    why = [sf.reason] + ([record.ruling.escalation_reason] if record.ruling.escalation_reason and fid not in (record.ruling.escalation_reason or "") else [])
    return ReviewQuestion(id=f"seg:{fid}", kind="segment_scope", subject=fid, title=title, escalation_reasons=why,
                          evidence=_items(record, ids), options=opts, adoptable=record.ruling.evidence_status != "insufficient",
                          sides=_sides(record, fid), focus={"start": v.get("start"), "end": v.get("end")})


def _accused(record: CaseRecord) -> str:
    vals = _vals(record)
    if record.facts.dispute_type != "safety":
        for fid in record.ruling.safety_basis:
            who = vals.get(fid, {}).get("from")
            if who in ("rider", "driver") and "idx" in vals.get(fid, {}):
                return who
    return "driver" if record.dispute.filed_by == "rider" else "rider"


def _safety_question(record: CaseRecord, base: tuple[str, Optional[float]], gap: Optional[EvidenceGapNote]) -> ReviewQuestion:
    r, who = record.ruling, _accused(record)
    ruling, amount = base
    money = f"; the settled {_money(amount)} refund still issues" if amount else ""
    clauses = [c for c in ("SAFE-1", "SAFE-2") if c in r.cited_policy] or ["SAFE-1"]
    spec = (("none", f"No safety issue: the {who}'s words or driving were not a threat", "none", False),
            ("misconduct", f"Misconduct by the {who}, not a threat (recorded, no account action)", "confirmed", False),
            ("threat_or_harassment", f"Threat, harassment or danger by the {who}: account flag", "confirmed", True),
            ("unsubstantiated", "Cannot be established either way on this record", "suspected", False))
    opts = [ReviewOption(id=oid, label=label, detail=f"Recorded as safety_concern = {sc}" + (" with flag_account" if flag else "") + money + ".",
                         clauses=clauses, ruling=ruling, amount=amount, flag_account=flag, requires_confirmation=flag, proposed=True)
            for oid, label, sc, flag in spec]
    ids = list(r.safety_basis) + (gap.facts if gap else []) + [k for k, x in _vals(record).items() if x.get("statement") or x.get("keyword_hint")]
    ids += [k for k, x in _vals(record).items() if "idx" in x]           # every message, so the reviewer reads them in order
    title = (f"Safety: did the {who} threaten, harass or endanger the other party?"
             + (" The record holds no account of what happened." if gap and gap.status == "insufficient" else ""))
    why = [x for x in (r.escalation_reason, r.recommended_action) if x]          # the evidence gap has its own note
    times = [e for e in (_vals(record).get(f, {}).get("ts") for f in r.safety_basis) if e]
    return ReviewQuestion(id="safety", kind="safety", subject="case", title=title, escalation_reasons=why or ["safety concern recorded by the court"],
                          evidence=_items(record, ids), options=opts, adoptable=not (gap and gap.status == "insufficient"),
                          vocabulary=SAFETY_VOCAB, sides=_sides(record),
                          focus={"start": min(times), "end": max(times)} if times else None)


TRACE_FALLBACK = {"no_show": ["refund_full", "no_action"], "fare_dispute": ["refund_partial", "no_action"],
                  "route_deviation": ["refund_partial", "no_action"]}      # outcomes when the certificate allows only escalate
THRESHOLD = re.compile(r"\bTH-[13]\b")


def _trace_outcomes(cert: Certificate) -> list[str]:
    rest = [a for a in cert.allowed if a != "escalate"] or TRACE_FALLBACK.get(cert.dispute_type, [])
    return sorted(rest, key=lambda a: a == "no_action")                      # a refund first, then no refund


def _trace_amount(cert: Certificate, ruling: str, final: dict) -> Optional[float]:
    """The amount code computes for an outcome picked on the trace question (never the client's)."""
    if ruling == "refund_full":
        return cert.amount if cert.amount is not None else cert.fee
    if ruling == "refund_partial":
        if cert.dispute_type == "route_deviation" and cert.segments and cert.rate_per_km is not None and all(x is not None for x in final.values()):
            return expected_amount(cert, final)
        return cert.amount
    return None


def _trace_question(record: CaseRecord, cert: Certificate, final: dict, gap: Optional[EvidenceGapNote]) -> ReviewQuestion:
    """Escalated on a ground no segment or safety question carries: an amount above the TH-1 limit, a TH-3 fraud flag, a
    record with a hole (TH-4). The options are the case outcomes themselves, priced by code. A threshold stop is what the
    reviewer is there to approve, so its options can be adopted; a record that cannot support any outcome cannot."""
    r = record.ruling
    why = list((record.eligibility or {}).get("reasons") or [r.escalation_reason or "escalated"])
    insufficient = r.evidence_status == "insufficient" or bool(cert.insufficient)
    threshold = any(THRESHOLD.search(x) for x in why)
    adoptable = threshold and not insufficient
    if r.recommended_action:
        why.append(f"What the court proposed (not carried out; you decide): {r.recommended_action}")
    stop = ["TH-4"] if insufficient else sorted({m.group(0) for x in why for m in THRESHOLD.finditer(x)})
    fee_word = f"the ${cert.fee:.2f} cancellation fee"
    opts = []
    for ruling in _trace_outcomes(cert):
        amount = _trace_amount(cert, ruling, final)
        flag = bool(cert.flag_required and ruling == "no_action")
        if cert.dispute_type == "no_show":
            label, clauses = (("Void the fee: refund it to the rider", ["NS-2"]) if ruling == "refund_full"
                              else ("The fee stands: the driver waited at the pickup long enough", ["NS-1"]))
            detail = (f"Refund {fee_word} (NS-2)" if ruling == "refund_full" else f"Keep {fee_word} (NS-1)")
            if cert.goodwill_required and ruling == "refund_full":
                detail += f", plus the ${GOODWILL:.2f} goodwill credit (NS-8)"
                clauses.append("NS-8")
        elif cert.dispute_type == "fare_dispute":
            label, clauses = (("Approve the refund of the surge part", ["SURGE-2", "SURGE-3"]) if ruling == "refund_partial"
                              else ("No refund: the higher fare stands", ["SURGE-1"]))
            detail = (f"Refund {_money(amount)}" + (f": {cert.amount_formula}" if cert.amount_formula else "") + " (SURGE-2)"
                      if ruling == "refund_partial" else "The in-app notice met SURGE-1, so the higher fare stands")
        else:
            label, clauses = (("Refund the extra distance", ["RD-2"]) if ruling == "refund_partial" else ("No refund", ["RD-1"]))
            detail = (f"Refund {_money(amount)} (RD-2)" if ruling == "refund_partial" and amount is not None
                      else "Refund the counted extra distance (RD-2); the record does not give an amount" if ruling == "refund_partial"
                      else "No refund is due")
        if flag:
            detail += "; the policy adds an account flag"
        opts.append(ReviewOption(id=ruling, label=label, detail=detail + ".", clauses=clauses + stop, ruling=ruling, amount=amount,
                                 flag_account=flag, requires_confirmation=flag))
    if insufficient:
        title = "The record has a gap the court could not get past: decide what it supports, or ask for the missing record"
    elif threshold and any(x.startswith("TH-1") and "above" in x for x in why):
        amt = next((o.amount for o in opts if o.amount), None)
        title = f"{_money(amt) if amt else 'The refund'} is above the ${TH_MANUAL:.0f} a refund can be approved without a person: approve it or not"
    elif threshold:
        title = "The system may not act on its own here (a fraud flag or a confidence check): approve the outcome or not"
    else:
        title = "The policy check stopped this ruling: decide it on the record"
    ids = list(r.cited_facts) + (gap.facts if gap else [])
    return ReviewQuestion(id="trace", kind="decision", subject="case", title=title, escalation_reasons=why,
                          evidence=_items(record, ids), options=opts, adoptable=adoptable, sides=_sides(record))


def _settled(record: CaseRecord, cert: Certificate, prior: bool) -> list[SettledItem]:
    out, vals = [], _vals(record)
    judge = {sf.fact_id: sf for sf in record.ruling.segment_findings}
    for fid, sg in cert.segments.items():
        v = vals.get(fid, {})
        lab = f"{fid} · {_hm(v.get('start'))}–{_hm(v.get('end'))} · +{sg['extra_km']:.2f} km"
        amt = round(sg["extra_km"] * cert.rate_per_km + 1e-9, 2) if cert.rate_per_km else None
        if sg["exempt"] is not None:
            out.append(SettledItem(subject=fid, label=lab, by="code", finding="exempt" if sg["exempt"] else "counts",
                                   amount=None if sg["exempt"] else amt, detail=sg.get("why", "")))
        elif fid in judge and judge[fid].finding != "undetermined":
            f = judge[fid]
            out.append(SettledItem(subject=fid, label=lab, by="judge", finding=f.finding, amount=amt if f.finding == "counts" else None,
                                   detail=f"{f.ground}: {f.reason}"))
    if cert.dispute_type == "route_deviation" and cert.segments:
        drv = next((v for v in vals.values() if v.get("party") == "driver"), {})
        n = drv.get("route_disputes_upheld_90d", 0)
        out.append(SettledItem(subject="RD-6", label="Account flag (repeat route breach)", by="code", finding="flag if a segment counts" if prior else "no flag",
                               detail=f"driver route_disputes_upheld_90d = {n}" + (": a counted segment adds flag_account" if prior else ": no account action")))
    if cert.dispute_type == "no_show" and cert.mechanical:
        rest = [a for a in cert.allowed if a != "escalate"]
        if len(rest) == 1:
            out.append(SettledItem(subject="NS", label="No-show outcome", by="code", finding=rest[0],
                                   amount=cert.fee if rest[0] == "refund_full" else None,
                                   detail=f"cancellation fee ${cert.fee:.2f} " + ("refunded" if rest[0] == "refund_full" else "stands")))
    if record.ruling.safety_concern == "none":
        out.append(SettledItem(subject="SAFE-1", label="Safety screen", by="judge", finding="none", detail="the court read every message and found nothing"))
    return out


def _base_outcome(record: CaseRecord, cert: Certificate, final: dict, prior: bool) -> tuple[str, Optional[float]]:
    """The outcome outside a safety question: what code and the court already fixed (no money for a safety complaint)."""
    if cert.dispute_type == "route_deviation" and cert.segments and all(x is not None for x in final.values()):
        ruling, amount, _ = _route_outcome(cert, final, prior)
        return ruling, amount
    rest = [a for a in cert.allowed if a != "escalate"]
    if cert.dispute_type == "no_show" and len(rest) == 1:
        return rest[0], (cert.fee if rest[0] == "refund_full" else None)
    return "no_action", None


def build_packet(record: CaseRecord, case: Case) -> ReviewPacket:
    """Everything the human review UI shows for one escalated run. Raises NotReviewable for a run cleared automatically."""
    r = record.ruling
    if r is None or auto_cleared(record):
        raise NotReviewable(f"{record.case_id} was cleared automatically; no human review")
    cert = evaluate(case, record.facts)
    prior = _prior_route_flag(record)
    final = _final_findings(record, cert)
    gap = None
    if r.evidence_status != "sufficient":
        gap = EvidenceGapNote(status=r.evidence_status, gap=r.evidence_gap or "the court could not tell whether the record settles the question",
                              facts=sorted(set(FID.findall(r.evidence_gap or ""))) or [])
    questions = [_segment_question(record, cert, sf, final, prior) for sf in r.segment_findings if sf.finding == "undetermined"]
    base = _base_outcome(record, cert, final, prior)
    if r.safety_concern in ("suspected", "confirmed") or record.facts.dispute_type == "safety":
        questions.append(_safety_question(record, base, gap))
    if not questions:      # escalated on a ground no structured field carries (TH-1 limit, TH-3 flag, a hole in the record)
        questions.append(_trace_question(record, cert, final, gap))
    route = _queue(record)
    at = _ruled_at(record)
    settled = _settled(record, cert, prior)
    if cert.dispute_type == "route_deviation" and cert.segments and cert.rate_per_km is not None:
        # RD-2: (deviation − km of exempt segments) × rate, tolerance after exemptions. A segment the court did not settle is
        # taken as exempt here, so the figure is what is due whatever the open question decides
        judged = {sf.fact_id: sf.exempt for sf in r.segment_findings if sf.finding != "undetermined"}
        fill = {fid: (judged.get(fid, True) if sg["exempt"] is None else sg["exempt"]) for fid, sg in cert.segments.items()}
        settled_amount = expected_amount(cert, fill) or None
    else:
        settled_amount = round(sum(s.amount for s in settled if s.amount and s.subject.startswith("F")), 2) or None
    why = (record.eligibility or {}).get("reasons") or [x for x in (r.escalation_reason,) if x]
    basis = sorted({e.fact_id for q in questions for e in q.evidence}, key=lambda x: int(x[1:]))
    ctx = [f.id for f in record.facts.facts if (f.value or {}).get("party") or ("total" in (f.value or {}) and "base_fare" in (f.value or {}))]
    links = {"court": f"/replay.html?case={record.case_id}&phase=court", "trip": f"/replay.html?case={record.case_id}",
             "facts": f"/facts.html?case={record.case_id}", "policy": "/policy.html", "receipt": f"/receipt.html?run={record.case_id}"}
    p = ReviewPacket(case_id=record.case_id, dispute_type=record.facts.dispute_type, filed_by=record.dispute.filed_by,
                     filed_at=record.dispute.filed_at, statement=record.dispute.statement,
                     trip_summary=(record.trip_summary or {}).get("text", ""), service_type=case.trip.service_type,
                     queue=route.queue, sla_hours=route.sla_hours, due_at=(at + timedelta(hours=route.sla_hours)) if at else None,
                     safety_concern=r.safety_concern, safety_basis=list(r.safety_basis), escalation_reasons=why, questions=questions,
                     settled=settled, settled_amount=settled_amount, evidence_gap=gap, basis=basis, sides=_sides(record), context=ctx,
                     facts={f.id: {"source": f.source, "text": f.text} for f in record.facts.facts}, allowed=list(cert.allowed), links=links)
    p._cert, p._record = cert, record
    return p


# ---------------------------------------------------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------------------------------------------------

def _pick(packet: ReviewPacket, picks: dict[str, str], what: str, adopt: bool) -> dict[str, ReviewOption]:
    out = {}
    for q in packet.questions:
        oid = picks.get(q.id)
        if oid is None:
            raise DecisionError(f"{what}: choose an option for {q.id} ({q.title})")
        if adopt and not q.adoptable:
            raise DecisionError(f"{q.id}: the record cannot support a predefined option here ({packet.evidence_gap.gap if packet.evidence_gap else 'no adoptable option'}); write your own judgment or request evidence")
        opt = next((o for o in q.options if o.id == oid), None)
        if opt is None:
            raise DecisionError(f"{q.id}: unknown option {oid!r} (allowed: {', '.join(o.id for o in q.options) or 'none'})")
        out[q.id] = opt
    extra = set(picks) - {q.id for q in packet.questions}
    if extra:
        raise DecisionError(f"unknown question id(s): {', '.join(sorted(extra))}")
    return out


def _combine(packet: ReviewPacket, picked: dict[str, ReviewOption]) -> tuple[str, Optional[float], bool, dict[str, bool]]:
    """Recompute the outcome from every picked finding together (never from the option cards' amounts)."""
    cert, rec = packet._cert, packet._record
    prior = _prior_route_flag(rec)
    findings = _final_findings(rec, cert)
    seg = {q.subject: picked[q.id].finding == "exempt" for q in packet.questions if q.kind == "segment_scope"}
    findings.update(seg)
    if cert.dispute_type == "route_deviation" and cert.segments:
        if any(x is None for x in findings.values()):
            raise DecisionError("a segment is still open; every undetermined segment needs a finding")
        ruling, amount, flag = _route_outcome(cert, findings, prior)
    elif "trace" in picked:                      # the outcome itself was picked; its amount is recomputed here
        ruling = picked["trace"].ruling
        amount = _trace_amount(cert, ruling, findings)
        flag = False
    else:
        ruling, amount = _base_outcome(rec, cert, findings, prior)
        flag = False
    flag = flag or any(o.flag_account for q, o in picked.items() if q in ("safety", "trace"))
    return ruling, amount, flag, seg


def apply_decision(packet: ReviewPacket, decision: HumanDecision) -> Ruling:
    """adopt_option / own_judgment as a Ruling. Amounts are recomputed here; cited fact ids must exist."""
    if packet._cert is None or packet._record is None:
        raise DecisionError("packet was not built on this server (build_packet)")
    if decision.outcome == "request_evidence":
        raise DecisionError("request_evidence produces no ruling; use request_evidence()")
    if not decision.checked:
        raise DecisionError("confirm that you checked the segment on the map and the quoted messages")
    rec, ids = packet._record, set(packet.facts)
    if decision.outcome == "adopt_option":
        if decision.amount is not None or decision.amount_override is not None:
            raise DecisionError("an adopted option's amount is computed by code; do not send one")
        picked = _pick(packet, decision.choices, "adopt_option", adopt=True)
        reason = decision.reason.strip() or "; ".join(f"{q}: {o.label}" for q, o in picked.items())
        cited = list(dict.fromkeys(decision.cited_facts or packet.basis))
    else:
        picked = _pick(packet, decision.findings, "own_judgment", adopt=False)
        reason = decision.reason.strip()
        if len(reason) < MIN_REASON:
            raise DecisionError(f"own_judgment needs a reason of at least {MIN_REASON} characters")
        if not decision.cited_facts:
            raise DecisionError("own_judgment must cite at least one fact id")
        cited = list(dict.fromkeys(decision.cited_facts))
    bad = [f for f in cited if f not in ids]
    if bad:
        raise DecisionError(f"unknown fact id(s): {', '.join(bad)}")
    ruling, amount, flag, seg = _combine(packet, picked)
    formula = amount
    if decision.outcome == "own_judgment" and decision.amount_override is not None:
        manual = round(decision.amount_override.amount, 2)
        if (formula is None or abs(manual - formula) > 0.005) and not decision.amount_override.confirmed:
            raise DecisionError(f"manual amount ${manual:.2f} differs from the formula ({_money(formula)}): confirm it a second time")
        amount = manual or None
        same = formula is not None and abs(manual - formula) <= 0.005
        ruling = (ruling if same and ruling.startswith("refund") else "refund_partial") if amount else "no_action"
    if decision.amount is not None and decision.outcome == "own_judgment":
        raise DecisionError("send a manual amount as amount_override {amount, confirmed}")
    if ruling == "no_action":
        amount = None                            # a ruling that refunds nothing carries no amount (0.00 stays the formula's)
    confirm_needed = any(o.requires_confirmation and o.flag_account for o in picked.values())
    if confirm_needed and not decision.confirm_account_action:
        raise DecisionError("this outcome refers an account for review: confirm the account action a second time")
    if decision.outcome == "adopt_option" and packet.allowed != ["escalate"] and "safety" not in picked and ruling not in packet.allowed:
        raise DecisionError(f"{ruling} is not an outcome the policy allows here ({', '.join(packet.allowed)})")
    # carry every segment finding into the ruling, the reviewer's in place of the undetermined ones
    findings = []
    for sf in rec.ruling.segment_findings:
        q = next((q for q in packet.questions if q.subject == sf.fact_id), None)
        if q is None:
            findings.append(sf)
            continue
        o = picked[q.id]
        findings.append(SegmentFinding(fact_id=sf.fact_id, finding=o.finding, ground=o.ground or "other", basis=list(sf.basis),
                                       reason=f"Human reviewer ({decision.reviewer}): {reason}"))
    safety = rec.ruling.safety_concern if rec.ruling.safety_concern != "unscreened" else "none"
    if "safety" in picked:
        safety = {"none": "none", "misconduct": "confirmed", "threat_or_harassment": "confirmed", "unsubstantiated": "suspected"}[picked["safety"].id]
    clauses = list(dict.fromkeys(c for o in picked.values() for c in o.clauses))
    what = "; ".join(f"{q}: {o.label}" for q, o in picked.items())
    action = f"Human review ({decision.outcome}): {what}; {ruling} {_money(amount)}" + (" + flag_account" if flag else "")
    if decision.outcome == "own_judgment" and decision.amount_override is not None:
        action += f" (manual amount; formula {_money(formula)})"
    goodwill = GOODWILL if ("trace" in picked and packet._cert.goodwill_required and ruling == "refund_full") else None
    return Ruling(ruling=ruling, amount=amount, recommended_action=action, confidence=1.0, reasoning=reason, cited_facts=cited,
                  cited_policy=clauses, flag_account=flag, segment_findings=findings, safety_concern=safety, goodwill_credit=goodwill,
                  safety_basis=list(rec.ruling.safety_basis), evidence_status="sufficient", evidence_gap=None, escalate=False)


def formula_amount(packet: ReviewPacket, decision: HumanDecision) -> Optional[float]:
    """The amount code computes for the decision's findings (what a manual amount is compared with)."""
    picks = decision.choices if decision.outcome == "adopt_option" else decision.findings
    return _combine(packet, _pick(packet, picks, decision.outcome, adopt=False))[1]


def notice_preview(packet: ReviewPacket, decision: HumanDecision, ruling: Optional[Ruling] = None) -> dict[str, str]:
    """What each party would be told. A ruled outcome uses the template notices; an evidence request names what is asked."""
    if decision.outcome == "request_evidence":
        req = decision.request
        if req is None:
            raise DecisionError("request_evidence needs a request {to, items, due_in_hours, on_timeout}")
        due = f"within {req.due_in_hours} h"
        ask = "; ".join(req.items)
        after = ("the reviewer decides on the record as it stands" if req.on_timeout == "decide_on_record" else "the dispute is closed with no change")
        out = {}
        for side in ("rider", "driver"):
            if req.to == side:
                out[side] = f"Your dispute on trip {packet.case_id} is with a Ryde reviewer, who needs more information from you {due}: {ask}. If nothing arrives, {after}."
            else:
                out[side] = f"The dispute on trip {packet.case_id} is still under review; no decision has been made and nothing has changed yet."
        return out
    rider, driver = fallback_notices(ruling or apply_decision(packet, decision))
    return {"rider": rider, "driver": driver}


# ---------------------------------------------------------------------------------------------------------------------
# stores (runs/human_reviews.json, runs/evidence_requests.json; the queue file is core/stretch/sla.py's)
# ---------------------------------------------------------------------------------------------------------------------

def _load(name: str, runs_dir: Path) -> list[dict]:
    return read_json(runs_dir / name, [])


def latest(case_id: str, runs_dir: Path = RUNS_DIR) -> tuple[Optional[dict], Optional[dict]]:
    """(last decision, last evidence request) for the case."""
    d = [x for x in _load(REVIEWS_NAME, runs_dir) if x.get("case_id") == case_id]
    e = [x for x in _load(EVIDENCE_NAME, runs_dir) if x.get("case_id") == case_id]
    return (d[-1] if d else None), (e[-1] if e else None)


def review_status(case_id: str, runs_dir: Path = RUNS_DIR) -> str:
    d, e = latest(case_id, runs_dir)
    if d and (not e or d["recorded_at"] >= e["requested_at"]):
        return "decided"
    return "awaiting_evidence" if e else "open"


def await_evidence(case_id: str, request: EvidenceRequest, runs_dir: Path = RUNS_DIR, route: Optional[sla.Route] = None) -> sla.QueueItem:
    """Keep the case's queue item open and move its due time to the evidence deadline (enqueue it first if absent).
    The status stays "open" (sla.QueueItem has no other open state); the note says why it is waiting."""
    items = sla.list_queue(runs_dir)
    hit = next((i for i in items if i.case_id == case_id), None)
    if hit is None:
        hit = sla.enqueue(case_id, route or sla._route("review_24h", "escalated: human review"), runs_dir)
        items = sla.list_queue(runs_dir)
    t = now()
    upd = hit.model_copy(update={"status": "open", "resolved_at": None, "resolved_by": None, "due_at": t + timedelta(hours=request.due_in_hours),
                                 "note": f"awaiting_evidence from {request.to}: {'; '.join(request.items)} (on timeout: {request.on_timeout})"})
    sla._save([upd if i.case_id == case_id else i for i in items], runs_dir)
    return upd


def request_evidence(packet: ReviewPacket, decision: HumanDecision, runs_dir: Path = RUNS_DIR) -> dict:
    """Persist the request and keep the case open; nothing is ruled, nothing is resolved."""
    if decision.outcome != "request_evidence" or decision.request is None:
        raise DecisionError("request_evidence needs a request {to, items, due_in_hours, on_timeout}")
    if not decision.checked:
        raise DecisionError("confirm that you checked the segment on the map and the quoted messages")
    req = decision.request
    t = now()
    entry = {"case_id": packet.case_id, "reviewer": decision.reviewer, "requested_at": t.isoformat(), "status": "awaiting_evidence",
             "due_at": (t + timedelta(hours=req.due_in_hours)).isoformat(), "request": req.model_dump(), "note": decision.note,
             "notices": notice_preview(packet, decision)}
    write_json(runs_dir / EVIDENCE_NAME, _load(EVIDENCE_NAME, runs_dir) + [entry])
    item = await_evidence(packet.case_id, req, runs_dir, sla.Route(queue=packet.queue, sla_hours=packet.sla_hours, reason="escalated: human review",
                                                                   priority=sla.PRIORITY.get(packet.queue, 1)))
    return {"status": "awaiting_evidence", "request": entry, "queue_item": item.model_dump(mode="json")}


def _override(packet: ReviewPacket, ruling: Ruling, reviewer: str, note: str, runs_dir: Path) -> feedback.Override:
    """feedback.record_override, except for a dispute type the precedent store has no features for (a surge fare dispute,
    core/stretch/precedent.py FEATURES): the override is written and the queue item resolved, no precedent is indexed."""
    rec = packet._record
    if rec.facts.dispute_type in precedent.FEATURES:
        return feedback.record_override(packet.case_id, ruling, reviewer, note, runs_dir, rec)
    auto = rec.ruling
    ov = feedback.Override(case_id=packet.case_id, dispute_type=rec.facts.dispute_type, auto_ruling=auto.ruling if auto else None,
                           auto_amount=auto.amount if auto else None, human_ruling=ruling.ruling, human_amount=ruling.amount,
                           changed_outcome=auto is None or auto.ruling != ruling.ruling or (auto.amount or 0) != (ruling.amount or 0),
                           reviewer=reviewer, note=note, recorded_at=now())
    write_json(feedback.overrides_path(runs_dir), [o.model_dump(mode="json") for o in feedback.load(runs_dir)] + [ov.model_dump(mode="json")])
    sla.resolve(packet.case_id, reviewer, note or f"override: {ruling.ruling}", runs_dir)
    return ov


def record_decision(packet: ReviewPacket, decision: HumanDecision, runs_dir: Path = RUNS_DIR) -> dict:
    """adopt_option / own_judgment: the ruling goes through feedback.record_override (overrides.json, precedent re-indexed
    as "human", queue item resolved) and the full decision is kept in runs/human_reviews.json."""
    ruling = apply_decision(packet, decision)
    formula = formula_amount(packet, decision)
    ov = _override(packet, ruling, decision.reviewer, decision.note or ruling.recommended_action, runs_dir)
    entry = {"case_id": packet.case_id, "outcome": decision.outcome, "reviewer": decision.reviewer, "recorded_at": now().isoformat(),
             "status": "decided", "ruling": ruling.model_dump(mode="json"), "formula_amount": formula,
             "amount_override": decision.amount_override.model_dump() if decision.amount_override else None,
             "choices": decision.choices or decision.findings, "note": decision.note,
             "notices": notice_preview(packet, decision, ruling)}
    write_json(runs_dir / REVIEWS_NAME, _load(REVIEWS_NAME, runs_dir) + [entry])
    return {"status": "decided", "review": entry, "override": ov.model_dump(mode="json")}
