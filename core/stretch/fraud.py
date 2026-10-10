"""Bad-faith signals (STRETCH_FRAUD): deterministic checks over the fact table, no LLM.

    detect(table, case=None)   -> list[Signal]
    as_facts(signals)          -> list[Fact]   extra facts (source "timeline" / "profile") advocates and judge can cite
    event(signals)             -> Event        one "verify"/"check" log line

Every signal names the fact ids it rests on, so the judge can cite the signal fact AND the underlying evidence.
Signals are hints: policy already says what to do with them (NS-2 flag_account for a fake "I'm Here",
RD-6 for repeat offenders, SAFE-1 for threats; profile facts never decide a case alone).

Fact values written here only use the keys signal / signal_party / severity / evidence so core.verify's value
sniffing (threat, severe, nearest_m, total+base_fare, party, ...) and core.policy_engine's `party` lookup are never
triggered by a signal fact.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

from core.schemas import Case, Event, Fact, FactTable, Party
from core.stretch._util import find, find_all, make_event

Severity = Literal["low", "medium", "high"]

PICKUP_RADIUS_M = 200                 # data-layer parameter (gap G2)
REPEAT_DISPUTES_90D = 3               # profile anomaly: >= 3 disputes in 90 d ...
REPEAT_UPHELD_90D = 2                 # ... with >= 2 upheld  -> REPEAT_OFFENDER
SERIAL_DISPUTES_90D = 3               # >= 3 disputes, none upheld -> SERIAL_COMPLAINANT (low)
WAIT_TOLERANCE_S = 30                 # claimed wait may exceed GPS-verified wait by this much before it is a signal

JAM_WORDS = ("jam", "jammed", "traffic", "congest", "closed", "accident", "roadwork", "road block", "blocked")
WAIT_RE = re.compile(r"wait(?:ed|ing)?\s+(?:for\s+)?(?:more than|over|>)?\s*(\d+)\s*min", re.I)
QUOTE_RE = re.compile(r"[“\"](.+?)[”\"]")

# signal code -> closest legal FactSource for the rendered fact
SOURCE_OF: dict[str, str] = {
    "ARRIVAL_LOCATION_MISMATCH": "timeline", "WAIT_CLAIM_UNSUPPORTED": "timeline", "JAM_CLAIM_UNSUPPORTED": "timeline",
    "REPEAT_OFFENDER": "profile", "SERIAL_COMPLAINANT": "profile",
}


class Signal(BaseModel):
    code: str
    party: Party
    severity: Severity
    evidence: list[str]                       # fact ids the signal rests on
    text: str                                 # one citable sentence


def _quoted(fact: Fact) -> str:
    """The verbatim message inside a chat fact's text (falls back to the whole text)."""
    m = QUOTE_RE.search(fact.text)
    return m.group(1) if m else fact.text


def _texts(table: FactTable, party: Party, case: Optional[Case]) -> list[tuple[str, str]]:
    """(fact id, verbatim text) of everything `party` said that is in the fact table, plus the dispute
    statement when that party filed (the statement is not a fact, so its id is 'statement')."""
    out = [(f.id, _quoted(f)) for f in table.facts if f.source == "chat" and (f.value or {}).get("from") == party]
    if case is not None and case.dispute.filed_by == party:
        out.append(("statement", case.dispute.statement))
    return out


