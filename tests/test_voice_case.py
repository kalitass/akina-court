"""A case with a spoken complaint: the audio is served, the transcript is on file, the case file itself is untouched."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as srv

ROOT = Path(__file__).resolve().parents[1]


def test_spoken_complaints_on_file_are_complete_and_served():
    metas = sorted((ROOT / "data" / "voice").glob("*.json"))
    assert metas, "at least one demo case carries a spoken complaint"
    client = TestClient(srv.app)
    for p in metas:
        m = json.loads(p.read_text(encoding="utf-8"))
        cid = m["case_id"]
        assert p.stem == cid
        for k in ("audio", "transcript", "engine", "request_id", "audio_s", "statement_on_file", "lang"):
            assert m.get(k) not in (None, ""), f"{cid}: {k} missing"
        assert m["engine"].startswith("tencent-asr")
        assert (ROOT / "web" / m["audio"].lstrip("/")).exists(), f"{cid}: audio file {m['audio']} missing"
        case = json.loads(next(d for d in (ROOT / "data" / "cases", ROOT / "data" / "bench" / "cases") if (d / f"{cid}.json").exists()).joinpath(f"{cid}.json").read_text())
        assert m["statement_on_file"] == case["dispute"]["statement"]      # the case file is what the court heard; the transcript sits beside it
        r = client.get(f"/api/cases/{cid}/voice")
        assert r.status_code == 200 and r.json()["transcript"] == m["transcript"]
        assert client.get(m["audio"]).status_code == 200
    assert client.get("/api/cases/C-0006/voice").status_code == 404
