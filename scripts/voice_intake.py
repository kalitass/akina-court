#!/usr/bin/env python3
"""Voice intake from the command line: make a spoken test clip, transcribe it, file it as the complaint of a case.

    .venv/bin/python scripts/voice_intake.py say "The driver took a longer route ..." clip.wav   # macOS voice → 16 kHz WAV
    .venv/bin/python scripts/voice_intake.py transcribe clip.wav [--lang en|zh]                   # Tencent Cloud ASR → text
    .venv/bin/python scripts/voice_intake.py file C-0001 clip.wav [--lang en]                     # transcribe, then run the court
                                                                                                   # on C-0001 with that complaint
    .venv/bin/python scripts/voice_intake.py attach C-0001 clip.wav [--lang en]                   # store the clip as the case's spoken
                                                                                                   # complaint: web/voice/<id>.wav +
                                                                                                   # data/voice/<id>.json (transcript)

Credentials: TENCENTCLOUD_SECRET_ID / _KEY in the environment (never in the repo); `file` also needs the model key.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.voice import VoiceUnavailable, transcribe  # noqa: E402


def say(text: str, out: Path) -> Path:
    """Synthesise with the macOS voice and convert to 16 kHz mono 16-bit WAV (the format the recogniser likes best)."""
    with tempfile.TemporaryDirectory() as d:
        aiff = Path(d) / "clip.aiff"
        subprocess.run(["say", "-v", "Samantha", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(out)], check=True)
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    lang = argv[argv.index("--lang") + 1] if "--lang" in argv else "en"
    chat_idx = int(argv[argv.index("--chat") + 1]) if "--chat" in argv else None      # attach: the clip is chat message #N, not the complaint
    argv = [a for i, a in enumerate(argv) if a not in ("--lang", "--chat") and (i == 0 or argv[i - 1] not in ("--lang", "--chat"))]
    cmd = argv[0]
    if cmd == "say":
        out = say(argv[1], Path(argv[2]))
        print(f"wrote {out} ({out.stat().st_size} bytes)"); return 0
    clip = Path(argv[2] if cmd in ("file", "attach") else argv[1])
    try:
        r = transcribe(clip.read_bytes(), clip.suffix, lang)
    except VoiceUnavailable as e:
        print(f"voice intake unavailable: {e}"); return 1
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if cmd == "transcribe":
        return 0
    from app.main import load_case
    if cmd == "attach":
        import shutil
        from datetime import datetime, timezone
        cid = argv[1]
        case = load_case(cid)
        audio_dir, meta_dir = ROOT / "web" / "voice", ROOT / "data" / "voice"
        audio_dir.mkdir(exist_ok=True); meta_dir.mkdir(exist_ok=True)
        meta_path = meta_dir / f"{cid}.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"case_id": cid}
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if chat_idx is None:
            shutil.copyfile(clip, audio_dir / f"{cid}{clip.suffix.lower()}")
            meta.update({"audio": f"/voice/{cid}{clip.suffix.lower()}", "lang": lang, "transcript": r["text"], "engine": r["engine"],
                         "request_id": r["request_id"], "audio_s": r["audio_s"], "recognised_at": stamp, "statement_on_file": case.dispute.statement,
                         "note": "The complaint was spoken; Tencent Cloud ASR produced the transcript. The case file keeps the statement as filed; the court reads text only."})
        else:
            m = case.chat[chat_idx - 1]
            name = f"{cid}-chat-{chat_idx}{clip.suffix.lower()}"
            shutil.copyfile(clip, audio_dir / name)
            entry = {"idx": chat_idx, "from": m.sender, "ts": m.ts.isoformat() if m.ts else None, "audio": f"/voice/{name}", "lang": lang,
                     "transcript": r["text"], "engine": r["engine"], "request_id": r["request_id"], "audio_s": r["audio_s"], "recognised_at": stamp,
                     "text_on_file": m.text}
            meta["chat"] = [c for c in meta.get("chat", []) if c.get("idx") != chat_idx] + [entry]
            meta.setdefault("note", "A chat message arrived as voice; Tencent Cloud ASR produced the transcript, which the case file carries as the message text. The court reads text only.")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
        print(f"attached: data/voice/{cid}.json")
        return 0
    from core.orchestrate import run_case
    from core.schemas import Dispute
    case = load_case(argv[1])
    case = case.model_copy(update={"dispute": Dispute.model_validate({**case.dispute.model_dump(), "statement": r["text"]})})
    rec = asyncio.run(run_case(case, on_event=lambda e: print(f"[{e.elapsed}] {e.actor:6s} {e.kind:8s} {e.title}")))
    print(f"\n{rec.case_id}: {rec.ruling.ruling}" + (f" ${rec.ruling.amount:.2f}" if rec.ruling.amount else "") + f" · {rec.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
