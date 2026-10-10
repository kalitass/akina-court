#!/usr/bin/env python3
"""Check whether a complete DISP-002 rerun is safe to use as a public replay.

Run this against the newly generated record before replacing the archived one.
It does not edit the record or contact a model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.llm import describe_model  # noqa: E402
from core.orchestrate import _safe_notice  # noqa: E402
from core.receipt import verify  # noqa: E402
from core.schemas import Case, CaseRecord  # noqa: E402


def validate(path: Path) -> list[str]:
    case = Case.model_validate_json((ROOT / "data/cases/DISP-002.json").read_text())
    record = CaseRecord.model_validate_json(path.read_text())
    errors: list[str] = []
    expected = json.loads((ROOT / "data/expected/DISP-002.json").read_text())

    if record.case_id != case.case_id:
        errors.append("record belongs to a different case")
    if (record.ruling.ruling != expected["ruling"] or record.ruling.amount != expected["amount"]
            or record.ruling.escalate != expected["escalate"]):
        errors.append("ruling differs from the organisers' expected outcome; inspect before publishing")
    if record.ruling.flag_account:
        errors.append("account flag is present in the sample ruling; inspect before publishing")
    if not verify(record.receipt, case, describe_model())["verified"]:
        errors.append("receipt does not match the current case, policy, code and model")

    profiles = [f for f in record.facts.facts if f.source == "profile"]
    if len(profiles) != 2 or any(f.value.get("disputes_window_days") is not None
                                  or f.value.get("trips_window_days") is not None
                                  or "window unknown" not in f.text for f in profiles):
        errors.append("profile facts still assign a known time window to lifetime totals")

    notices = {n.to: n.text for n in record.notices}
    if set(notices) != {"rider", "driver"} or any(
        notices.get(side) != _safe_notice(side, record.ruling) for side in ("rider", "driver")
    ):
        errors.append("outward notices do not match the verified ruling template")
    if not any(e.kind == "notify" and e.title == "Notices drafted for rider and driver"
               and all(notices.get(side, "") in e.body for side in ("rider", "driver"))
               for e in record.events):
        errors.append("event log does not contain the verified outward notices")
    return errors


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs/DISP-002.json"
    problems = validate(target)
    if problems:
        print("Replay is not ready:")
        for problem in problems:
            print("- " + problem)
        raise SystemExit(1)
    print("DISP-002 replay passed the outcome, provenance, notice and receipt checks.")
