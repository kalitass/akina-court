"""Attach reviewer materials after the unchanged evidence validator returns."""
from core.evidence import EvidenceRequest, EvidenceResponse, Provider, SyntheticGpsProvider, digest, plan
from core.evidence import recover as original_recover
from recovery.reviewer_packet import build_packet


def recover(case, provider):
    updated, report = original_recover(case, provider)
    if report['request'] is not None:
        report['reviewer_packet'] = build_packet(case, updated, report)
    return updated, report