def detect(table: FactTable, case: Optional[Case] = None) -> list[Signal]:
    """All bad-faith signals the facts support, in a stable order."""
    out: list[Signal] = []
    near, here = find(table, "nearest_m"), find(table, "driver_pressed_here_at")
    within = find(table, "within_200m_s")
    within_s = int(within.value["within_200m_s"]) if within else 0

    # 1. "I'm Here" pressed while GPS puts the driver outside the pickup radius (NS-2 flag_account trigger)
    if here and here.value.get("driver_pressed_here_at") and near and not near.value.get("within_200m", True):
        out.append(Signal(code="ARRIVAL_LOCATION_MISMATCH", party="driver", severity="high", evidence=[here.id, near.id],
                          text=(f"Driver tapped \"I'm Here\" ({here.id}) while GPS puts the closest approach at "
                                f"{near.value['nearest_m']:.0f} m from pickup ({near.id}), outside the {PICKUP_RADIUS_M} m radius.")))

    # 2. driver claims to have waited N min; GPS-verified time within 200 m is shorter
    if near:
        claims = [(fid, int(m.group(1))) for fid, t in _texts(table, "driver", case) for m in [WAIT_RE.search(t)] if m]
        bad = [(fid, n) for fid, n in claims if n * 60 > within_s + WAIT_TOLERANCE_S]
        if bad:
            fid, n = max(bad, key=lambda x: x[1])
            ev = [x for x in [fid, near.id, within.id if within else None] if x and x != "statement"]
            out.append(Signal(code="WAIT_CLAIM_UNSUPPORTED", party="driver", severity="medium", evidence=ev,
                              text=(f"Driver claims to have waited {n} min ({fid}) but GPS shows {within_s // 60} min {within_s % 60} s "
                                    f"within {PICKUP_RADIUS_M} m of pickup" + (f" ({within.id})" if within else f" — never inside the radius ({near.id})") + ".")))

    # 3. driver blames traffic / closure / accident while every speed band on record is >= 3 and no incident exists
    bands = find_all(table, "speed_band")
    incidents = find_all(table, "reported_at")
    if bands and not incidents and all(b.value["speed_band"] >= 3 for b in bands):
        jam = [(fid, t) for fid, t in _texts(table, "driver", case) if any(w in t.lower() for w in JAM_WORDS)]
        if jam:
            fid, _ = jam[0]
            ev = [x for x in [fid] if x != "statement"] + [b.id for b in bands]
            lo = min(b.value["kmh_min"] for b in bands)
            out.append(Signal(code="JAM_CLAIM_UNSUPPORTED", party="driver", severity="medium", evidence=ev,
                              text=(f"Driver cites traffic/closure ({fid}) but LTA speed bands on record are all ≥ {lo} km/h "
                                    f"({', '.join(b.id for b in bands)}) and no incident was recorded.")))

    # 4. profile anomalies (supporting evidence only)
    for pf in find_all(table, "disputes_90d", "disputes_upheld_90d"):
        v, party = pf.value, pf.value.get("party")
        if party not in ("rider", "driver"):
            continue
        if v.get("disputes_window_days") != 90:
            continue  # a total with no stated time window cannot establish a 90-day pattern
        if v["disputes_90d"] >= REPEAT_DISPUTES_90D and v["disputes_upheld_90d"] >= REPEAT_UPHELD_90D:
            out.append(Signal(code="REPEAT_OFFENDER", party=party, severity="medium", evidence=[pf.id],
                              text=(f"{party.title()} profile: {v['disputes_90d']} disputes in 90 d, {v['disputes_upheld_90d']} upheld "
                                    f"({pf.id}) — repeat pattern; supports flag_account, never decides the case.")))
        elif v["disputes_90d"] >= SERIAL_DISPUTES_90D and v["disputes_upheld_90d"] == 0:
            out.append(Signal(code="SERIAL_COMPLAINANT", party=party, severity="low", evidence=[pf.id],
                              text=(f"{party.title()} profile: {v['disputes_90d']} disputes in 90 d, none upheld ({pf.id}) — "
                                    f"frequent unsuccessful disputes; context only.")))

    # (threats are not screened here: whether a message is a threat is the judge's reading — SAFE-1 safety screen)
    return out


def as_facts(signals: list[Signal]) -> list[Fact]:
    """Signal facts with temporary ids ("fraud-<code>"); the caller renumbers (core.stretch.renumber).
    """
    out = []
    for s in signals:
        src = SOURCE_OF.get(s.code)
        if src is None:
            continue
        out.append(Fact(id=f"fraud-{s.code}", source=src,
                        text=f"Bad-faith signal {s.code} ({s.party}, {s.severity}): {s.text}",
                        value={"signal": s.code, "signal_party": s.party, "severity": s.severity, "evidence": s.evidence}))
    return out


def highest(signals: list[Signal]) -> Optional[Severity]:
    order = {"low": 0, "medium": 1, "high": 2}
    return max((s.severity for s in signals), key=order.__getitem__, default=None)


def event(signals: list[Signal]) -> Event:
    title = f"Bad-faith screen: {len(signals)} signal(s)" + (f", highest {highest(signals)}" if signals else "")
    body = "\n".join(f"{s.code} [{s.party}, {s.severity}] {s.text} (evidence: {', '.join(s.evidence)})" for s in signals) \
        or "no bad-faith signal: timeline, GPS, traffic and profiles are consistent with both parties' statements"
    return make_event("verify", "check", title, body)
