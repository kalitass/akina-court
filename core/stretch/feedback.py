"""Learning feedback loop (STRETCH_FEEDBACK): a human reviewer's override flows back into the precedent store.

    record_override(case_id, human_ruling, reviewer, note)  -> Override     runs/overrides.json + precedent re-index as "human"
    stats()                                                 -> dict         override rate per dispute type (dashboard)

The override also resolves the case's queue item (sla.resolve) when one exists. The CaseRecord is read from
runs/<case_id>.json unless passed in, so the API works from a future review page with only a case id.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from core.schemas import CaseRecord, DisputeType, Ruling
from core.stretch import precedent, sla
from core.stretch._util import RUNS_DIR, now, read_json, write_json

OVERRIDES_NAME = "overrides.json"


class Override(BaseModel):
    case_id: str
    dispute_type: DisputeType
    auto_ruling: Optional[str] = None
    auto_amount: Optional[float] = None
    human_ruling: str
    human_amount: Optional[float] = None
    changed_outcome: bool                     # ruling action or amount differs from the automatic one
    reviewer: str
    note: str = ""
    recorded_at: datetime


def overrides_path(runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / OVERRIDES_NAME


def load(runs_dir: Path = RUNS_DIR) -> list[Override]:
    return [Override.model_validate(o) for o in read_json(overrides_path(runs_dir), [])]


def load_record(case_id: str, runs_dir: Path = RUNS_DIR) -> CaseRecord:
    return CaseRecord.load(runs_dir / f"{case_id}.json")


def ruling_from_override(body: dict, previous: Optional[Ruling] = None) -> Ruling:
    """A reviewer's decision as a Ruling. The reviewer may state safety_concern / evidence_status; otherwise a ruled
    outcome means the person found the evidence sufficient, an escalate keeps the status unknown, and the safety
    reading carries over from the court's ruling (a person who disagrees states it in the body)."""
    action = body["ruling"]
    esc = action == "escalate"
    prev_safety = previous.safety_concern if previous is not None else "none"
    safety = body.get("safety_concern") or ("none" if prev_safety == "unscreened" and not esc else prev_safety)
    status = body.get("evidence_status") or ("unknown" if esc else "sufficient")
    return Ruling(ruling=action, amount=None if esc or action == "no_action" else body.get("amount"),
                  recommended_action=body.get("recommended_action", "per reviewer"), confidence=1.0, reasoning=body.get("reasoning", ""),
                  cited_facts=list(body.get("cited_facts", [])), cited_policy=list(body.get("cited_policy", [])), escalate=esc,
                  safety_concern=safety, safety_basis=list(body.get("safety_basis", [])), evidence_status=status,
                  evidence_gap=body.get("evidence_gap") if status != "sufficient" else None)


def record_override(case_id: str, human_ruling: Ruling, reviewer: str, note: str = "",
                    runs_dir: Path = RUNS_DIR, record: Optional[CaseRecord] = None) -> Override:
    """Persist the human decision, re-index the precedent as source "human" (ranks first in similar()),
    and close the queue item. Latest override per case wins (list keeps history)."""
    rec = record or load_record(case_id, runs_dir)
    auto = rec.ruling
    changed = auto is None or auto.ruling != human_ruling.ruling or (auto.amount or 0) != (human_ruling.amount or 0)
    ov = Override(case_id=case_id, dispute_type=rec.facts.dispute_type,
                  auto_ruling=auto.ruling if auto else None, auto_amount=auto.amount if auto else None,
                  human_ruling=human_ruling.ruling, human_amount=human_ruling.amount, changed_outcome=changed,
                  reviewer=reviewer, note=note, recorded_at=now())
    write_json(overrides_path(runs_dir), [o.model_dump(mode="json") for o in load(runs_dir)] + [ov.model_dump(mode="json")])
    precedent.index(rec, runs_dir, source="human", ruling=human_ruling, reviewer=reviewer)
    sla.resolve(case_id, reviewer, note or f"override: {human_ruling.ruling}", runs_dir)
    return ov


def stats(runs_dir: Path = RUNS_DIR) -> dict[str, dict]:
    """Per dispute type: indexed cases, reviewed cases, cases whose outcome a human changed, and the rates.
    Denominator = precedent store entries (every ruled case is indexed there); falls back to runs/C-*.json."""
    entries = precedent.load(runs_dir)
    totals: dict[str, set[str]] = {}
    if entries:
        for e in entries:
            totals.setdefault(e.dispute_type, set()).add(e.case_id)
    else:
        for p in runs_dir.glob("C-*.json"):
            rec = CaseRecord.load(p)
            totals.setdefault(rec.facts.dispute_type, set()).add(rec.case_id)
    latest: dict[str, Override] = {}
    for o in load(runs_dir):                     # list is chronological; the last entry per case wins
        latest[o.case_id] = o
    out: dict[str, dict] = {}
    for dt in sorted(set(totals) | {o.dispute_type for o in latest.values()}):
        cases = totals.get(dt, set())
        reviewed = {c for c, o in latest.items() if o.dispute_type == dt}
        changed = {c for c, o in latest.items() if o.dispute_type == dt and o.changed_outcome}
        n = len(cases | reviewed)
        out[dt] = {"cases": n, "reviewed": len(reviewed), "overridden": len(changed),
                   "review_rate": round(len(reviewed) / n, 3) if n else 0.0,
                   "override_rate": round(len(changed) / n, 3) if n else 0.0}
    return out
