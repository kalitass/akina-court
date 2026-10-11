"""Voice intake: speech becomes text before the court; the court is unchanged and never sees audio."""
from __future__ import annotations

import io
import struct

import pytest
from fastapi.testclient import TestClient

import app.main as srv
from app.voice import VoiceUnavailable, pcm16_to_wav, transcribe


def test_wav_wrapper_writes_a_valid_header():
    pcm = struct.pack("<4h", 0, 1000, -1000, 0)
    wav = pcm16_to_wav(pcm, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and wav[36:40] == b"data"
    assert struct.unpack("<I", wav[24:28])[0] == 16000 and wav[44:] == pcm


def test_transcribe_refuses_what_it_cannot_do(monkeypatch):
    monkeypatch.delenv("TENCENTCLOUD_SECRET_ID", raising=False)
    monkeypatch.delenv("TENCENTCLOUD_SECRET_KEY", raising=False)
    with pytest.raises(VoiceUnavailable, match="unsupported audio format"):
        transcribe(b"x", "webm")
    with pytest.raises(VoiceUnavailable, match="3 MB"):
        transcribe(b"", "wav")
    with pytest.raises(VoiceUnavailable, match="not configured"):
        transcribe(b"RIFF", "wav")


def test_voice_endpoint_returns_text_or_a_clear_503(monkeypatch):
    client = TestClient(srv.app)
    monkeypatch.setenv("DEMO_TOKEN", "")
    import app.voice as voice
    monkeypatch.setattr(voice, "transcribe", lambda data, fmt, lang: {"text": "The driver took a longer route.", "engine": f"fake:{lang}", "request_id": "r1", "audio_s": 3.2})
    r = client.post("/api/intake/voice", files={"audio": ("clip.wav", io.BytesIO(b"RIFF....WAVE"), "audio/wav")}, data={"lang": "en"})
    assert r.status_code == 200 and r.json()["text"].startswith("The driver") and r.json()["engine"] == "fake:en"

    def down(data, fmt, lang):
        raise VoiceUnavailable("Tencent Cloud ASR is not activated on this account: open the ASR console once, then retry")
    monkeypatch.setattr(voice, "transcribe", down)
    r = client.post("/api/intake/voice", files={"audio": ("clip.wav", io.BytesIO(b"RIFF"), "audio/wav")})
    assert r.status_code == 503 and "not activated" in r.json()["detail"]


def test_transcript_is_filed_as_the_complaint_and_never_saved(monkeypatch):
    client = TestClient(srv.app)
    monkeypatch.setenv("DEMO_TOKEN", "")
    monkeypatch.setattr(srv, "LIVE_RUNS", True)
    heard = {}

    async def fake_run_case(case, on_event=None, rebuttal=True, inject=None):
        heard["statement"] = case.dispute.statement
        raise RuntimeError("stop here: the court itself is not under test")
    monkeypatch.setattr(srv, "run_case", fake_run_case)
    saved = []
    monkeypatch.setattr(srv, "save_record", lambda rec, d: saved.append(rec))
    r = client.post("/api/runs/C-0001", json={"statement": "He drove me out to Beach Road for his own stop."})
    assert r.status_code == 200 and r.json()["run_id"] == "C-0001~voice"
    import time
    for _ in range(50):
        if srv.RUNS["C-0001~voice"].done:
            break
        time.sleep(0.05)
    assert heard["statement"] == "He drove me out to Beach Road for his own stop."
    assert saved == []
    # the case the run actually heard is what the receipt and the replay see
    assert srv.get_case("C-0001~voice")["dispute"]["statement"].startswith("He drove me")
    # a statement cannot ride on a counterfactual or an injection, and must be text
    assert client.post("/api/runs/C-0001", json={"statement": "x", "counterfactual": "no_consent"}).status_code == 400
    assert client.post("/api/runs/C-0001", json={"statement": ""}).status_code == 400
