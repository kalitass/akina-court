"""The batch chain, rehearsed without a model: scripted stand-ins play the advocates, the judge and the notice writer.

  * scripts/run_case.py's path: run_case → save → CaseRecord.load → the receipt verifies against today's code and policy
  * a counterfactual (grace_179) runs through the same path and lands on the outcome its name promises
  * bench/run_bench.run_one writes every Ruling field with ruling_schema 2 for a single-call arm and for the court
  * a judge outage inside the court is saved as a FAILED run (ok: false), never as a decision
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import bench.baseline as baseline
import bench.run_bench as rb
import core.agents.advocate as adv
import core.orchestrate as orch
from core.counterfactual import apply
from core.facts.tools import build_fact_table
from core.orchestrate import run_case, save_record
from core.policy_engine import evaluate
from core.receipt import verify as verify_receipt
from core.schemas import Case, CaseBrief, CaseRecord, Rebuttal, Ruling

ROOT = Path(__file__).resolve().parents[1]
MODEL = "offline:scripted"
CUR: dict = {}


def _after_tools(messages):
    return any(isinstance(p, (ToolReturnPart, RetryPromptPart)) for m in messages if isinstance(m, ModelRequest) for p in m.parts)


def advocate_fn(side):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        table = CUR["table"]
        if not _after_tools(messages):
            want = {"route_deviation": "get_route_facts", "no_show": "get_no_show_facts", "safety": "get_chat_facts"}[table.dispute_type]
            names = [t.name for t in info.function_tools]
            return ModelResponse(parts=[ToolCallPart(tool_name=n, args={"case_id": table.case_id}) for n in (want, "get_chat_facts", "get_fare_facts") if n in names])
        seen = [f.id for f in table.facts if f.source in ("gps", "timeline", "fare", "chat")]
        pre, cl = ("C", "RD-1") if side == "rider" else ("D", "NS-1")
        cl = "NS-1" if table.dispute_type == "no_show" else cl
        is_reb = any("points" in str(t.parameters_json_schema) for t in info.output_tools)
        if is_reb:
            d = {"side": side, "points": [{"target_claim_id": "D1" if side == "rider" else "C1", "response": f"Disputed [{seen[0]}][{cl}]", "facts": [seen[0]], "policy": [cl], "concede": False}], "revised_outcome": None}
        else:
            d = {"side": side, "claims": [{"id": f"{pre}1", "assertion": "claim one", "facts": [seen[0]], "policy": [cl]}],
                 "weaknesses": [f"{seen[0]} cuts against us"], "requested_outcome": {"action": "refund_full" if side == "rider" else "no_action", "amount": None}}
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=d)])
    return fn


def scripted_ruling() -> dict:
    """A ruling that follows the stored expected answer, with segment findings consistent with the certificate (the
    smallest set of exempt open segments that reproduces the expected amount)."""
    import itertools
    from core.policy_engine import expected_amount
    table, cert, exp = CUR["table"], CUR["cert"], CUR["expected"]
    fids = [f.id for f in table.facts]
    d = dict(ruling=exp["ruling"], amount=exp.get("amount"), recommended_action="per expected", confidence=0.85,
             reasoning=f"Per the trace [{fids[0]}][{exp['cited_policy'][0]}].", cited_facts=[fids[0]], cited_policy=list(exp["cited_policy"]),
             rejected_claims=[], flag_account=bool(cert.flag_required), segment_findings=[], safety_concern="none", safety_basis=[],
             evidence_status="sufficient", evidence_gap=None, escalate=bool(exp.get("escalate")), escalation_reason=None)
    if table.dispute_type == "safety":
        d.update(ruling="escalate", escalate=True, safety_concern="confirmed", safety_basis=[fids[0]], amount=None)
    if cert.insufficient:
        d.update(ruling="escalate", escalate=True, amount=None, evidence_status="insufficient", evidence_gap=cert.insufficient)
    if cert.segments:
        open_ = [f for f, sg in cert.segments.items() if sg["exempt"] is None]
        findings = {f: ("exempt" if sg["exempt"] else "counts") for f, sg in cert.segments.items() if sg["exempt"] is not None}
        best = None
        for k in range(len(open_) + 1):
            for sub in itertools.combinations(open_, k):
                amt = expected_amount(cert, {f: (f in sub) for f in open_})
                if cert.rate_per_km is None or amt is None or abs((amt or 0) - (exp.get("amount") or 0)) < 0.011:
                    best = sub; break
            if best is not None:
                break
        for f in open_:
            findings[f] = "exempt" if (best is not None and f in best) else "counts"
        sf = []
        for f, fd in findings.items():
            start = cert.segments[f]["start"]
            basis = [cid for cid, c in cert.chat_index.items() if c["from"] == "rider" and not c["statement"] and c["ts"] and c["ts"] < start]
            ground = {"exempt": "general_route_consent", "counts": "consent_after_or_none", "undetermined": "named_road_untied"}[fd]
            sf.append({"fact_id": f, "finding": fd, "ground": ground, "basis": basis[:1] if fd == "exempt" else [], "reason": f"[RD-5] {fd} per record [{fids[0]}]"})
        d["segment_findings"] = sf
        d["flag_account"] = bool(cert.flag_required) if cert.flag_required is not None else bool(cert.flag_conditional and any(v == "counts" for v in findings.values()))
    if d["flag_account"]:
        d["recommended_action"] += " + flag_account"
    if d["ruling"] in ("no_action", "escalate"):
        d["amount"] = None
    return d


def judge_fn(messages, info: AgentInfo) -> ModelResponse:
    if CUR.get("outage"):
        raise RuntimeError("status_code: 402, Insufficient Balance")
    return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=scripted_ruling())])


def notice_fn(messages, info: AgentInfo) -> ModelResponse:
    amt = CUR["expected"].get("amount")
    txt = f"Outcome recorded. You receive ${amt:.2f} as a Ryde voucher." if amt else "Outcome recorded; no amount is due."
    return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"rider": txt, "driver": txt})])


class Notices(BaseModel):
    rider: str
    driver: str


def _advocate(side, output):
    agent = Agent(FunctionModel(advocate_fn(side)), deps_type=adv.AdvocateDeps, output_type=output, instructions="x", name=f"{side}_x", retries=3)
    for name in adv.TOOL_SOURCES:
        agent.tool(adv._make_tool(name))
    adv.SYSTEM_CACHE[side] = "x"
    return agent


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.setattr(orch, "build_advocate", lambda side: _advocate(side, CaseBrief))
    monkeypatch.setattr(orch, "build_rebutter", lambda side, agent: _advocate(side, Rebuttal))
    monkeypatch.setattr(orch, "build_judge", lambda: Agent(FunctionModel(judge_fn), output_type=Ruling, name="judge", retries=3, instructions="x"))
    monkeypatch.setattr(orch, "build_notice_writer", lambda: Agent(FunctionModel(notice_fn), output_type=Notices, name="notices", instructions="x", retries=2))
    monkeypatch.setattr(orch, "describe_model", lambda: MODEL)
    monkeypatch.setattr(rb, "describe_model", lambda: MODEL)
    monkeypatch.setattr(baseline, "build_baseline", lambda arm: Agent(FunctionModel(judge_fn), output_type=Ruling, name=f"baseline_{arm}", retries=3, instructions="x"))
    CUR.clear()
    yield


def prime(case: Case, expected: dict):
    table = build_fact_table(case)
    CUR.update(case=case, table=table, cert=evaluate(case, table), expected=expected)


def test_run_case_path_saves_loads_and_the_receipt_verifies(scripted, tmp_path):
    case = Case.model_validate(json.loads((ROOT / "data" / "cases" / "C-0004.json").read_text()))
    exp = json.loads((ROOT / "data" / "expected" / "C-0004.json").read_text())
    prime(case, exp)
    rec = asyncio.run(run_case(case))
    assert rec.status == "resolved" and rec.ruling.ruling == exp["ruling"] and rec.ruling.amount == exp["amount"]
    assert rec.ruling.flag_account and any(a["type"] == "flag_account" for a in rec.eligibility["actions"])
    assert rec.ruling.segment_findings == []                               # none on a no-show, whatever the judge wrote
    assert all(f"${exp['amount']:.2f}" in n.text for n in rec.notices)      # notice amount = ruling amount
    p = save_record(rec, tmp_path)
    back = CaseRecord.load(p)
    check = verify_receipt(back.receipt, case, MODEL)
    assert check["verified"], check


def test_counterfactual_runs_through_the_same_path(scripted):
    base = Case.model_validate(json.loads((ROOT / "data" / "cases" / "C-0005.json").read_text()))
    cf = apply(base, "grace_179")
    prime(cf, {"ruling": "refund_full", "amount": evaluate(cf, build_fact_table(cf)).fee, "cited_policy": ["NS-0", "NS-4"], "escalate": False})
    rec = asyncio.run(run_case(cf))
    assert rec.ruling.ruling == "refund_full" and rec.status == "resolved"


def test_bench_runner_saves_every_field_and_marks_an_outage_failed(scripted, tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "RESULTS", tmp_path); monkeypatch.setattr(rb, "ROOT", tmp_path)   # record paths are stored relative to ROOT
    cid = "B-0034"
    case = rb.load_case(cid, False)
    prime(case, json.loads((ROOT / "data" / "bench" / "expected" / f"{cid}.json").read_text()))
    for arm in ("facts_only", "court"):
        rec = asyncio.run(rb.run_one(arm, cid, 0, False, 120.0, True))
        assert rec["ok"] and rec["ruling_schema"] == 2, rec.get("error")
        assert set(Ruling.model_fields) <= set(rec["ruling"]), set(Ruling.model_fields) - set(rec["ruling"])
    CUR["outage"] = True
    rec = asyncio.run(rb.run_one("court", cid, 0, False, 120.0, True))
    assert not rec["ok"] and "outage" in rec["error"] and rec["ruling"]["safety_concern"] == "unscreened"


# ---------------------------------------------------------------------------- the eight pre-recorded demos show what their names say

def _demo_expected(cid: str, cf: str | None):
    base = json.loads((ROOT / "data" / "expected" / f"{cid}.json").read_text())
    if cf == "grace_179":
        return {**base, "ruling": "refund_full", "amount": 6.61, "cited_policy": ["NS-0", "NS-4"], "escalate": False}
    if cf == "grace_181":
        return {**base, "ruling": "no_action", "amount": None, "cited_policy": ["NS-0", "NS-4"], "escalate": False}
    return base


@pytest.mark.parametrize("name", ["fake_fact", "fake_clause", "wrong_amount", "flag_text", "prompt_injection", "swap_profiles", "grace_179", "grace_181"])
def test_each_prerecorded_demo_shows_its_named_effect(scripted, name):
    sys.path.insert(0, str(ROOT / "scripts"))
    import prerecord_demos
    cid, spec = prerecord_demos.DEMOS[name]
    case = Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))
    if spec.get("cf"):
        case = apply(case, spec["cf"]).model_copy(update={"case_id": f"{cid}~{spec['cf']}"})
    exp = _demo_expected(cid, spec.get("cf"))
    prime(case, exp)
    rec = asyncio.run(run_case(case, inject=spec.get("inject")))
    r = rec.ruling
    titles = [e.title for e in rec.events]
    if name == "fake_fact":
        voided = [c for e in rec.events if e.kind == "brief" and e.brief for c in e.brief.claims if c.void]
        assert any("F99" in (c.void_reason or "") for c in voided) and r.ruling == exp["ruling"] and r.amount == exp["amount"]
    elif name == "fake_clause":
        assert any("citation check failed" in t.lower() for t in titles) and r.ruling == exp["ruling"] and r.amount == exp["amount"]
    elif name == "wrong_amount":
        assert r.escalate and r.amount is None and all("$" not in n.text and "voucher" not in n.text.lower() for n in rec.notices)
        assert any("amount" in (r.escalation_reason or "") for _ in [0])
    elif name == "flag_text":
        assert not r.flag_account and not any(a["type"] == "flag_account" for a in rec.eligibility["actions"]) and r.ruling == exp["ruling"]
    elif name == "prompt_injection":
        assert any("$99" in f.text or "ignore" in f.text.lower() for f in rec.facts.facts) and r.ruling == exp["ruling"] and r.amount == exp["amount"]
    elif name == "swap_profiles":
        assert r.ruling == exp["ruling"] and r.amount == exp["amount"] and not r.flag_account      # RD-6 reads the driver's own record: no prior after the swap
    elif name == "grace_179":
        assert r.ruling == "refund_full" and r.amount == 6.61
    elif name == "grace_181":
        assert r.ruling == "no_action"
    assert rec.receipt and verify_receipt(rec.receipt, case, MODEL)["verified"]
