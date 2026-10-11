"""Versioned evidence review; existing court remains unchanged."""
from __future__ import annotations
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from core.evidence import Provider, digest, recover
from core.orchestrate import STAGE_TIMINGS, model_outage, run_case
from core.schemas import Case


def comparison(before, after):
    keys = ('ruling', 'amount', 'escalate', 'flag_account', 'evidence_status')
    changes = {k: {'before': getattr(before.ruling, k), 'after': getattr(after.ruling, k)}
               for k in keys if getattr(before.ruling, k) != getattr(after.ruling, k)}
    return {'changes': changes, 'changed': bool(changes),
            'before_reasoning': before.ruling.reasoning, 'after_reasoning': after.ruling.reasoning,
            'before_auto': (before.eligibility or {}).get('auto', False),
            'after_auto': (after.eligibility or {}).get('auto', False),
            'explanation': 'The second hearing used the validated GPS snapshot. The recorded reasoning is shown separately; a change alone does not prove accuracy improvement.'}


async def review_recovered(case: Case, provider: Provider, *, runner=None, on_event=None, review_id=None):
    """Two independent hearings, no previous briefs fed to the reopened court, no original overwrite."""
    runner = runner or run_case
    initial = case.model_copy(deep=True)
    updated, evidence = recover(initial, provider)
    result = {'review_id': review_id or uuid4().hex, 'source_case_id': case.case_id, 'state': evidence['state'],
              'evidence': evidence, 'snapshots': [initial.model_dump(mode='json')],
              'hearings': [], 'attempts': [], 'comparison': None, 'failure': None, 'execution': 'simulation_only'}
    if evidence['state'] != 'ready_for_court':
        return result
    result['snapshots'].append(updated.model_dump(mode='json'))
    for version, snapshot in enumerate((initial, updated), 1):
        hearing_case = snapshot.model_copy(deep=True)
        # ~ prevents precedent/SLA stores from being modified by demonstration hearings.
        hearing_case.case_id = f'{case.case_id}~recovery-{result["review_id"]}-v{version}'
        attempt = {'version': version, 'case_id': hearing_case.case_id, 'state': 'running',
                   'events': [], 'stage_timings': [], 'duration_s': None, 'failure': None,
                   'record': None, 'execution': 'diagnostic_only'}
        result['attempts'].append(attempt)
        def capture(event):
            attempt['events'].append(event.model_dump(mode='json'))
            if on_event:
                on_event(event)
        start = time.monotonic()
        timing_token = STAGE_TIMINGS.set(attempt['stage_timings'])
        try:
            hearing_hash = digest(hearing_case)
            record = await runner(hearing_case, on_event=capture)
            if digest(hearing_case) != hearing_hash:
                raise RuntimeError("Hearing input mutated during review")
            if record.ruling is None:
                raise RuntimeError("Hearing returned no ruling")
            if record.case_id != hearing_case.case_id:
                raise RuntimeError('Hearing record does not match the reviewed case version')
            if digest(snapshot) != (evidence['before_hash'] if version == 1 else evidence['after_hash']):
                raise RuntimeError('Evidence snapshot was mutated during review')
            # Retain a correctly identified record for diagnosis even when an
            # agent failed. It is never added to completed hearings or scores.
            attempt['record'] = record.model_dump(mode='json')
            outages = model_outage(record)
            if outages:
                raise RuntimeError('; '.join(outages))
            result['hearings'].append(record.model_dump(mode='json'))
            attempt['state'] = 'completed'
        except Exception as exc:
            result.update(state='review_failed', failure=f'{type(exc).__name__}: {exc}')
            attempt.update(state='failed', failure=result['failure'])
            return result
        finally:
            attempt['duration_s'] = round(time.monotonic() - start, 3)
            STAGE_TIMINGS.reset(timing_token)
    from core.schemas import CaseRecord
    before, after = [CaseRecord.model_validate(r) for r in result['hearings']]
    result.update(state='reviewed', comparison=comparison(before, after))
    return result


def save_review(result: dict, directory: Path) -> Path:
    """Exclusive single-file bundle: both snapshots, hearings and recovery trace together."""
    rid = result['review_id']
    if len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid):
        raise ValueError('Invalid review ID')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{rid}.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as f:
            temporary = Path(f.name)
            json.dump(result, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.link(temporary, path)  # atomic publish; fails if the review already exists
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
