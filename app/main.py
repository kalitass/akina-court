"""Local service: FastAPI + Server-Sent Events.

    .venv/bin/python -m uvicorn app.main:app --reload --port 8000     (loads .env if present)

    GET  /                       landing page (web/index.html); /court.html = expert court UI
    GET  /api/cases              [{case_id, type, filed_by, statement, service_type, has_run}]
    GET  /api/cases/{id}         Case JSON (map, timeline)
    GET  /api/cases/{id}/facts   FactTable (code only, instant)
    GET  /api/runs/{id}          CaseRecord of the last run (404 if none)
    POST /api/runs/{id}          start a run (idempotent while running); body {"rebuttal": true}
    GET  /api/runs/{id}/stream   SSE: replays events so far, then live until "done"
    GET  /api/policy             policy markdown
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Request, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
for _flag in ("STRETCH_PRECEDENT", "STRETCH_FRAUD", "STRETCH_SLA", "STRETCH_FEEDBACK"):
    os.environ.setdefault(_flag, "1")            # the demo service runs with every stretch module on; set 0 in .env to get the bare MVP

from core.facts.tools import build_fact_table          # noqa: E402
from core.llm import describe_model                     # noqa: E402
from core.orchestrate import run_case, save_record      # noqa: E402
from core.policy import policy_text                     # noqa: E402
from core.schemas import Case, CaseRecord, Event        # noqa: E402

app = FastAPI(title="Ryde Dispute Court")
CASES_DIR, RUNS_DIR = ROOT / "data" / "cases", ROOT / "runs"


class Run:
    def __init__(self):
        self.events: list[Event] = []
        self.done = False
        self.error: Optional[str] = None
        self.record: Optional[CaseRecord] = None
        self.subs: list[asyncio.Queue] = []

    def push(self, ev: Optional[Event]):
        if ev is not None:
            self.events.append(ev)
        for q in self.subs:
            q.put_nowait(ev)


RUNS: dict[str, Run] = {}


BENCH_DIR = ROOT / "data" / "bench" / "cases"   # the 49 benchmark cases replay on the map too (no stored court run; use Run live)


def load_case(cid: str) -> Case:
    for d in (CASES_DIR, BENCH_DIR):
        p = d / f"{cid}.json"
        if p.exists():
            return Case.model_validate(json.loads(p.read_text()))
    raise HTTPException(404, f"no case {cid}")


def bench_titles() -> dict:
    """Plain-language scenario title per benchmark case id (same map the ops page uses)."""
    try:
        from bench.ops_page import SCENARIO, humanize
        man = json.loads((ROOT / "data" / "bench" / "manifest.json").read_text())
        return {c["case_id"]: SCENARIO.get(c["name"], humanize(c["name"])) for c in man["cases"]}
    except Exception:  # noqa: BLE001
        return {}


@app.get("/api/cases")
def list_cases():
    """Demo cases (group 'demo') followed by the benchmark cases (group 'benchmark'); every one is replayable."""
    out, titles = [], bench_titles()
    for group, d, pat in (("demo", CASES_DIR, "C-*.json"), ("sample", CASES_DIR, "DISP-*.json"), ("benchmark", BENCH_DIR, "B-*.json")):
        for p in sorted(d.glob(pat)):
            c = json.loads(p.read_text())
            title = titles.get(c["case_id"]) or (f"Organisers' sample · {c['dispute']['type'].replace('_', ' ')}" if group == "sample" else None)
            out.append({"case_id": c["case_id"], "group": group, "title": title,
                        "type": c["dispute"]["type"], "filed_by": c["dispute"]["filed_by"],
                        "statement": c["dispute"]["statement"], "service_type": c["trip"]["service_type"],
                        "pickup": c["trip"]["pickup"]["name"], "dropoff": c["trip"]["dropoff"]["name"],
                        "has_run": stored_run_path(c["case_id"]) is not None, "running": c["case_id"] in RUNS and not RUNS[c["case_id"]].done})
    return out


@app.get("/api/cases/{cid}")
def get_case(cid: str, counterfactual: Optional[str] = None):
    """`cid` may be a run id like C-0005~grace_179 (the transform is applied) or a plain case id with ?counterfactual=."""
    base, _, cf = cid.partition("~")
    case = load_case(base)
    cf = cf or counterfactual
    if cf:
        from core.counterfactual import COUNTERFACTUALS, apply
        if cf in COUNTERFACTUALS:          # C-0001~fake_fact is a pre-recorded injection run: the case itself is untouched
            case = apply(case, cf)
    return case.model_dump(mode="json")


@app.get("/api/cases/{cid}/facts")
def get_facts(cid: str, counterfactual: Optional[str] = None):
    from core.schemas import Case as _Case
    return build_fact_table(_Case.model_validate(get_case(cid, counterfactual))).model_dump(mode="json")


BENCH_RUNS_DIR = ROOT / "bench" / "results" / "court"     # the benchmark's primary court run of every B-case (<id>.record.json)
STALE_STORED_RUNS = {"DISP-002"}  # archived run predates the notice and profile-window corrections


def stored_run_path(cid: str) -> Optional[Path]:
    """A run saved by this service (runs/<id>.json) or, for benchmark cases, the benchmark's own court record."""
    p = RUNS_DIR / f"{cid}.json"
    if p.exists():
        return p
    q = BENCH_RUNS_DIR / f"{cid}.record.json"
    return q if q.exists() else None


