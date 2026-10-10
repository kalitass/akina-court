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

from pydantic import BaseModel, Field, model_validator

# ----------------------------------------------------------------------------
# 1. Case: raw evidence for one dispute (spec 1.3). Loaded from data/cases/*.json
#    or mapped from the Ryde sample dataset. Agents never see this directly.
# ----------------------------------------------------------------------------

DisputeType = Literal["route_deviation", "no_show", "safety"]
Party = Literal["rider", "driver"]


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


class Route(BaseModel):
    total_km: float
    total_min: float
    polyline: list[tuple[float, float]]           # [(lat, lon), ...]


class GpsPoint(BaseModel):
    ts: datetime
    lat: float
    lon: float
    speed_kmh: float


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


class Traffic(BaseModel):
    speed_bands: list[SpeedBand] = []
    incidents: list[Incident] = []


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
    disputes_window_days: Optional[int] = 90  # synthetic case files use 90-day counts; imported samples can override


class DriverProfile(RiderProfile):
    trips_90d: int
    trips_window_days: Optional[int] = 90


class Profiles(BaseModel):
    rider: RiderProfile
    driver: DriverProfile


class PolicyParams(BaseModel):
    """Platform parameters stated in the case record itself (e.g. the organisers' sample). Absent = Ryde defaults."""
    free_wait_min: Optional[float] = None
    no_show_threshold_min: Optional[float] = None
    cancellation_fee: Optional[float] = None
    fee_goes_to: Optional[str] = None


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


class CaseBrief(BaseModel):
    side: Party
    claims: list[Claim]
    weaknesses: list[str]                         # the advocate must list its own weak points
    requested_outcome: RequestedOutcome


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


# ----------------------------------------------------------------------------
# 4. Ruling: judge output (LLM, structured) + verify annotations (code).
# ----------------------------------------------------------------------------

class RejectedClaim(BaseModel):
    id: str
    reason: str


Finding = Literal["exempt", "counts", "undetermined"]


class SegmentFinding(BaseModel):
    """The judge's reading of one off-route segment. Code settles what it can measure (RD-4 incident); the meaning of
    what was said (RD-3 / RD-5) is the judge's, and it may be undetermined — then the case goes to a person."""
    fact_id: str                                  # the gps off-route segment fact, e.g. "F5"
    finding: Finding                              # exempt = RD-3/RD-4/RD-5 excuses it; counts = refundable under RD-2; undetermined = evidence does not settle it
    basis: list[str] = []                         # the chat / statement fact ids the finding rests on (code checks they exist, who wrote them and when)
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


SafetyConcern = Literal["none", "suspected", "confirmed"]


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
    segment_findings: list[SegmentFinding] = []   # route cases: one entry per off-route segment fact (drives the map colours)
    safety_concern: SafetyConcern = "none"        # the judge's reading of every message, statement and complaint (SAFE-1 / SAFE-2); never a keyword
    safety_basis: list[str] = []                  # fact ids that raised the concern
    evidence_gap: Optional[str] = None            # what is missing when the judge cannot decide (one sentence) — a ground for escalate
    escalate: bool = False
    escalation_reason: Optional[str] = None


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
