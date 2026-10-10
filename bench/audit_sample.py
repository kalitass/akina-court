#!/usr/bin/env python3
"""Audit sample: re-run a small preregistered set of benchmark cases per arm and keep the FULL transport evidence.

For every HTTP call to the model API this stores the exact request body (system/user messages, output schema,
parameters), the unmodified response body, the provider's response headers (request id, date) and timings, so a
reviewer can see with their own eyes what the model was asked and what it answered. The ordinary benchmark files
(bench/results/<arm>/) keep only parsed rulings and usage; this directory is the proof that those come from real runs.

    export DEEPSEEK_API_KEY=...   (or put it in .env); export LLM_PROVIDER=deepseek
    .venv/bin/python bench/audit_sample.py                 # 5 cases x 4 arms -> bench/results/audit_sample/
    .venv/bin/python bench/audit_sample.py --cases B-0001  # subset

Nothing under core/ is modified: the three places that build a model are re-pointed, in this process only, to a
provider whose HTTP client has request/response hooks.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import os

# The benchmark and the stored demo runs are the bare court: no precedent store feeding earlier rulings into later
# prompts, no SLA queue or bad-faith signals writing extra facts or repo files. Whatever the shell exports is ignored.
for _k in [k for k in os.environ if k.startswith("STRETCH_")]:
    os.environ.pop(_k)
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx2  # noqa: E402  (the openai 3.x client speaks httpx2)
from pydantic_ai.models.openai import OpenAIChatModel  # noqa: E402
from pydantic_ai.providers.deepseek import DeepSeekProvider  # noqa: E402

import core.llm as llm  # noqa: E402

CASES = ["B-0001", "B-0022", "B-0026", "B-0034", "B-0044"]   # route basic, route consent-scope, no-show fake "I'm Here", no-show 175 s boundary, safety threat
ARMS = ["raw", "facts_only", "judge_only", "court"]
OUT = ROOT / "bench" / "results" / "audit_sample"
REDACT = {"authorization", "cookie", "set-cookie", "x-api-key"}
REDACT_PREFIX = ("x-stainless-",)        # SDK / OS fingerprint headers: not evidence, not published


def _keep(k: str) -> bool:
    return k.lower() not in REDACT and not k.lower().startswith(REDACT_PREFIX)

# ---- transport capture ----
CALLS: list[dict] = []          # calls of the run in progress
_pending: dict[int, dict] = {}


async def _on_request(request: httpx2.Request) -> None:
    body = request.content.decode("utf-8", "replace") if request.content else ""
    try:
        body_json = json.loads(body)
    except Exception:  # noqa: BLE001
        body_json = None
    rec = {"n": len(CALLS) + len(_pending) + 1, "started_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
           "method": request.method, "url": str(request.url),
           "request_headers": {k: ("<redacted>" if not _keep(k) else v) for k, v in request.headers.items()},
           "request_body": body_json if body_json is not None else body, "_t0": time.monotonic()}
    _pending[id(request)] = rec


async def _on_response(response: httpx2.Response) -> None:
    await response.aread()
    rec = _pending.pop(id(response.request), {"n": len(CALLS) + 1, "url": str(response.request.url), "_t0": time.monotonic()})
    text = response.text
    try:
        body_json = json.loads(text)
    except Exception:  # noqa: BLE001
        body_json = None
    rec.update({"status": response.status_code, "latency_s": round(time.monotonic() - rec.pop("_t0"), 3),
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "response_headers": {k: ("<redacted>" if not _keep(k) else v) for k, v in response.headers.items()},
                "response_body": body_json if body_json is not None else text,
                "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    CALLS.append(rec)


CLIENT = httpx2.AsyncClient(event_hooks={"request": [_on_request], "response": [_on_response]}, timeout=180)


def make_model(role: str = "advocate"):
    """Same model selection as core.llm.make_model, DeepSeek provider, but through the capturing HTTP client."""
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    if provider != "deepseek":
        raise SystemExit("audit_sample captures the DeepSeek provider only (LLM_PROVIDER=deepseek)")
    name = os.environ.get(f"LLM_MODEL_{role.upper()}") or os.environ.get("LLM_MODEL") or llm.DEFAULTS["deepseek"]
    return OpenAIChatModel(name, provider=DeepSeekProvider(api_key=os.environ["DEEPSEEK_API_KEY"], http_client=CLIENT))


import core.agents.advocate as _adv  # noqa: E402
import core.agents.judge as _judge  # noqa: E402
import bench.baseline as _base  # noqa: E402
_adv.make_model = _judge.make_model = _base.make_model = make_model

from bench.baseline import run_baseline  # noqa: E402
from bench.run_bench import load_case, ruling_dict  # noqa: E402
from core.llm import describe_model  # noqa: E402
from core.orchestrate import run_case  # noqa: E402
from core.receipt import fingerprint  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def summarize_calls(calls: list[dict]) -> dict:
    """Provider-side identifiers and usage, taken from the stored responses (DeepSeek: header x-ds-trace-id, body id)."""
    bodies = [c.get("response_body") for c in calls if isinstance(c.get("response_body"), dict)]
    return {"model_calls": len(calls),
            "provider_trace_ids": [c.get("response_headers", {}).get("x-ds-trace-id") for c in calls],
            "provider_response_ids": [b.get("id") for b in bodies],
            "provider_model_reported": sorted({str(b.get("model")) for b in bodies}),
            "system_fingerprints": sorted({str(b.get("system_fingerprint")) for b in bodies if b.get("system_fingerprint")}),
            "requested_model": sorted({str((c.get("request_body") or {}).get("model")) for c in calls if isinstance(c.get("request_body"), dict)}),
            "usage": [b.get("usage") for b in bodies]}


async def run_one(arm: str, cid: str) -> dict:
    case = load_case(cid, swap=False)
    CALLS.clear(); _pending.clear()
    d = OUT / arm / cid
    if d.exists():
        shutil.rmtree(d)            # never mix this capture's call files with an earlier one's
    (d / "calls").mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    rec = {"arm": arm, "case_id": cid, "model": describe_model(), "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "fingerprint": fingerprint(case, describe_model())}
    if arm in ("court", "judge_only"):
        record = await asyncio.wait_for(run_case(case, rebuttal=arm == "court", advocates=arm == "court"), 600)
        rec["ruling"] = ruling_dict(record.ruling); rec["status"] = record.status
        e = getattr(record, "eligibility", None)
        rec["eligibility"] = e.model_dump(mode="json") if hasattr(e, "model_dump") else e
        (d / "record.json").write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=1))
    else:
        out = await asyncio.wait_for(run_baseline(case, arm), 600)
        rec["ruling"] = ruling_dict(out["ruling"])
    rec["latency_s"] = round(time.monotonic() - t0, 2)
    rec["model_calls"] = len(CALLS)
    rec.update(summarize_calls(CALLS))
    for c in CALLS:
        (d / "calls" / f"{c['n']:02d}.json").write_text(json.dumps(c, ensure_ascii=False, indent=1))
    rec["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (d / "run.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


async def main_async(cases: list[str], arms: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    runs = []
    for arm in arms:
        for cid in cases:
            try:
                r = await run_one(arm, cid)
            except Exception as e:  # noqa: BLE001
                print(f"  {arm:11s} {cid}  FAILED {type(e).__name__}: {e}", flush=True)
                shutil.rmtree(OUT / arm / cid, ignore_errors=True)   # a failed capture leaves nothing that could be counted
                continue
            runs.append(run_summary(r))
            print(f"  {arm:11s} {cid}  {r['ruling'].get('ruling'):15s} {str(r['ruling'].get('amount')):>7s}  {r['latency_s']:5.1f}s  calls {r['model_calls']}  served by {r['provider_model_reported']}", flush=True)
    write_manifest(cases, arms, started, runs)


def run_summary(r: dict) -> dict:
    return {k: r.get(k) for k in ("arm", "case_id", "model", "latency_s", "model_calls", "requested_model", "provider_model_reported", "provider_trace_ids", "provider_response_ids")} | {
        "ruling": r["ruling"].get("ruling"), "amount": r["ruling"].get("amount"), "escalate": r["ruling"].get("escalate")}


def write_manifest(cases, arms, started, runs):
    import pydantic_ai, openai
    served = sorted({m for r in runs for m in (r.get("provider_model_reported") or [])})
    manifest = {"purpose": "audit sample: full request/response capture for a preregistered subset of the benchmark",
                "note": "requested_model is the id sent in each request; provider_model_reported is the model name the API returned in the response body, which the provider may alias",
                "requested_model": sorted({m for r in runs for m in (r.get("requested_model") or [])}), "provider_model_reported": served,
                "command": " ".join(sys.argv), "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "cases": cases, "arms": arms, "model": describe_model(), "provider_base_url": "https://api.deepseek.com (DeepSeekProvider)",
                "versions": {"python": platform.python_version(), "pydantic_ai": pydantic_ai.__version__, "openai": openai.__version__, "httpx2": httpx2.__version__},
                "redacted_headers": sorted(REDACT) + [p + "*" for p in REDACT_PREFIX], "runs": runs}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    files = sorted(p for p in OUT.rglob("*.json") if p.name != "SHA256SUMS")
    (OUT / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(OUT)}\n" for p in files))
    print(f"wrote {len(files)} files under {OUT.relative_to(ROOT)} + SHA256SUMS")


def rebuild(cases, arms):
    """Recompute run.json identifiers and the manifest from the stored call files (no model calls)."""
    runs = []
    for arm in arms:
        for cid in cases:
            d = OUT / arm / cid
            if not (d / "run.json").exists():
                continue
            r = json.loads((d / "run.json").read_text())
            calls = [json.loads(p.read_text()) for p in sorted((d / "calls").glob("*.json"))]
            r.update(summarize_calls(calls)); (d / "run.json").write_text(json.dumps(r, ensure_ascii=False, indent=1)); runs.append(run_summary(r))
    started = json.loads((OUT / "manifest.json").read_text()).get("started_at") if (OUT / "manifest.json").exists() else None
    write_manifest(cases, arms, started, runs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--rebuild", action="store_true", help="only rebuild run.json ids and manifest from stored calls")
    a = ap.parse_args()
    if a.rebuild:
        rebuild(a.cases.split(","), a.arms.split(","))
    else:
        asyncio.run(main_async(a.cases.split(","), a.arms.split(",")))


if __name__ == "__main__":
    main()
