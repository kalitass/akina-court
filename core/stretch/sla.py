"""SLA & routing (STRETCH_SLA): where a ruled case goes next, and a small queue file for a future queue page.

    route(ruling, dispute_type, signals=())  -> Route     queue + SLA hours + reason (pure function)
    event(route)                             -> Event     one "system"/"notify" log line
    enqueue(case_id, route) / list_queue() / resolve(case_id, resolver, note)   -> runs/queue.json

Queues (lowest first):
    auto_resolve   the ruling executes as-is (voucher issued / dispute closed); SLA 0 h, sampled for audit
    review_24h     a human confirms within 24 h: escalated by verify, confidence below AUTO_CONFIDENCE,
                   amount above AUTO_CAP_SGD, a flag_account recommendation, or a high bad-faith signal
    urgent_safety  safety disputes and threat signals: 2 h SLA (SAFE-1)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel

from core.schemas import DisputeType, Event, Ruling
from core.stretch._util import RUNS_DIR, make_event, now, read_json, write_json
from core.stretch.fraud import Signal

Queue = Literal["auto_resolve", "review_24h", "urgent_safety"]
QUEUE_NAME = "queue.json"
AUTO_CONFIDENCE = 0.0           # model confidence is diagnostic only: automation is decided by the policy certificate
AUTO_CAP_SGD = 20.0             # refunds above this are confirmed by a human
SLA_HOURS: dict[Queue, int] = {"auto_resolve": 0, "review_24h": 24, "urgent_safety": 2}
PRIORITY: dict[Queue, int] = {"auto_resolve": 0, "review_24h": 1, "urgent_safety": 2}


class Route(BaseModel):
    queue: Queue
    sla_hours: int
    reason: str
    priority: int                               # 0 auto .. 2 urgent, for sorting a queue page


class QueueItem(BaseModel):
    case_id: str
    queue: Queue
    sla_hours: int
    reason: str
    priority: int
    enqueued_at: datetime
    due_at: datetime
    status: Literal["open", "resolved"] = "open"
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    note: str = ""


def _route(queue: Queue, reason: str) -> Route:
    return Route(queue=queue, sla_hours=SLA_HOURS[queue], reason=reason, priority=PRIORITY[queue])


def route(ruling: Ruling, dispute_type: DisputeType, signals: Iterable[Signal] = (),
          eligibility: Optional[dict] = None) -> Route:
    """Deterministic routing; the first matching rule wins (most urgent first).
    `eligibility` is CaseRecord.eligibility ({"auto": bool, "reasons": [...]}) from the policy certificate;
    when the certificate says the case is not eligible for automation it goes to review regardless of confidence."""
    sigs = list(signals)
    if dispute_type == "safety" or any(s.code == "CHAT_THREAT" for s in sigs):
        return _route("urgent_safety", "safety dispute / threat keyword (SAFE-1): human reviewer within 2 h")
    if ruling.escalate or ruling.ruling == "escalate":
        return _route("review_24h", f"escalated by verify: {ruling.escalation_reason or 'no reason recorded'}")
    if eligibility is not None and eligibility.get("auto") is False:
        why = "; ".join(eligibility.get("reasons") or []) or "no reason recorded"
        return _route("review_24h", f"policy certificate: not eligible for automation ({why})")
    if ruling.confidence < AUTO_CONFIDENCE:
        return _route("review_24h", f"confidence {ruling.confidence:.2f} < {AUTO_CONFIDENCE:.2f}: human confirms before execution")
    if ruling.amount is not None and ruling.amount > AUTO_CAP_SGD:
        return _route("review_24h", f"refund ${ruling.amount:.2f} exceeds the auto-execute cap ${AUTO_CAP_SGD:.2f}")
    if getattr(ruling, "flag_account", False):
        return _route("review_24h", "ruling recommends flag_account: account action needs a human (RD-6 / NS-2)")
    high = [s.code for s in sigs if s.severity == "high"]
    if high:
        return _route("review_24h", f"high-severity bad-faith signal: {', '.join(high)}")
    return _route("auto_resolve", f"{ruling.ruling} at confidence {ruling.confidence:.2f}, no flag, no high-severity signal: execute automatically")


def event(r: Route, case_id: str = "") -> Event:
    sla = "immediate" if r.sla_hours == 0 else f"SLA {r.sla_hours} h"
    return make_event("system", "notify", f"Routed to {r.queue} ({sla})", r.reason)


# ---------------------------------------------------------------------------
# queue file
# ---------------------------------------------------------------------------

def queue_path(runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / QUEUE_NAME


def list_queue(runs_dir: Path = RUNS_DIR, queue: Optional[Queue] = None, status: Optional[str] = None) -> list[QueueItem]:
    """Items sorted most urgent / earliest due first."""
    items = [QueueItem.model_validate(i) for i in read_json(queue_path(runs_dir), [])]
    items = [i for i in items if (queue is None or i.queue == queue) and (status is None or i.status == status)]
    return sorted(items, key=lambda i: (-i.priority, i.due_at))


def _save(items: list[QueueItem], runs_dir: Path) -> None:
    write_json(queue_path(runs_dir), [i.model_dump(mode="json") for i in items])


def enqueue(case_id: str, r: Route, runs_dir: Path = RUNS_DIR) -> QueueItem:
    """Upsert by case_id (a re-run replaces the earlier item)."""
    t = now()
    item = QueueItem(case_id=case_id, queue=r.queue, sla_hours=r.sla_hours, reason=r.reason, priority=r.priority,
                     enqueued_at=t, due_at=t + timedelta(hours=r.sla_hours))
    items = [i for i in list_queue(runs_dir) if i.case_id != case_id] + [item]
    _save(items, runs_dir)
    return item


def resolve(case_id: str, resolver: str, note: str = "", runs_dir: Path = RUNS_DIR) -> Optional[QueueItem]:
    """Mark the item resolved; returns it, or None if the case is not queued."""
    items = list_queue(runs_dir)
    hit = next((i for i in items if i.case_id == case_id), None)
    if hit is None:
        return None
    done = hit.model_copy(update={"status": "resolved", "resolved_at": now(), "resolved_by": resolver, "note": note})
    _save([done if i.case_id == case_id else i for i in items], runs_dir)
    return done


def overdue(runs_dir: Path = RUNS_DIR, at: Optional[datetime] = None) -> list[QueueItem]:
    t = at or now()
    return [i for i in list_queue(runs_dir, status="open") if i.sla_hours and i.due_at < t]
