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
        case = json.loads(next(d for d in (ROOT / "data" / "cases", ROOT / "data" / "bench" / "cases") if (d / f"{cid}.json").exists()).joinpath(f"{cid}.json").read_text())
        clips = []
        if m.get("audio"):                                   # the complaint itself was spoken
            for k in ("transcript", "engine", "request_id", "audio_s", "statement_on_file", "lang"):
                assert m.get(k) not in (None, ""), f"{cid}: {k} missing"
            assert m["statement_on_file"] == case["dispute"]["statement"]      # the case file is what the court heard; the transcript sits beside it
            clips.append((m["audio"], m["engine"]))
        for v in m.get("chat", []):                          # a chat message arrived as voice: the transcript IS the filed text
            for k in ("idx", "audio", "transcript", "engine", "request_id", "audio_s", "text_on_file"):
                assert v.get(k) not in (None, ""), f"{cid}: chat {k} missing"
            msg = case["chat"][v["idx"] - 1]
            assert v["text_on_file"] == msg["text"] and " ".join(v["transcript"].split()) == msg["text"], f"{cid}: chat #{v['idx']} text differs from the transcript"
            assert v["from"] == msg["from"]
            clips.append((v["audio"], v["engine"]))
        assert clips, f"{cid}: no clip on file"
        for audio, engine in clips:
            assert engine.startswith("tencent-asr")
            assert (ROOT / "web" / audio.lstrip("/")).exists(), f"{cid}: audio file {audio} missing"
            assert client.get(audio).status_code == 200
        r = client.get(f"/api/cases/{cid}/voice")
        assert r.status_code == 200 and r.json() == m
    assert client.get("/api/cases/C-0006/voice").status_code == 404
