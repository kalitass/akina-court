"""An archived sample run must not be served as the current court output."""

import pytest
from fastapi import HTTPException

from app.main import get_run
from scripts.validate_sample_run import ROOT, validate


def test_stale_sample_replay_is_unavailable_but_other_runs_remain_available():
    with pytest.raises(HTTPException) as err:
        get_run("DISP-002")
    assert err.value.status_code == 410
    assert get_run("C-0004")["case_id"] == "C-0004"


def test_archived_sample_cannot_pass_replay_acceptance_gate():
    errors = validate(ROOT / "runs/DISP-002.json")
    assert any("profile facts" in error for error in errors)
    assert any("outward notices" in error for error in errors)
