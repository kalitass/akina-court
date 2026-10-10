"""Reproducibility receipt: fingerprints fixed at ruling time, re-checked at request time.

A ruling carries sha256 fingerprints of (1) the exact case the agents saw, (2) the policy text, (3) the code that
computed the facts and ran the court, (4) the model, and (5) the judge prompt. `GET /api/runs/{id}/receipt` returns
the stored fingerprints next to the current ones with a match flag per item, so a reviewer can tell whether the
ruling could be reproduced today or whether something has changed since.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.schemas import Case

ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = ("core", "data/rates.json")                 # the code that computes facts, runs the court and checks the ruling, plus the rate table a fact reads; the web/API layer is not part of the ruling
KEYS = ("case_sha256", "policy_sha256", "code_sha256", "model")


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def case_hash(case: Case) -> str:
    return _h(json.dumps(case.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode("utf-8"))


def policy_hash() -> str:
    return _h((ROOT / "policy" / "policy.md").read_bytes())


def code_hash() -> str:
    files: list[Path] = []
    for entry in CODE_FILES:
        p = ROOT / entry
        files += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    h = hashlib.sha256()
    for f in files:
        if f.exists() and "__pycache__" not in f.parts:
            h.update(str(f.relative_to(ROOT)).encode()); h.update(f.read_bytes())
    return h.hexdigest()[:16]


def fingerprint(case: Case, model: str, judge_prompt: Optional[str] = None) -> dict:
    return {"case_sha256": case_hash(case), "policy_sha256": policy_hash(), "code_sha256": code_hash(), "model": model,
            "judge_prompt_sha256": _h(judge_prompt.encode("utf-8")) if judge_prompt else None,
            "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def verify(stored: Optional[dict], case: Case, model: str) -> dict:
    current = fingerprint(case, model)
    if not stored:
        return {"stored": None, "current": current, "match": {}, "verified": False, "status": "no stored receipt (run predates receipts)"}
    match = {k: stored.get(k) == current.get(k) for k in KEYS}
    ok = all(match.values())
    changed = [k for k, v in match.items() if not v]
    return {"stored": stored, "current": current, "match": match, "verified": ok,
            "status": "verified: case, policy, code and model are unchanged since the ruling" if ok
            else "mismatch: " + ", ".join(changed) + " changed since the ruling — re-run before relying on it"}
