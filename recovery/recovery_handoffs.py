"""Read-only bridge from saved recovery experiments to the existing case queue.

Hash checks establish internal consistency, not authenticity of a record source.
Only server-published flat bundles are used; CLI experiment folders stay separate.
"""
import json
import re
from pathlib import Path

from recovery.evidence import digest
from recovery.reviewer_packet import build_packet
from core.schemas import Case


def list_handoffs(case_id: str, directory: Path) -> dict:
    if case_id not in {'C-0001', 'C-0004'}:
        raise ValueError('Unsupported recovery case')
    items, skipped = [], 0
    for path in sorted(directory.glob('*.json')):
        if not re.fullmatch(r'[0-9a-f]{32}', path.stem) or path.is_symlink():
            continue
        try:
            bundle = json.loads(path.read_text())
            if not isinstance(bundle, dict):
                raise ValueError('Invalid bundle object')
            if bundle.get('source_case_id') != case_id:
                continue
            evidence = bundle['evidence']
            snapshots = bundle['snapshots']
            if not isinstance(evidence, dict) or not isinstance(snapshots, list):
                raise ValueError('Invalid evidence or snapshot list')
            if bundle['review_id'] != path.stem or len(snapshots) not in (1, 2):
                raise ValueError('Invalid bundle identity')
            initial = Case.model_validate(snapshots[0])
            current = Case.model_validate(snapshots[-1])
            if initial.case_id != case_id or current.case_id != case_id:
                raise ValueError('Snapshot belongs to a different case')
            if initial.trip.trip_id != current.trip.trip_id:
                raise ValueError('Snapshot belongs to a different trip')
            if (digest(initial), digest(current)) != (evidence['before_hash'], evidence['after_hash']):
                raise ValueError('Snapshot fingerprint mismatch')
            packet = evidence['reviewer_packet']
            # A stale policy/fact schema or edited packet must not silently feed
            # the current reviewer page. Retain the original bundle for diagnosis.
            if packet != build_packet(initial, current, evidence):
                raise ValueError('Packet does not match current source assessment')
            state = bundle['state']
            if state not in {'human_review', 'ready_for_court', 'review_failed', 'reviewed'}:
                raise ValueError('Unsupported review state')
            items.append({
                'review_id': path.stem,
                'run_id': f'{case_id}~recovery-{path.stem}',
                'review_state': state,
                'evidence_state': evidence['state'],
                'failure': bundle.get('failure'),
                'packet': packet,
                'execution': 'simulation_only',
                'queue_resolution': 'unchanged',
                'next_step': ('The AI review failed. Review the validated evidence and investigation task manually.'
                              if state == 'review_failed' else packet['next_step']),
            })
        except (ValueError, KeyError, TypeError, OSError):
            skipped += 1
    return {'case_id': case_id, 'items': items, 'skipped_records': skipped,
            'ordering': 'review_id; not chronological',
            'limits': ['Saved synthetic recovery bundles only; no model calls or queue writes.',
                       'Internal consistency checks do not authenticate a real telemetry provider.',
                       'Records incompatible with the current policy/fact assessment are omitted.']}
