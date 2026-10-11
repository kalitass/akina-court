"""Versioned evidence review; existing court remains unchanged."""
from __future__ import annotations
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from recovery.evidence import Provider, digest, recover
from core.orchestrate import model_outage, run_case
from core.schemas import Case, CaseRecord
from core.llm import describe_model
from core.receipt import verify


def recovery_code_hash():
    from hashlib import sha256
    h = sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        h.update(path.name.encode()); h.update(path.read_bytes())
    return h.hexdigest()


def hearing_context(hearing_mode="court"):
    """Configuration needed to compare hearings; receipts separately pin code and policy."""
    return {'model': describe_model(),
            'tokenhub_base_url': os.environ.get('TOKENHUB_BASE_URL'),
            'role_models': {role: os.environ.get(f'LLM_MODEL_{role}') for role in ('JUDGE', 'ADVOCATE')},
            'workflow': hearing_mode,
            'recovery_code_sha256': recovery_code_hash(),
            'stretch': {k: v for k, v in sorted(os.environ.items()) if k.startswith('STRETCH_')}}


def verified_initial(case, bundle, hearing_mode="court"):
    """Reuse only a completed initial hearing from a matching saved recovery bundle.

    Receipts check consistency, not authenticity. The API loads server-owned
    bundles; callers of this function must supply records from a trusted store.
    """
    if bundle.get('source_case_id') != case.case_id:
        raise ValueError('Previous review belongs to another case')
    snapshots = bundle.get('snapshots') or []
    if not snapshots or digest(Case.model_validate(snapshots[0])) != digest(case):
        raise ValueError('Previous review used a different initial snapshot')
    if bundle.get('hearing_context') != hearing_context(hearing_mode):
        raise ValueError('Previous hearing configuration changed or is unavailable')
    hearings = bundle.get('hearings') or []
    if not hearings:
        raise ValueError('Previous review has no completed initial hearing')
    record = CaseRecord.model_validate(hearings[0])
    source_id = (bundle.get('reused_initial') or {}).get('review_id', bundle.get('review_id'))
    if not isinstance(source_id, str) or len(source_id) != 32 or any(c not in '0123456789abcdef' for c in source_id):
        raise ValueError('Previous review has an invalid source ID')
    expected_id = f'{case.case_id}~recovery-{source_id}-v1'
    if record.case_id != expected_id or record.ruling is None or model_outage(record):
        raise ValueError('Previous initial hearing is incomplete or incorrectly identified')
    original_input = case.model_copy(deep=True)
    original_input.case_id = expected_id
    check = verify(record.receipt, original_input, describe_model())
    if not check['verified']:
        raise ValueError('Previous hearing receipt is missing or stale: ' + check['status'])
    return record.model_dump(mode='json')


def comparison(before, after):
    keys = ('ruling', 'amount', 'escalate', 'flag_account', 'evidence_status')
    changes = {k: {'before': getattr(before.ruling, k), 'after': getattr(after.ruling, k)}
               for k in keys if getattr(before.ruling, k) != getattr(after.ruling, k)}
    return {'changes': changes, 'changed': bool(changes),
            'before_reasoning': before.ruling.reasoning, 'after_reasoning': after.ruling.reasoning,
            'before_auto': (before.eligibility or {}).get('auto', False),
            'after_auto': (after.eligibility or {}).get('auto', False),
            'explanation': 'The second hearing used the validated GPS snapshot. The recorded reasoning is shown separately; a change alone does not prove accuracy improvement.'}


async def review_recovered(case: Case, provider: Provider, *, runner=None, on_event=None, review_id=None, previous_review=None, hearing_mode="court"):
    """Independent hearings; optionally reuse a verified initial hearing, never feed its briefs to the new court."""
    runner = runner or run_case
    initial = case.model_copy(deep=True)
    updated, evidence = recover(initial, provider)
    result = {'review_id': review_id or uuid4().hex, 'source_case_id': case.case_id, 'state': evidence['state'],
              'evidence': evidence, 'snapshots': [initial.model_dump(mode='json')],
              'hearings': [], 'attempts': [], 'comparison': None, 'failure': None, 'execution': 'simulation_only',
              'hearing_context': hearing_context(hearing_mode), 'reused_initial': None}
    if evidence['state'] != 'ready_for_court':
        return result
    result['snapshots'].append(updated.model_dump(mode='json'))
    versions = [(1, initial), (2, updated)]
    if previous_review is not None:
        try:
            record = verified_initial(initial, previous_review, hearing_mode)
        except (ValueError, TypeError, KeyError) as exc:
            result.update(state='reuse_rejected', failure=str(exc))
            return result
        result['hearings'].append(record)
        result['reused_initial'] = {'review_id': (previous_review.get('reused_initial') or {}).get('review_id', previous_review['review_id']),
                                    'parent_review_id': previous_review['review_id'],
                                    'case_id': record['case_id'], 'receipt_verified': True}
        versions = [(2, updated)]
    for version, snapshot in versions:
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
