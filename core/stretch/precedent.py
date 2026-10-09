"""Precedent store (STRETCH_PRECEDENT): "same facts, same ruling".

    index(record)            -> PrecedentEntry      store one CaseRecord's features + ruling in runs/precedents.json
    similar(table, k=3)      -> list[PrecedentHit]  nearest stored cases of the same dispute type
    judge_block(hits)        -> str                 text the orchestrator appends to the judge prompt
    event(hits)              -> Event               one log line ("system"/"facts") for the UI
    consistency(ruling,hits) -> list[str]           lines for the verification event; a WARNING when the
                                                    ruling disagrees with >= 2 highly similar precedents

Similarity is hand-written over a few numeric features per dispute type (no embeddings, no LLM): each
feature difference is normalised by a typical scale and capped at 1, binary features count 1.5x, and
similarity = 1 - weighted mean difference. Human-overridden precedents (source "human", see feedback.py)
rank first at equal similarity and get a small boost, which is the feedback loop.

Facts cannot carry source "precedent" (FactSource is a Literal), so precedents never enter the fact table:
the judge sees them as context text and must still cite F*/clause ids for the actual ruling.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from core.schemas import CaseRecord, DisputeType, Event, FactTable, Ruling
from core.stretch._util import RUNS_DIR, find, find_all, make_event, now, read_json, write_json

STORE_NAME = "precedents.json"
HUMAN_BOOST = 0.05            # added to similarity of human-reviewed precedents (capped at 1.0)
HIGH_SIMILARITY = 0.80        # consistency check: a precedent counts as "highly similar" at or above this
MIN_SHOWN = 0.60              # weaker matches are not shown to the judge at all (a 0.44 match is noise)
BINARY_WEIGHT = 1.5

# feature -> normalisation scale; None = binary (0/1)
FEATURES: dict[DisputeType, dict[str, Optional[float]]] = {
    "route_deviation": {
        "excess_km": 5.0, "excess_pct": 100.0, "n_detours": 2.0, "max_extra_km": 3.0,
        "severe_band": None, "incident_on_route": None, "consent_before_detour": None, "threat": None,
    },
    "no_show": {
        "nearest_m": 500.0, "within_200m_s": 300.0, "s_after_accept": 600.0,
        "cancelled_by_driver": None, "pressed_here": None, "arrival_recorded": None, "threat": None,
    },
    "safety": {"excess_km": 5.0, "n_detours": 2.0, "threat": None},
}


class PrecedentEntry(BaseModel):
    case_id: str
    dispute_type: DisputeType
    features: dict[str, float]
    flags: list[str] = []                       # human-readable feature flags ("threat", "fake_here", ...)
    ruling: str
    amount: Optional[float] = None
    recommended_action: str = ""
    cited_policy: list[str] = []
    confidence: float = 0.0
    source: Literal["auto", "human"] = "auto"
    reviewer: Optional[str] = None
    recorded_at: datetime


class PrecedentHit(BaseModel):
    case_id: str
    ruling: str
    amount: Optional[float] = None
    similarity: float                           # 0..1 after the human boost
    source: Literal["auto", "human"]
    why: str                                    # one line: which features matched / differed


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def features(table: FactTable) -> dict[str, float]:
    """Numeric feature vector from the fact values (same keys as FEATURES[dispute_type], missing -> 0)."""
    f: dict[str, float] = {}
    f["threat"] = float(table.dispute_type == "safety")   # a safety complaint; chat threats are the judge's reading, not a table feature
    if table.dispute_type in ("route_deviation", "safety"):
        dist = find(table, "excess_pct")
        detours = find_all(table, "extra_km", "start")
        f["excess_km"] = float((dist.value or {}).get("excess_km", 0)) if dist else 0.0
        f["excess_pct"] = float((dist.value or {}).get("excess_pct", 0)) if dist else 0.0
        f["n_detours"] = float(len(detours))
        f["max_extra_km"] = max((float(d.value["extra_km"]) for d in detours), default=0.0)
        f["severe_band"] = float(any((x.value or {}).get("severe") for x in table.facts))
        f["incident_on_route"] = float(any((x.value or {}).get("m_from_route") is not None
                                           and x.value["m_from_route"] <= 300 for x in find_all(table, "reported_at")))
        first = min((d.value["start"] for d in detours), default=None)
        rider_msgs = [x.value["ts"] for x in find_all(table, "ts", "idx") if x.value.get("from") == "rider" and x.value.get("ts")]
        f["consent_before_detour"] = float(bool(first) and any(ts < first for ts in rider_msgs))   # a rider message before the detour (what it said is the judge's)
    if table.dispute_type == "no_show":
        near, within, cancel = find(table, "nearest_m"), find(table, "within_200m_s"), find(table, "s_after_accept")
        here, arrived = find(table, "driver_pressed_here_at"), find(table, "driver_arrived_at")
        f["nearest_m"] = float(near.value["nearest_m"]) if near else 0.0
        f["within_200m_s"] = float(within.value["within_200m_s"]) if within else 0.0
        f["s_after_accept"] = float(cancel.value["s_after_accept"]) if cancel else 0.0
        f["cancelled_by_driver"] = float(bool(cancel) and cancel.value.get("cancelled_by") == "driver")
        f["pressed_here"] = float(bool(here) and here.value.get("driver_pressed_here_at") is not None)
        f["arrival_recorded"] = float(bool(arrived) and arrived.value.get("driver_arrived_at") is not None)
    return {k: f.get(k, 0.0) for k in FEATURES[table.dispute_type]}


def flags_of(feat: dict[str, float]) -> list[str]:
    out = []
    if feat.get("threat"):
        out.append("threat")
    if feat.get("pressed_here") and feat.get("nearest_m", 0) > 200:
        out.append("fake_here")
    if feat.get("incident_on_route"):
        out.append("incident_on_route")
    if feat.get("consent_before_detour"):
        out.append("consent_before_detour")
    return out


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

def store_path(runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / STORE_NAME


def load(runs_dir: Path = RUNS_DIR) -> list[PrecedentEntry]:
    return [PrecedentEntry.model_validate(e) for e in read_json(store_path(runs_dir), [])]


def index(record: CaseRecord, runs_dir: Path = RUNS_DIR, source: Literal["auto", "human"] = "auto",
          ruling: Optional[Ruling] = None, reviewer: Optional[str] = None) -> Optional[PrecedentEntry]:
    """Upsert one case into the store (keyed by case_id). `ruling` overrides record.ruling (human override).
    Returns None when there is nothing to index (no ruling). A human entry is never downgraded by an auto re-run."""
    r = ruling or record.ruling
    if r is None:
        return None
    feat = features(record.facts)
    entry = PrecedentEntry(case_id=record.case_id, dispute_type=record.facts.dispute_type, features=feat,
                           flags=flags_of(feat), ruling=r.ruling, amount=r.amount, recommended_action=r.recommended_action,
                           cited_policy=list(r.cited_policy), confidence=r.confidence, source=source, reviewer=reviewer,
                           recorded_at=now())
    entries = load(runs_dir)
    old = next((e for e in entries if e.case_id == record.case_id), None)
    if old and old.source == "human" and source == "auto":
        return old
    entries = [e for e in entries if e.case_id != record.case_id] + [entry]
    write_json(store_path(runs_dir), [e.model_dump(mode="json") for e in entries])
    return entry


def seed_from_runs(runs_dir: Path = RUNS_DIR) -> int:
    """Index every runs/C-*.json CaseRecord (demo bootstrap). Returns the number indexed."""
    n = 0
    for p in sorted(runs_dir.glob("C-*.json")):
        rec = CaseRecord.model_validate_json(p.read_text(encoding="utf-8"))
        if index(rec, runs_dir):
            n += 1
    return n


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------

def _similarity(a: dict[str, float], b: dict[str, float], spec: dict[str, Optional[float]]) -> tuple[float, str]:
    tot_w, tot_d, same, diff = 0.0, 0.0, [], []
    for k, scale in spec.items():
        x, y = a.get(k, 0.0), b.get(k, 0.0)
        if scale is None:
            d, w = float(x != y), BINARY_WEIGHT
            (diff if d else same).append(k)
        else:
            d, w = min(abs(x - y) / scale, 1.0), 1.0
            if d <= 0.25:
                same.append(f"{k} {x:g}≈{y:g}")
            else:
                diff.append(f"{k} {x:g} vs {y:g}")
        tot_w += w
        tot_d += w * d
    sim = 1.0 - tot_d / tot_w if tot_w else 0.0
    why = ("matches " + ", ".join(same) if same else "no matching features") + ("; differs " + ", ".join(diff) if diff else "")
    return round(sim, 3), why


def similar(table: FactTable, k: int = 3, runs_dir: Path = RUNS_DIR, exclude_self: bool = True) -> list[PrecedentHit]:
    """k nearest stored cases of the same dispute type. Human-reviewed entries get HUMAN_BOOST and win ties."""
    spec = FEATURES[table.dispute_type]
    me = features(table)
    hits = []
    for e in load(runs_dir):
        if e.dispute_type != table.dispute_type or (exclude_self and e.case_id == table.case_id):
            continue
        sim, why = _similarity(me, e.features, spec)
        if e.source == "human":
            sim = min(1.0, round(sim + HUMAN_BOOST, 3))
            why = f"human-reviewed by {e.reviewer or 'reviewer'}; " + why
        hits.append(PrecedentHit(case_id=e.case_id, ruling=e.ruling, amount=e.amount, similarity=sim, source=e.source, why=why))
    hits = [h for h in hits if h.similarity >= MIN_SHOWN]
    hits.sort(key=lambda h: (round(h.similarity, 1), h.source == "human", h.case_id), reverse=True)   # similarity first; human breaks ties
    return hits[:k]


def judge_block(hits: list[PrecedentHit]) -> str:
    """Text for the judge prompt. Empty string when there are no hits. Explicitly non-binding."""
    if not hits:
        return ""
    lines = ["PRECEDENTS (context only — not evidence; rule from the fact table and policy, then say whether you follow or depart)"]
    for h in hits:
        amt = f" ${h.amount:.2f}" if h.amount else ""
        tag = " [human-reviewed]" if h.source == "human" else ""
        lines.append(f"  {h.case_id}{tag}: {h.ruling}{amt} (similarity {h.similarity:.2f}) — {h.why}")
    return "\n".join(lines)


def summary(hits: list[PrecedentHit]) -> str:
    """One line: 'N similar case(s): 2× refund_partial, 1× no_action'."""
    if not hits:
        return "no precedent of this dispute type in the store"
    counts: dict[str, int] = {}
    for h in hits:
        counts[h.ruling] = counts.get(h.ruling, 0) + 1
    body = ", ".join(f"{n}× {r}" for r, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    return f"{len(hits)} similar case(s): {body}"


def event(hits: list[PrecedentHit]) -> Event:
    body = "\n".join(f"{h.case_id}{' [human]' if h.source == 'human' else ''}: {h.ruling}"
                     + (f" ${h.amount:.2f}" if h.amount else "") + f" · similarity {h.similarity:.2f} · {h.why}" for h in hits)
    return make_event("system", "facts", f"Precedents: {summary(hits)}", body)


def consistency(ruling: Ruling, hits: list[PrecedentHit], min_similarity: float = HIGH_SIMILARITY, min_count: int = 2) -> list[str]:
    """Lines for the verification event. A WARNING line when >= min_count precedents at or above
    min_similarity all disagree with the ruling (the judge departed from settled practice)."""
    if not hits:
        return ["precedent: none stored for this dispute type"]
    close = [h for h in hits if h.similarity >= min_similarity]
    lines = [f"precedent: {summary(hits)}; {len(close)} at similarity ≥ {min_similarity:.2f}"]
    disagree = [h for h in close if h.ruling != ruling.ruling]
    if len(disagree) >= min_count and len(disagree) == len(close):
        ids = ", ".join(f"{h.case_id}={h.ruling}" for h in disagree)
        lines.append(f"WARNING precedent: ruling {ruling.ruling} differs from {len(disagree)} highly similar precedents ({ids}) — review for consistency")
    elif close and all(h.ruling == ruling.ruling for h in close):
        lines.append(f"precedent: consistent with {len(close)} highly similar case(s)")
    return lines


if __name__ == "__main__":   # python -m core.stretch.precedent [runs_dir]  -> seed the store from existing runs
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else RUNS_DIR
    print(f"indexed {seed_from_runs(d)} record(s) into {store_path(d)}")
