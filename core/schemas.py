"""
Data contracts for ryde-dispute. Single source of truth for what flows between layers.

    Case  --(fact tools, code)-->  FactTable
    FactTable --(advocate agents, LLM)--> CaseBrief x2
    FactTable + CaseBrief x2 --(judge agent, LLM)--> Ruling
    Ruling --(verify, code)--> Ruling (rejected_claims filled, escalate decided)
    every step --> Event  (what the UI renders)

"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pathlib import Path

from pydantic import BaseModel, Field, model_serializer, model_validator

# ----------------------------------------------------------------------------
# 1. Case: raw evidence for one dispute (spec 1.3). Case files on disk use the organisers' RydeResolve schema plus
#    our own fields (core/case_format.py); validation maps them to this shape. Agents never see this directly.
#    Fields marked "v3" carry official data the v3 policy needs; nothing reads them for a ruling yet. They are left
#    out of dumps while empty, so a case that carries none of them serialises and hashes exactly as before.
# ----------------------------------------------------------------------------

DisputeType = Literal["route_deviation", "no_show", "safety", "fare_dispute", "property_damage"]   # property_damage: no case data yet
Party = Literal["rider", "driver"]


def _drop_empty(d: dict, keys: tuple[str, ...]) -> dict:
    for k in keys:
        if k in d and d[k] in (None, [], {}):
            del d[k]
    return d


class Dispute(BaseModel):
    type: DisputeType
    filed_by: Party
    filed_at: datetime
    statement: str


class Place(BaseModel):
    lat: float
    lon: float
    name: str


class Trip(BaseModel):
    trip_id: str
    service_type: Literal["RydeTAXI", "RydeX"] = "RydeX"   # RydeTAXI = metered, RydeX = fixed fare
    pickup: Place
    dropoff: Place
    estimated_km: float
    estimated_min: float
    requested_at: datetime
    accepted_at: datetime
    driver_arrived_at: Optional[datetime] = None   # first time within 200 m of pickup (computed from GPS)
    driver_pressed_here_at: Optional[datetime] = None   # arrival confirmation: driver tapped "I'm Here", or the platform auto-confirmed (see arrival_confirmed_by)
    arrival_confirmed_by: Optional[Literal["driver_tap", "platform_auto"]] = None   # None with a timestamp above = driver_tap (older case files)
    arrival_radius_m: Optional[int] = None               # radius the platform used for an automatic arrival confirmation
    wait_started_at: Optional[datetime] = None           # platform wait timer, when the record carries one
    wait_expired_at: Optional[datetime] = None
    fee_applied_at: Optional[datetime] = None
    pickup_at: Optional[datetime] = None
    dropoff_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[Literal["rider", "driver", "system"]] = None
    cancellation_reason: Optional[str] = None             # v3: the reason picked in the app (official trip_data.cancellation_reason) — the canceller's claim
    scheduled_at: Optional[datetime] = None               # v3: scheduled pickup time (official trip_data.scheduled_time)

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        return _drop_empty(handler(self), ("scheduled_at",))


class Route(BaseModel):
    total_km: float
    total_min: float
    polyline: list[tuple[float, float]]           # [(lat, lon), ...]
    roads: list[dict] = []                        # v3: [{"name", "from_m"?, "to_m"?}] along the optimal route (RD-4 road-name match)

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        return _drop_empty(handler(self), ("roads",))


class GpsPoint(BaseModel):
    ts: datetime
    lat: float
    lon: float
    speed_kmh: float
    road: Optional[str] = None                    # v3: road being driven at this sample (official location_desc); RD-5 named-road check

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        return _drop_empty(handler(self), ("road",))


class SpeedBand(BaseModel):
    link_id: Optional[str] = None                 # LTA LinkID (synthetic id in mock data)
    road_name: str
    road_category: str                            # LTA v4: numeric code as string ("1" expressway .. "7")
    speed_band: int = Field(ge=1, le=8)           # LTA: 1 = 0-9 km/h ... 8 = 70+
    window_start: datetime
    window_end: datetime
    geometry: Optional[list[tuple[float, float]]] = None   # [[lat, lon], ...] of the link, for the map (LTA: Start/End coords)


class Incident(BaseModel):
    type: str                                     # Accident | Roadwork | Heavy Traffic | ...
    lat: float
    lon: float
    message: str
    reported_at: datetime


class RoadIncident(BaseModel):
    """v3: an incident identified by road name, without coordinates (official traffic_conditions, DISP-001)."""
    incident_id: Optional[str] = None
    road: Optional[str] = None
    direction: Optional[str] = None
    stretch: Optional[str] = None
    incident_type: Optional[str] = None           # vehicle_fire | heavy_congestion | traffic_flow | ...
    severity: Optional[str] = None
    reported_at: Optional[datetime] = None
    cleared_at: Optional[datetime] = None         # None = not cleared in the record
    description: Optional[str] = None


class Traffic(BaseModel):
    speed_bands: list[SpeedBand] = []
    incidents: list[Incident] = []
    road_incidents: list[RoadIncident] = []       # v3

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        return _drop_empty(handler(self), ("road_incidents",))


class Weather(BaseModel):
    rain_mm: float = 0
    description: str = "Fair"


class Fare(BaseModel):
    base_fare: float = 0
    distance_km: float = 0
    distance_fare: float = 0
    time_min: float = 0
    time_fare: float = 0
    waiting_fee: float = 0
    surge_multiplier: float = 1.0
    platform_fee: float = 0
    discount: float = 0
    total: float = 0
    cancellation_fee: float = 0
    tolls: float = 0                              # ERP / road tolls added after the trip
    edit_destination_fee: float = 0               # Ryde: $3.00 when driver accepts a destination change
    quoted_total: Optional[float] = None          # RydeX fixed-fare quote shown at booking
    pricing: Literal["metered", "fixed"] = "fixed"
    waiting_fee_basis: Optional[str] = None       # "metered_minutes" | "flat_pickup_button"
    currency: str = "SGD"


class ChatMessage(BaseModel):
    ts: Optional[datetime] = None                    # None = the record carries no timestamp (an evidence gap, never silently "before")
    sender: Party = Field(alias="from")
    text: str
    kind: Literal["message", "call"] = "message"     # "call": a call attempt logged in the chat (text = outcome)

    model_config = {"populate_by_name": True}


class RiderProfile(BaseModel):
    account_age_days: int
    rating: float
    disputes_90d: int
    disputes_upheld_90d: int
    route_disputes_upheld_90d: int = 0
    no_show_disputes_upheld_90d: int = 0


class DriverProfile(RiderProfile):
    trips_90d: int


class AccountRecord(BaseModel):
    """v3: account records the official profile carries beyond the history counts."""
    fraud_flags: Optional[int] = None
    fraud_flag_details: Optional[str] = None
    no_shows_30d: Optional[int] = None            # no-show cancellations in a 30-day rolling window (official policy §2.5)


class Profiles(BaseModel):
    rider: RiderProfile
    driver: DriverProfile
    rider_account: Optional[AccountRecord] = None   # v3
    driver_account: Optional[AccountRecord] = None  # v3

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        return _drop_empty(handler(self), ("rider_account", "driver_account"))


class PolicyParams(BaseModel):
    """Platform parameters stated in the case record itself (e.g. the organisers' sample). Absent = Ryde defaults."""
    free_wait_min: Optional[float] = None
    no_show_threshold_min: Optional[float] = None
    cancellation_fee: Optional[float] = None
    fee_goes_to: Optional[str] = None


class FareQuote(BaseModel):
    """v3: the upfront quote shown at booking (its total is Fare.quoted_total)."""
    surge_multiplier: Optional[float] = None      # in effect at quote time
    surge_amount: Optional[float] = None
    surgeable_subtotal: Optional[float] = None


class FareDetail(BaseModel):
    """v3: fare data from the official fare_breakdown that the fare lines above do not carry."""
    upfront_quote: Optional[FareQuote] = None
    surge_amount: Optional[float] = None          # actual fare
    surgeable_subtotal: Optional[float] = None    # actual fare: the part the multiplier applies to
    booking_fee: Optional[float] = None
    booking_fee_surge_exempt: Optional[bool] = None
    excess_distance_fare: Optional[float] = None  # the record's own figure (DISP-001)
    excess_tolls: Optional[float] = None


class SurgeLog(BaseModel):
    """v3: official surge_pricing_log (DISP-003)."""
    quote_time_surge: Optional[float] = None
    trip_start_surge: Optional[float] = None
    surge_activated_at: Optional[datetime] = None
    rider_notified: Optional[bool] = None
    notification_method: Optional[str] = None
    notification_timestamp: Optional[datetime] = None
    notification_text: Optional[str] = None       # SURGE-1: the in-app notice the rider saw, verbatim (what it states is read by the court)
    notification_content: Optional[dict[str, bool]] = None   # legacy: earlier records stated the three items as booleans
    reason: Optional[str] = None


class CallRecord(BaseModel):
    """v3: an in-app call from the platform's call log (official app_events *_called_*, or call_records)."""
    ts: Optional[datetime] = None
    caller: Party
    callee: Optional[Party] = None
    answered: Optional[bool] = None
    duration_s: Optional[float] = None
    recording_ref: Optional[str] = None           # the trip call recording (official policy §1.2: verbal notice needs it)
    transcript: Optional[str] = None
    details: Optional[str] = None                 # the platform's own line, verbatim


class Case(BaseModel):
    case_id: str
    dispute: Dispute
    trip: Trip
    route: Route
    gps: list[GpsPoint]
    traffic: Traffic = Traffic()
    weather: Weather = Weather()
    fare: Fare
    chat: list[ChatMessage] = []
    driver_statement: Optional[str] = None
    profiles: Profiles
    policy_params: Optional[PolicyParams] = None
    provenance: dict[str, str] = {}               # field -> "synthetic" | "ryde_sample" | "onemap"
    fare_detail: Optional[FareDetail] = None      # v3
    surge: Optional[SurgeLog] = None              # v3
    calls: list[CallRecord] = []                  # v3

    @model_validator(mode="before")
    @classmethod
    def _from_file(cls, v):
        """A case file in the official(-plus) shape is mapped here, so every loader reads it."""
        from core.case_format import is_official, to_internal
        return to_internal(v) if is_official(v) else v

    @model_serializer(mode="wrap")
    def _ser(self, handler):
        return _drop_empty(handler(self), ("fare_detail", "surge", "calls"))


# ----------------------------------------------------------------------------
# 2. FactTable: what the code computed (spec 1.5). The only evidence agents see.
# ----------------------------------------------------------------------------

FactSource = Literal["gps", "timeline", "fare", "chat", "traffic", "weather", "profile"]


class Fact(BaseModel):
    id: str                                       # "F1", "F2", ...
    source: FactSource
    text: str                                     # one citable sentence
    value: Optional[dict] = None                  # structured numbers for verify / UI


class FactTable(BaseModel):
    case_id: str
    dispute_type: DisputeType
    facts: list[Fact]

    def ids(self) -> set[str]:
        return {f.id for f in self.facts}


# ----------------------------------------------------------------------------
# 3. CaseBrief: advocate output (LLM, structured). Claims cite fact IDs + clause IDs.
# ----------------------------------------------------------------------------

class Claim(BaseModel):
    id: str                                       # rider: C1, C2...  driver: D1, D2...
    assertion: str
    facts: list[str]                              # ["F1", "F7"]
    policy: list[str]                             # ["RD-1"]
    void: bool = False                            # set by verify when a cited fact does not exist
    void_reason: Optional[str] = None


class RequestedOutcome(BaseModel):
    action: str                                   # from policy/policy.md action vocabulary
    amount: Optional[float] = None


Reading = Literal["met", "not_met", "undetermined"]   # a judge-read policy element: the text satisfies it / does not / cannot tell


class CaseBrief(BaseModel):
    side: Party
    claims: list[Claim]
    weaknesses: list[str]                         # the advocate must list its own weak points
    requested_outcome: RequestedOutcome
    segment_grounds: dict[str, Ground] = {}       # off-route segment fact id -> the policy ground this side's reading of the record supports
    element_readings: dict[str, Reading] = {}     # judge-read policy element id (e.g. "SURGE-1:notice") -> met / not_met / undetermined, this side's honest reading


class RebuttalPoint(BaseModel):
    target_claim_id: str                          # the opponent's claim being answered (or own claim being conceded)
    response: str                                 # one or two sentences, cites facts + clauses
    facts: list[str] = []
    policy: list[str] = []
    concede: bool = False                         # True = the advocate concedes this point of the opponent
    void: bool = False
    void_reason: Optional[str] = None


class Rebuttal(BaseModel):
    """Append-only: the original CaseBrief is immutable; the rebuttal answers the opponent point by point."""
    side: Party
    points: list[RebuttalPoint]
    revised_outcome: Optional[RequestedOutcome] = None   # only if the advocate changes its ask
    segment_grounds: dict[str, Ground] = {}       # the side's grounds after reading the opponent (empty = unchanged from the brief)
    element_readings: dict[str, Reading] = {}     # the side's element readings after reading the opponent (empty = unchanged)


# ----------------------------------------------------------------------------
# 4. Ruling: judge output (LLM, structured) + verify annotations (code).
# ----------------------------------------------------------------------------

class RejectedClaim(BaseModel):
    id: str
    reason: str


Finding = Literal["exempt", "counts", "undetermined"]


Ground = Literal["incident",                  # RD-4: a qualifying incident on the replaced stretch (code settles this one)
                 "rider_named_stop",          # RD-3(a): a rider message before the segment named the place and the car stopped there
                 "general_route_consent",     # RD-5: the rider gave a general route choice ("whichever way is faster") and the loop goes there
                 "named_road_tied",           # RD-5: the rider agreed to a named road and a record ties the driven segment to it
                 "named_road_untied",         # RD-5: agreed to a named road, the record names no roads for the segment and nothing else ties or places it
                 "named_road_elsewhere",      # RD-5: agreed to a named road, but the record places the segment somewhere else
                 "driver_errand",             # RD-5 / RD-3(b): a stop or loop of the driver's own inside the segment that no rider message asked for
                 "scope_other",               # RD-5: the rider agreed to something else (a short stop, a different change), not this segment
                 "consent_after_or_none",     # RD-5: no rider message before the segment agrees to it (asked only, agreed after, refused, silent)
                 "other"]                     # none of the above: the judge must say what, and cannot execute on it

# The consequence the written policy attaches to each ground. The judge reads the words and names the ground; code
# holds it to the consequence (check_ruling): a finding that contradicts its own ground is sent back, then escalated.
GROUND_CONSEQUENCE: dict = {
    # incident: under v3 a traffic reason does not excuse the fare (RD-2); it only clears the driver of a violation
    "incident": "counts", "rider_named_stop": "exempt", "general_route_consent": "exempt", "named_road_tied": "exempt",
    "named_road_untied": "undetermined",
    "named_road_elsewhere": "counts", "driver_errand": "counts", "scope_other": "counts", "consent_after_or_none": "counts",
}


class ElementFinding(BaseModel):
    """The judge's reading of one policy element that turns on what a text says (not a segment): e.g. whether the surge
    notice stated the new multiplier, the revised fare and a free-cancel option (SURGE-1), or why the driver cancelled
    (NS-0). Code fixes the consequence of each reading and checks the basis exists."""
    element: str                                  # the element id the trace names, e.g. "SURGE-1:notice", "NS-0:reason"
    finding: Reading
    basis: list[str] = []                         # fact ids the reading rests on
    reason: str                                   # one clause-cited sentence


class SegmentFinding(BaseModel):
    """The judge's reading of one off-route segment. Code settles what it can measure (RD-4 incident); the meaning of
    what was said (RD-3 / RD-5) is the judge's: the judge names the ground (which policy branch the words fall under)
    and the finding, and code checks the finding is the consequence the policy attaches to that ground."""
    fact_id: str                                  # the gps off-route segment fact, e.g. "F5"
    finding: Finding                              # exempt = RD-3/RD-4/RD-5 excuses it; counts = refundable under RD-2; undetermined = evidence does not set
    ground: Ground = "other"                      # the policy branch the finding rests on (see GROUND_CONSEQUENCE); records before 2026-10-11 carry "other"
    basis: list[str] = []                         # the chat / statement fact ids the finding rests on (code checks they exist, who wrote them and when)
    named_road: Optional[str] = None              # named_road_* grounds: the road the rider agreed to; code checks it against the roads the segment drove (RD-5)
    excluded_road: Optional[str] = None           # a road the rider's words rule out ("ok, but not via Y"); code checks whether the segment drove it
    reason: str                                   # one clause-cited sentence

    @model_validator(mode="before")
    @classmethod
    def _from_legacy(cls, v):
        """Records written before findings had three values stored exempt: true/false."""
        if isinstance(v, dict) and "finding" not in v and "exempt" in v:
            v = dict(v); v["finding"] = "exempt" if v.pop("exempt") else "counts"
        return v

    @property
    def exempt(self) -> Optional[bool]:
        return {"exempt": True, "counts": False}.get(self.finding)


SafetyConcern = Literal["none", "suspected", "confirmed", "unscreened"]   # unscreened = the judge never ran (timeout, provider error); set by code only, always escalates
EvidenceStatus = Literal["sufficient", "insufficient", "unknown"]


class Ruling(BaseModel):
    ruling: str                                   # action vocabulary: refund_full | refund_partial | no_action | escalate ...
    amount: Optional[float] = None
    recommended_action: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str                                # natural language, cites [F*] and [RD-*]
    cited_facts: list[str]
    cited_policy: list[str]
    rejected_claims: list[RejectedClaim] = []
    flag_account: bool = False                    # structured account-flag decision; the only thing actions / checks read
    goodwill_credit: Optional[float] = None       # NS-8: $5.00 credit when the driver neither arrived nor tried to make contact
    element_findings: list[ElementFinding] = []   # one entry per "? element" the trace lists (surge notice content, cancellation reason)
    segment_findings: list[SegmentFinding] = []   # route cases: one entry per off-route segment fact (drives the map colours)
    safety_concern: SafetyConcern                 # REQUIRED: the judge's reading of every message, statement and complaint (SAFE-1 / SAFE-2);
                                                  # "none" means "read and found nothing", never "not read"
    safety_basis: list[str] = []                  # fact ids that raised the concern
    evidence_status: EvidenceStatus               # REQUIRED: sufficient = the record settles the elements the ruling needs;
                                                  # insufficient = a needed record is missing (say what in evidence_gap); unknown = cannot tell.
                                                  # Only "sufficient" can execute; the other two are grounds to escalate.
    evidence_gap: Optional[str] = None            # what is missing (one sentence); null when evidence_status is sufficient
    escalate: bool = False
    escalation_reason: Optional[str] = None


def legacy_ruling(v: dict) -> dict:
    """Migration for ruling dicts written BEFORE safety_concern / evidence_status were required (stored runs and
    benchmark files from 2026-10-09 and earlier). Called only by the explicit record loaders (CaseRecord.load,
    bench readers of archived files) — never by validation, so a new model output missing either field fails."""
    if not isinstance(v, dict) or ("safety_concern" in v and "evidence_status" in v):
        return v
    v = dict(v)
    v.setdefault("safety_concern", "none")
    if "evidence_status" not in v:
        v["evidence_status"] = "insufficient" if (v.get("evidence_gap") and (v.get("escalate") or v.get("ruling") == "escalate")) else "sufficient"
    return v


class Notice(BaseModel):
    to: Party
    text: str


# ----------------------------------------------------------------------------
# 5. Event: one line of the communication log. The UI renders nothing else.
#    Mirrors web/index.html CASES[*].events so the mock front end needs no changes.
# ----------------------------------------------------------------------------

Actor = Literal["system", "rider", "driver", "judge", "verify"]
EventKind = Literal[
    "intake", "facts",            # system
    "tool",                       # advocate tool call
    "brief", "rebuttal",          # advocate output
    "check", "escalate",          # verify (code)
    "ruling", "summary",          # judge
    "notify",                     # system
]


class Event(BaseModel):
    seq: int
    ts: datetime
    elapsed: str                                  # "00:12.1" since intake, for display
    actor: Actor
    kind: EventKind
    title: str = ""
    body: str = ""                                # may contain [F1] [RD-2] tokens; UI linkifies
    # kind-specific payloads (exactly one is set for tool/brief/ruling)
    tool: Optional[dict] = None                   # {"fn": "get_chat_facts", "args": {...}, "returned": ["F4"]}
    brief: Optional[CaseBrief] = None
    rebuttal: Optional[Rebuttal] = None
    ruling: Optional[Ruling] = None
    certificate: Optional[list[str]] = None       # policy execution trace lines (verify events)


class CaseRecord(BaseModel):
    """Everything persisted for one dispute: what the UI loads on page open."""
    case_id: str
    dispute: Dispute
    trip_summary: dict                            # route / fare / duration strings for the header
    status: Literal["in_progress", "resolved", "escalated"]
    facts: FactTable
    events: list[Event]
    ruling: Optional[Ruling] = None
    proposed_ruling: Optional[Ruling] = None      # what the judge said before code verification
    certificate: list[str] = []                   # policy execution trace (final)
    eligibility: Optional[dict] = None            # {"auto": bool, "reasons": [...], "actions": [{"type", "mode", "detail"}], "what_would_change": [...]}
    briefs: dict[str, CaseBrief] = {}
    rebuttals: dict[str, Rebuttal] = {}
    notices: list[Notice] = []
    precedent_id: Optional[str] = None
    receipt: Optional[dict] = None                # fingerprints fixed at ruling time (core/receipt.py)

    @classmethod
    def load(cls, path) -> "CaseRecord":
        """The one entry point for stored runs. Rulings written before safety_concern / evidence_status were required
        are migrated here, explicitly (legacy_ruling); nothing else fills those fields in."""
        import json
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        for k in ("ruling", "proposed_ruling"):
            if isinstance(d.get(k), dict):
                d[k] = legacy_ruling(d[k])
        for ev in d.get("events", []):
            if isinstance(ev, dict) and isinstance(ev.get("ruling"), dict):
                ev["ruling"] = legacy_ruling(ev["ruling"])
        return cls.model_validate(d)
