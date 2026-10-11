"""Attach reviewer materials after the unchanged evidence validator returns."""
from app.evidence import EvidenceRequest, EvidenceResponse, Provider, SyntheticGpsProvider, digest, plan
from app.evidence import recover as original_recover
from recovery.reviewer_packet import build_packet


def recover(case, provider):
    updated, report = original_recover(case, provider)
    # Conservative extension admission rule, not a change to the court policy.
    # GPS recovery cannot supply missing chat timestamps or establish consent timing.
    untimed = [i for i, message in enumerate(updated.chat)
               if message.sender == 'rider' and message.ts is None]
    if report['state'] == 'ready_for_court' and updated.dispute.type == 'route_deviation' and untimed:
        task = ('GPS was recovered, but rider message timestamps are missing. '
                'Retrieve the original timestamped chat records or ask a human reviewer '
                'to assess consent timing. Never copy a driver timestamp onto a rider message.')
        report.update(state='human_review', human_task=task,
                      admission_check={'status': 'blocked', 'reason': 'missing_rider_chat_timestamps',
                                       'message_indices': untimed, 'scope': 'recovery_extension_only'})
        report['events'].append({'kind': 'blocked', 'message': task})
    if report['request'] is not None:
        report['reviewer_packet'] = build_packet(case, updated, report)
    return updated, report
