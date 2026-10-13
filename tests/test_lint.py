"""Every committed case file passes the universal linter (data/synth/lint.py): no driver line typed while moving, pins on
the road, loops that go somewhere, speed bands that agree with the trace, dates and timestamps in order, no bulletin
naming the trip's destination. The generator refuses to publish a case with a violation; this test keeps the committed
files honest, hand-written demos and the organisers' sample included."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synth"))
import lint  # noqa: E402

from core.case_format import read_case  # noqa: E402

FILES = lint.all_case_files()
# The organisers' records are evidence as sent, never edited to please the linter. Rules written for our generated traces
# that their coarse records break, and why: DISP-001's optimal route is ten named waypoints, not a road-snapped polyline
# (PIN measures the snap connector); DISP-003's rider writes 30 s after the trip ended (ORDER expects chat within the trip).
AS_SENT = {"DISP-001": ("PIN",), "DISP-003": ("ORDER",)}


@pytest.mark.parametrize("path", FILES, ids=[Path(f).stem for f in FILES])
def test_case_file_has_no_lint_violation(path):
    errs = lint.lint_case(read_case(path))
    assert [e for e in errs if e.split(":")[0] not in AS_SENT.get(Path(path).stem, ())] == []
