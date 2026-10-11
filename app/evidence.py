"""Bounded evidence recovery; uses policy gaps, never generates missing telemetry."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel

from core.schemas import Case, GpsPoint
from core.facts.tools import build_fact_table
from core.policy_engine import evaluate


class EvidenceRequest(BaseModel):
    request_id: str
    trip_id: str
    field: Literal['gps'] = 'gps'
    start: datetime
    end: datetime
    reason: str


class EvidenceResponse(BaseModel):
    request_id: str
    trip_id: str
    source: str
    status: Literal['available', 'unavailable', 'conflict']
    points: list[GpsPoint] = []


class Provider(Protocol):
    def fetch(self, request: EvidenceRequest) -> EvidenceResponse: ...


def digest(case: Case) -> str:
    return sha256(case.model_dump_json().encode()).hexdigest()


def plan(case: Case) -> EvidenceRequest | None:
    cert = evaluate(case, build_fact_table(case))
    # This first implementation deliberately handles complete GPS absence only.
    # Partial traces and missing chat need their own validation, not this shortcut.
    if case.dispute.type == 'safety' or case.gps or not cert.insufficient:
        return None
    end = case.trip.cancelled_at or case.trip.dropoff_at
    if end is None or end <= case.trip.accepted_at:
        return None
    return EvidenceRequest(request_id=f'{digest(case)[:16]}:gps', trip_id=case.trip.trip_id,
                           start=case.trip.accepted_at, end=end, reason=cert.insufficient)


def recover(case: Case, provider: Provider) -> tuple[Case, dict]:
    """Return a new snapshot and an audit trail. Never changes or rules on the input."""
    before = case.model_copy(deep=True)
    request = plan(before)
    report = {'version': 1, 'before_hash': digest(before), 'after_hash': digest(before),
              'state': 'no_supported_request', 'request': None, 'events': [], 'human_task': None}
    if request is None:
        return before, report
    report['request'] = request.model_dump(mode='json')
    report['events'].append({'kind': 'request', 'message': request.reason})
    try:
        response = provider.fetch(request)
    except Exception:
        return _blocked(before, report, 'The trip-record service failed. Retrieve the requested GPS interval for review.')
    reason = None
    if response.request_id != request.request_id or response.trip_id != request.trip_id:
        reason = 'The returned evidence belongs to a different request or trip. Retrieve correctly linked GPS records.'
    elif response.status != 'available':
        reason = ('Conflicting GPS records need a person to establish the authoritative source.'
                  if response.status == 'conflict' else 'GPS records could not be retrieved. Investigate arrival and waiting time manually.')
    elif not response.source.strip():
        reason = 'The GPS response has no source. Verify its origin before using it.'
    elif len(response.points) < 2:
        reason = 'The GPS interval is incomplete. Retrieve a trace covering the requested period.'
    else:
        times = [p.ts for p in response.points]
        if any(t.tzinfo is None for t in times):
            reason = 'GPS timestamps have no timezone. Confirm their time basis.'
        elif any(a >= b for a, b in zip(times, times[1:])):
            reason = 'GPS timestamps are not strictly increasing. Reconcile the record ordering.'
        elif times[0] > request.start or times[-1] < request.end:
            reason = 'The GPS trace does not cover the requested period. Retrieve the missing interval.'
        elif any((b-a).total_seconds() > 30 for a,b in zip(times,times[1:])):
            reason = 'The GPS trace has a gap over the demo completeness limit of 30 seconds. Investigate the missing interval.'
        elif any(not (-90 <= p.lat <= 90 and -180 <= p.lon <= 180) for p in response.points):
            reason = 'GPS coordinates are invalid. Verify the returned telemetry.'
    if reason:
        return _blocked(before, report, reason)
    updated = before.model_copy(deep=True)
    updated.gps = [p.model_copy(deep=True) for p in response.points if request.start <= p.ts <= request.end]
    if len(updated.gps) < 2:
        return _blocked(before, report, 'No usable GPS interval remains after filtering. Retrieve the requested interval.')
    updated.provenance['recovered_gps'] = response.source
    updated.provenance['recovered_gps_at'] = datetime.now(timezone.utc).isoformat()
    cert = evaluate(updated, build_fact_table(updated))
    report.update(version=2, after_hash=digest(updated), state='ready_for_court' if not cert.insufficient else 'human_review',
                  human_task=cert.insufficient, policy_after=cert.lines(), allowed_after=cert.allowed,
                  source=response.source)
    report['events'].append({'kind': 'accepted', 'message': 'Linked GPS records accepted; facts and policy recomputed. A court review is still required.'})
    return updated, report


def _blocked(case: Case, report: dict, reason: str) -> tuple[Case, dict]:
    report.update(state='human_review', human_task=reason)
    report['events'].append({'kind': 'blocked', 'message': reason})
    return case, report


class SyntheticGpsProvider:
    """Demo adapter: recovers explicitly synthetic fixture data; no real API access."""
    def __init__(self, full_case: Case, mode: Literal['available', 'unavailable', 'conflict']):
        self.full_case, self.mode = full_case, mode

    def fetch(self, request: EvidenceRequest) -> EvidenceResponse:
        return EvidenceResponse(request_id=request.request_id, trip_id=self.full_case.trip.trip_id,
                                source='synthetic fixture: demo trip-record service', status=self.mode,
                                points=self.full_case.gps if self.mode == 'available' else [])
