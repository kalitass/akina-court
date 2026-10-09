"""Shared helpers for the stretch modules: feature flags, tiny JSON stores, Event construction.

Nothing here touches an LLM. Stores are plain JSON lists under runs/ (gitignored), rewritten atomically.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from core.schemas import Event, Fact, FactTable

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"
TRUTHY = {"1", "true", "yes", "on"}


def enabled(name: str) -> bool:
    """Feature flag: `enabled("precedent")` reads STRETCH_PRECEDENT (also accepts the full env name). Default off."""
    key = name.upper() if name.upper().startswith("STRETCH_") else f"STRETCH_{name.upper()}"
    return os.environ.get(key, "").strip().lower() in TRUTHY


def now() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def make_event(actor: str, kind: str, title: str, body: str = "", **payload) -> Event:
    """An Event with seq=0 / elapsed="": the orchestrator's EventLog owns numbering. See `replay()`."""
    return Event(seq=0, ts=now(), elapsed="", actor=actor, kind=kind, title=title, body=body, **payload)


def replay(events: Iterable[Event], emit) -> list[Event]:
    """Re-emit hook events through the orchestrator's `EventLog.emit` so they get seq / ts / elapsed."""
    out = []
    for e in events:
        payload = {k: v for k, v in (("tool", e.tool), ("brief", e.brief), ("ruling", e.ruling)) if v is not None}
        out.append(emit(e.actor, e.kind, e.title, e.body, **payload))
    return out


def renumber(extra: Iterable[Fact], table: FactTable) -> list[Fact]:
    """Give extra facts ids F{n+1}.. after the table's last fact (the caller appends them in this order)."""
    n = len(table.facts)
    return [f.model_copy(update={"id": f"F{n + i}"}) for i, f in enumerate(extra, 1)]


def values(table: FactTable) -> dict[str, dict]:
    return {f.id: (f.value or {}) for f in table.facts}


def find(table: FactTable, *keys: str, **eq) -> Optional[Fact]:
    """First fact whose value has every key in `keys` and matches every `eq` item (e.g. find(t, "nearest_m"))."""
    for f in table.facts:
        v = f.value or {}
        if all(k in v for k in keys) and all(v.get(k) == val for k, val in eq.items()):
            return f
    return None


def find_all(table: FactTable, *keys: str, **eq) -> list[Fact]:
    out = []
    for f in table.facts:
        v = f.value or {}
        if all(k in v for k in keys) and all(v.get(k) == val for k, val in eq.items()):
            out.append(f)
    return out
