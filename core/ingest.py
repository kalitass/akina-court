"""Bring a RydeResolve sample dataset (the organisers' JSON) into data/cases as an official-plus case file.

    python -m core.ingest data/samples/DISP-001.md            # markdown with a ```json block, or a bare .json
    python -m core.ingest data/samples/DISP-003.md --out data/cases/DISP-003.json

The file keeps every official field exactly as sent; the reader (core/case_format.py) maps them to the internal Case at
load time, so the same sample loads with or without this step. Added here (plus fields):
  case_metadata.provenance   where the values the reader derives come from (source file, route, history window, timeline)
  optimal_route              only when the record has none: OneMap route for pickup → dropoff (cached legs need no
                             token). Without one the reader draws a straight line and says so in provenance. A record
                             with its own optimal_route waypoints keeps them as the route.
Nothing is invented: fields the sample does not carry stay absent and the fallbacks are named in provenance.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.case_format import dumps, load_official, to_internal  # noqa: E402


def _route(pickup: dict, dropoff: dict):
    """OneMap route pickup → dropoff, or None (no token and the leg is not cached: the reader then draws a straight line)."""
    try:
        from data.synth.route_provider import OneMapRouteProvider
        return OneMapRouteProvider().route([(pickup["lat"], pickup["lng"]), (dropoff["lat"], dropoff["lng"])])
    except Exception:  # noqa: BLE001
        return None


def enrich(d: dict, name: str) -> dict:
    """The official record plus provenance and, when it has none, an optimal route."""
    out = {k: v for k, v in d.items() if k != "case_metadata"}
    prov = {"source": f"RydeResolve sample dataset (organisers): {name}"}
    if (d.get("optimal_route") or {}).get("waypoints"):
        prov["route"] = "optimal_route waypoints in the record"
    else:
        t = d["trip_data"]
        r = _route(t["pickup_location"], t["dropoff_location"])
        if r is not None:
            out["optimal_route"] = {"estimated_distance_km": r["total_km"], "estimated_duration_min": r["total_min"],
                                    "waypoints": [{"lat": la, "lng": lo} for la, lo in r["polyline"]], "roads": r.get("roads", [])}
            prov["route"] = "onemap"
    prov.update({k: v for k, v in (to_internal(out).get("provenance") or {}).items() if k not in prov})
    meta = dict(d.get("case_metadata") or {})
    meta["provenance"] = {**prov, **(meta.get("provenance") or {})}
    return {"case_metadata": meta, **out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path"); ap.add_argument("--out")
    a = ap.parse_args()
    case = enrich(load_official(Path(a.path)), Path(a.path).name)
    cid = case["dispute_ticket"]["dispute_id"]
    out = Path(a.out) if a.out else ROOT / "data" / "cases" / f"{cid}.json"
    out.write_text(dumps(case), encoding="utf-8")
    c = to_internal(case)
    print(f"wrote {out}  ({c['dispute']['type']}, {len(c['gps'])} gps points, route {case['case_metadata']['provenance']['route']})")


if __name__ == "__main__":
    main()
