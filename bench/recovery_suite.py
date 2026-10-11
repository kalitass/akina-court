"""Derived synthetic recovery stress tests, separate from the published benchmark."""
import json
import math
from pathlib import Path

from recovery.evidence import EvidenceResponse, digest
from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'data/recovery/manifest.json'


def load_suite():
    from core.receipt import policy_hash
    manifest = json.loads(MANIFEST.read_text())
    if manifest['policy_hash'] != policy_hash():
        raise ValueError('Policy changed; review and refreeze recovery references')
    for row in manifest['cases']:
        full = Case.model_validate_json((ROOT / 'data/cases' / f"{row['base_case']}.json").read_text())
        if digest(full) != row['base_hash']:
            raise ValueError(f"{row['id']}: base fixture changed; review and refreeze its reference")
    return manifest


def prepare_case(row):
    full = Case.model_validate_json((ROOT / 'data/cases' / f"{row['base_case']}.json").read_text())
    if digest(full) != row['base_hash']:
        raise ValueError('Base fixture fingerprint mismatch')
    if row.get('mutation') == 'untimed_rider_messages':
        for message in full.chat:
            if message.sender == 'rider':
                message.ts = None
    elif row.get('mutation') == 'missing_distance_fare':
        full.fare.distance_fare = 0
        full.fare.distance_km = 0
    elif row.get('mutation') == 'driver_cancels_at_pickup':
        full.trip.cancelled_by = 'driver'
    initial = full.model_copy(deep=True)
    initial.gps = []
    return initial, StressProvider(full, row['response'])


class StressProvider:
    def __init__(self, full, mode):
        self.full, self.mode = full, mode

    def fetch(self, request):
        if self.mode == 'service_error':
            raise RuntimeError('Synthetic trip-record outage')
        points = [p.model_copy(deep=True) for p in self.full.gps]
        if self.mode == 'truncated':
            points = points[2:]
        elif self.mode == 'gap':
            sampled = points[::10]
            if sampled[-1].ts != points[-1].ts:
                sampled.append(points[-1])
            points = sampled
        return EvidenceResponse(
            request_id=request.request_id,
            trip_id='synthetic-other-trip' if self.mode == 'wrong_trip' else request.trip_id,
            source='synthetic recovery stress fixture',
            status=self.mode if self.mode in {'unavailable', 'conflict'} else 'available',
            points=[] if self.mode in {'unavailable', 'conflict'} else points)


def score(hearing, expected):
    """Strict final outcome includes amount, escalation and account flag.

    An invalid/missing amount must not become zero through truthiness coercion.
    """
    ruling = hearing['ruling']
    actual, target = ruling.get('amount'), expected['amount']
    if target is None:
        amount_matches = actual is None
    else:
        amount_matches = (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                          and math.isfinite(actual) and abs(actual - target) <= .010000001)
    correct = (ruling.get('ruling') == expected['ruling'] and amount_matches
               and ruling.get('escalate') == expected['escalate']
               and ruling.get('flag_account') == expected['flag_account'])
    auto = bool((hearing.get('eligibility') or {}).get('auto'))
    return {'strict_match': correct, 'automatic_and_correct': auto and correct,
            'wrong_automatic': auto and not correct, 'automatic': auto}


def workflow_score(result, row):
    if result['state'] == 'reviewed':
        return {'kind': 'model_decision', **score(result['hearings'][-1], row['expected'])}
    if result['state'] == 'human_review':
        expected = row['expected']
        return {'kind': 'retrieval_handoff', 'correct_handoff': expected['ruling'] == 'escalate',
                'automatic_and_correct': False, 'wrong_automatic': False}
    # Timeouts and unavailable agents are failures, not correctly escalated rulings.
    return None
