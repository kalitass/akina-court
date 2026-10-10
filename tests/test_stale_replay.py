"""An archived sample run must not be served as the current court output."""

import pytest
from fastapi import HTTPException

from app.main import get_run


def test_stale_sample_replay_is_unavailable_but_other_runs_remain_available():
    with pytest.raises(HTTPException) as err:
        get_run("DISP-002")
    assert err.value.status_code == 410
    assert get_run("C-0004")["case_id"] == "C-0004"