@app.get("/api/runs/{cid}")
def get_run(cid: str):
    r = RUNS.get(cid)
    if r and r.record:
        return r.record.model_dump(mode="json")
    if cid in STALE_STORED_RUNS:
        raise HTTPException(410, "This stored replay has outdated notices and profile facts. The sample case remains available, but its court run must be regenerated before it can be shown.")
    p = stored_run_path(cid)
    if p is None:
        raise HTTPException(404, "no run yet")
    return json.loads(p.read_text())


@app.get("/api/demo-controls")
def demo_controls():
    from core.counterfactual import COUNTERFACTUALS
    from core.orchestrate import INJECTIONS
    return {"inject": INJECTIONS, "counterfactual": COUNTERFACTUALS, "live_runs": LIVE_RUNS,
            "live_runs_note": None if LIVE_RUNS else "Live model runs are switched off on this public demo (no model key is deployed). Every case, audit and benchmark trip here is a stored run; clone the repository and set DEEPSEEK_API_KEY to run the agents yourself."}


def _check_token(x_demo_token: Optional[str]):
    want = os.environ.get("DEMO_TOKEN")
    if want and x_demo_token != want:
        raise HTTPException(401, "demo token required (X-Demo-Token)")


LIVE_RUNS = os.environ.get("LIVE_RUNS", "1").strip().lower() not in ("0", "false", "no", "off")   # LIVE_RUNS=0: public demo without any model key; stored runs only
MAX_LIVE = int(os.environ.get("MAX_LIVE_RUNS", "2"))            # concurrent live court runs (each is ~6 LLM calls)
RATE_PER_IP = int(os.environ.get("LIVE_RUNS_PER_IP_10MIN", "4"))  # per-client budget so a public demo cannot drain the key
_ip_hits: dict[str, list[float]] = {}


def _rate_ok(ip: str) -> bool:
    import time as _t
    now = _t.time()
    hits = [t for t in _ip_hits.get(ip, []) if now - t < 600]
    if len(hits) >= RATE_PER_IP:
        _ip_hits[ip] = hits
        return False
    _ip_hits[ip] = hits + [now]
    return True


@app.post("/api/runs/{cid}")
async def start_run(cid: str, request: Request, body: Optional[dict] = None, x_demo_token: Optional[str] = Header(default=None)):
    _check_token(x_demo_token)
    """body: {rebuttal: bool, inject: [..], counterfactual: name}. A counterfactual run is keyed cid~name and not
    saved over the real run. Live runs are capped (MAX_LIVE_RUNS, LIVE_RUNS_PER_IP_10MIN); pre-recorded runs are always free."""
    if not LIVE_RUNS:
        raise HTTPException(403, "live runs are switched off on this public demo; stored runs are unlimited (clone the repo and set DEEPSEEK_API_KEY to run the agents)")
    body = body or {}
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    if sum(1 for r_ in RUNS.values() if not r_.done) >= MAX_LIVE:
        raise HTTPException(429, f"{MAX_LIVE} live runs already in progress; watch a pre-recorded case or retry in a minute")
    if not _rate_ok(ip):
        raise HTTPException(429, f"live-run budget for this client is {RATE_PER_IP} per 10 minutes; pre-recorded cases are unlimited")
    case = load_case(cid)
    cf = body.get("counterfactual")
    if cf:
        from core.counterfactual import apply
        case = apply(case, cf)
        cid = case.case_id
    rebuttal = bool(body.get("rebuttal", True))
    inject = set(body.get("inject") or [])
    if inject and not cf:
        cid = f"{cid}~inject"                       # demo runs never overwrite the real run
    r = RUNS.get(cid)
    if r and not r.done:
        return {"status": "running", "events": len(r.events), "run_id": cid}
    r = RUNS[cid] = Run()

    async def go():
        try:
            rec = await run_case(case, on_event=r.push, rebuttal=rebuttal, inject=inject)
            r.record = rec
            if not cf and not inject:
                save_record(rec, RUNS_DIR)
        except Exception as e:  # surface the error as a terminal event instead of a silent hang
            r.error = f"{type(e).__name__}: {e}"
            r.push(Event(seq=len(r.events) + 1, ts=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                         elapsed="--:--", actor="system", kind="escalate", title="Run failed", body=r.error))
        finally:
            r.done = True
            r.push(None)
    asyncio.create_task(go())
    return {"status": "started", "model": describe_model(), "run_id": cid}


