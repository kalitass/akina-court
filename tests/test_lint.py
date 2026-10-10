"""Every committed case file passes the universal linter (data/synth/lint.py): no driver line typed while moving, pins on
the road, loops that go somewhere, speed bands that agree with the trace, dates and timestamps in order, no bulletin
naming the trip's destination. The generator refuses to publish a case with a violation; this test keeps the committed
files honest, hand-written demos and the organisers' sample included."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synth"))
import lint  # noqa: E402

FILES = lint.all_case_files()


@pytest.mark.parametrize("path", FILES, ids=[Path(f).stem for f in FILES])
def test_case_file_has_no_lint_violation(path):
    assert lint.lint_case(json.load(open(path))) == []
