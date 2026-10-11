"""Voice intake: a spoken complaint becomes text before the court sees it; the court itself is unchanged.

Speech recognition is Tencent Cloud ASR (one-sentence recognition, ≤ 60 s). The transcript is returned to the caller,
who files it exactly as a typed complaint. Credentials: TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY; region
TENCENTCLOUD_ASR_REGION (default ap-singapore). Nothing here touches core/.
"""
from __future__ import annotations

import base64
import json
import os
import struct

FORMATS = {"wav": "wav", "mp3": "mp3", "m4a": "m4a", "aac": "aac", "ogg": "ogg-opus", "opus": "ogg-opus", "pcm": "pcm", "amr": "amr"}
ENGINES = {"en": "16k_en", "zh": "16k_zh", "zh-en": "16k_zh-PY"}      # 16k_zh-PY: Chinese with English words mixed in
MAX_BYTES = 3 * 1024 * 1024                                            # the one-sentence API takes up to 3 MB / 60 s


class VoiceUnavailable(Exception):
    """Speech recognition cannot run here: no credentials, service not activated, or the request was rejected."""


def pcm16_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV header (what the browser recorder sends)."""
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, sample_rate,
                         sample_rate * 2, 2, 16, b"data", len(pcm))
    return header + pcm


def transcribe(audio: bytes, fmt: str = "wav", lang: str = "en") -> dict:
    """{"text", "engine", "request_id", "audio_s"} for a clip, via Tencent Cloud ASR. Raises VoiceUnavailable."""
    fmt = FORMATS.get(fmt.lower().lstrip("."))
    if fmt is None:
        raise VoiceUnavailable(f"unsupported audio format; send one of {', '.join(sorted(FORMATS))}")
    if not audio or len(audio) > MAX_BYTES:
        raise VoiceUnavailable("the clip must be between 1 byte and 3 MB (about 60 seconds)")
    engine = ENGINES.get(lang, ENGINES["en"])
    sid, key = os.environ.get("TENCENTCLOUD_SECRET_ID", ""), os.environ.get("TENCENTCLOUD_SECRET_KEY", "")
    if not (sid and key):
        raise VoiceUnavailable("speech recognition is not configured on this server (no Tencent Cloud credentials)")
    try:
        from tencentcloud.asr.v20190614 import asr_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
    except ImportError as e:        # the SDK is an optional dependency of the web app
        raise VoiceUnavailable(f"speech recognition SDK is not installed: {e}")
    client = asr_client.AsrClient(credential.Credential(sid, key), os.environ.get("TENCENTCLOUD_ASR_REGION", "ap-singapore"))
    req = models.SentenceRecognitionRequest()
    req.from_json_string(json.dumps({"EngSerViceType": engine, "SourceType": 1, "VoiceFormat": fmt,
                                     "Data": base64.b64encode(audio).decode(), "DataLen": len(audio)}))
    try:
        resp = client.SentenceRecognition(req)
    except TencentCloudSDKException as e:
        code = getattr(e, "code", "") or ""
        if "UserNotRegistered" in code or "ServerNotOpen" in code:
            # one-sentence recognition is a separate product; fall back to recording-file recognition (asynchronous)
            return _transcribe_file(client, models, TencentCloudSDKException, audio, fmt, engine)
        raise VoiceUnavailable(f"speech recognition failed: {code or e}")
    return {"text": (resp.Result or "").strip(), "engine": f"tencent-asr:{engine}", "request_id": resp.RequestId,
            "audio_s": round((resp.AudioDuration or 0) / 1000, 1)}


def _transcribe_file(client, models, SDKError, audio: bytes, fmt: str, engine: str, wait_s: float = 45.0) -> dict:
    """Recording-file recognition: create a task, poll until it finishes (a short clip takes a few seconds)."""
    import re
    import time
    req = models.CreateRecTaskRequest()
    req.from_json_string(json.dumps({"EngineModelType": engine, "ChannelNum": 1, "ResTextFormat": 0, "SourceType": 1,
                                     "Data": base64.b64encode(audio).decode(), "DataLen": len(audio)}))
    try:
        task = client.CreateRecTask(req).Data.TaskId
    except SDKError as e:
        code = getattr(e, "code", "") or ""
        if "UserNotRegistered" in code or "ServerNotOpen" in code:
            raise VoiceUnavailable("Tencent Cloud ASR is not activated on this account: open the ASR console once, then retry")
        raise VoiceUnavailable(f"speech recognition failed: {code or e}")
    q = models.DescribeTaskStatusRequest()
    q.from_json_string(json.dumps({"TaskId": task}))
    t0 = time.monotonic()
    while True:
        try:
            st = client.DescribeTaskStatus(q).Data
        except SDKError as e:
            raise VoiceUnavailable(f"speech recognition failed: {getattr(e, 'code', '') or e}")
        if st.StatusStr == "success":
            text = re.sub(r"\[\d+:\d+\.\d+,\d+:\d+\.\d+\]\s*", "", st.Result or "").strip()
            return {"text": text, "engine": f"tencent-asr-file:{engine}", "request_id": f"task {task}", "audio_s": round(float(st.AudioDuration or 0), 1)}
        if st.StatusStr == "failed":
            raise VoiceUnavailable(f"speech recognition failed: {st.ErrorMsg or 'task failed'}")
        if time.monotonic() - t0 > wait_s:
            raise VoiceUnavailable("speech recognition timed out; try a shorter clip")
        time.sleep(1.5)