@app.get("/api/runs/{cid}/stream")
async def stream(cid: str):
    r = RUNS.get(cid)
    if r is None:
        raise HTTPException(404, "not running; POST /api/runs/{cid} first")
    q: asyncio.Queue = asyncio.Queue()
    r.subs.append(q)

    async def gen():
        try:
            for ev in list(r.events):
                yield f"event: event\ndata: {ev.model_dump_json()}\n\n"
            if r.done:
                yield "event: done\ndata: {}\n\n"
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev is None:
                    yield "event: done\ndata: {}\n\n"
                    return
                yield f"event: event\ndata: {ev.model_dump_json()}\n\n"
        finally:
            if q in r.subs:
                r.subs.remove(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/stretch")
def stretch_status():
    from core.stretch import Hooks
    return Hooks.active()


@app.get("/api/queue")
def queue():
    from core.stretch import sla
    return [q.model_dump(mode="json") for q in sla.list_queue(RUNS_DIR)]


@app.get("/api/precedents")
def precedents():
    from core.stretch import precedent
    return [p.model_dump(mode="json") for p in precedent.load(RUNS_DIR)]


@app.post("/api/override/{cid}")
def override(cid: str, body: dict, x_demo_token: Optional[str] = Header(default=None)):
    _check_token(x_demo_token)
    """Human reviewer overrides a ruling (STRETCH_FEEDBACK): body = {ruling, amount, reasoning, reviewer, note}."""
    from core.schemas import Ruling
    from core.stretch import Hooks
    r = RUNS.get(cid)
    rec = r.record if r and r.record else (CaseRecord.model_validate_json((RUNS_DIR / f"{cid}.json").read_text()) if (RUNS_DIR / f"{cid}.json").exists() else None)
    new = Ruling(ruling=body["ruling"], amount=body.get("amount"), recommended_action=body.get("recommended_action", "per reviewer"),
                 confidence=1.0, reasoning=body.get("reasoning", ""), cited_facts=[], cited_policy=[], escalate=False)
    out = Hooks(RUNS_DIR).on_human_override(cid, new, reviewer=body.get("reviewer", "reviewer"), note=body.get("note", ""), record=rec)
    return out.model_dump(mode="json") if out else {"status": "feedback flag off"}


@app.get("/api/runs/{cid}/receipt")
def receipt(cid: str):
    """Reproducibility receipt: hashes of the inputs, policy and code that produced this ruling."""
    rec = get_run(cid)
    from core.receipt import verify as verify_receipt
    from core.schemas import Case as _Case
    check = verify_receipt(rec.get("receipt"), _Case.model_validate(get_case(cid)), describe_model())
    d = rec.get("dispute") or {}
    return {"case_id": cid, "verified": check["verified"], "status": check["status"], "match": check["match"],
            "stored": check["stored"], "current": check["current"],      # the four fingerprints: case_sha256, policy_sha256, code_sha256, model
            "issued_at": (rec.get("receipt") or {}).get("issued_at"),
            "dispute": {k: d.get(k) for k in ("type", "filed_by", "statement")},
            "model": describe_model(), "fact_ids": [f["id"] for f in rec["facts"]["facts"]],
            "certificate": rec.get("certificate"), "eligibility": rec.get("eligibility"),
            "ruling": {k: rec["ruling"][k] for k in ("ruling", "amount", "recommended_action", "cited_facts", "cited_policy", "escalate")},
            "appeal": "Reply to the notice within 30 days (NS-7); a human reviewer re-opens the case with this receipt."}


@app.get("/policy-sources.md", response_class=PlainTextResponse)
def policy_sources():
    """Document source for every policy clause (policy/sources.md, served as text)."""
    return (ROOT / "policy" / "sources.md").read_text(encoding="utf-8")


@app.get("/api/policy", response_class=PlainTextResponse)
def get_policy():
    return policy_text()


@app.get("/api/health")
def health():
    return {"ok": True, "model": describe_model(), "provider": os.environ.get("LLM_PROVIDER", "deepseek"), "live_runs": LIVE_RUNS}


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.middleware("http")
async def no_stale_pages(request, call_next):
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith((".html", ".js", ".css", ".json", ".md")):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
