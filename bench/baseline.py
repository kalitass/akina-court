"""Baseline arms: ONE LLM call, no advocates, no citation check, no code verification.

    raw         the raw Case JSON (gps thinned to every 6th point so it fits the context, everything else verbatim)
                + the full policy text -> Ruling
    facts_only  the fact table (core.facts.tools.build_fact_table, the same text the court's judge reads) + the full
                policy -> Ruling. Separates "code computes the facts" from "court process" in the ablation.

Both use core.llm.make_model("judge") and pydantic-ai structured output (output_type=Ruling), like the court's judge.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache

from pydantic_ai import Agent

from core.facts.tools import build_fact_table
from core.llm import make_model
from core.policy import ACTIONS, policy_text
from core.schemas import Case, Ruling

GPS_THIN = 6


def usage_of(res):
    """RunUsage of an AgentRunResult (a property in pydantic-ai 2.x, a method in 1.x)."""
    u = res.usage
    return u() if callable(u) else u

COMMON_RULES = """RULES
- ruling must be one of: {ACTIONS}. amount (SGD, 2 decimals) only for refund_full / refund_partial / fee_waived,
  null for no_action and escalate. recommended_action is a short imperative for Ryde ops; append "+ flag_account"
  when a clause (RD-6, NS-2) calls for it and set the structured field `flag_account: true` (only that field counts).
  Never put flag_account in `ruling`.
- cited_policy: the clause ids (e.g. RD-2, NS-1) whose conditions you actually applied. Clauses marked 不可引用
  cannot be cited. cited_facts: leave empty unless you were given fact ids.
- reasoning: short paragraphs with the arithmetic for any amount. confidence 0-1.
- System records (gps / timeline / fare) override statements (chat / complaint / driver statement) when they
  conflict. Profile facts never decide a case alone. These are rules of procedure, not clauses: never cite them.
- SAFETY: if the dispute type is safety, or any chat message contains a threat / intimidation keyword (threat, threaten, kill, hurt, hit you, beat you, punch, slap, lock the door,
  lock you, find you, shut up, idiot, stupid, harass),
  do NOT rule: ruling = "escalate", escalate = true, reasoning = factual summary for a human reviewer.
- segment_findings: for route_deviation cases, one entry per off-route segment you identify (fact_id = the fact id
  if you were given one, else "seg1", "seg2" ...), exempt true/false, reason with clause ids. Empty otherwise.

OUTPUT: a Ruling. English.

POLICY (full text)
{POLICY}
"""

SYSTEM_RAW = """You are the dispute-resolution judge for Ryde (Singapore ride-hailing). You receive the COMPLETE RAW CASE
RECORD as JSON: the dispute ticket, trip timeline, quoted route (polyline + km), the driver's GPS trace (5 s samples,
thinned to every {THIN}th point), LTA speed bands and incidents, weather, the fare breakdown, the in-app chat, the
driver's statement and both parties' 90-day profiles. Nobody has pre-computed anything: distances, times, who was
where when, and what was agreed are for you to work out from the record. Apply the numbered policy below and rule.

""" + COMMON_RULES

SYSTEM_FACTS = """You are the dispute-resolution judge for Ryde (Singapore ride-hailing). You receive the ticket and a FACT
TABLE computed by code from the trip record (every fact has an id F1..Fn and a source: gps, timeline, fare, chat,
traffic, weather, profile). Apply the numbered policy below to these facts and rule. Cite fact ids as [F3] in
reasoning and list them in cited_facts.

""" + COMMON_RULES


def thin_case(case: Case) -> dict:
    """Raw Case JSON for the prompt: gps every GPS_THIN-th sample (last sample kept), everything else verbatim."""
    d = json.loads(case.model_dump_json(by_alias=True, exclude={"provenance"}))
    gps = d["gps"]
    d["gps"] = gps[::GPS_THIN] + ([gps[-1]] if (len(gps) - 1) % GPS_THIN else [])
    d["_note"] = f"gps thinned to every {GPS_THIN}th sample ({len(d['gps'])} of {len(gps)} points, 5 s grid -> {5 * GPS_THIN} s)"
    return d


def fact_table_text(case: Case) -> str:
    table = build_fact_table(case)
    return "\n".join(f"  {f.id}  [{f.source}]  {f.text}" for f in table.facts)


@lru_cache(maxsize=4)
def build_baseline(arm: str) -> Agent[None, Ruling]:
    system = {"raw": SYSTEM_RAW.format(THIN=GPS_THIN, ACTIONS=", ".join(ACTIONS), POLICY=policy_text()),
              "facts_only": SYSTEM_FACTS.format(ACTIONS=", ".join(ACTIONS), POLICY=policy_text())}[arm]
    return Agent(make_model("judge"), output_type=Ruling, name=f"baseline_{arm}", retries=3, instructions=system)


def baseline_prompt(case: Case, arm: str) -> str:
    d = case.dispute
    head = (f"CASE {case.case_id} — dispute type: {d.type}, filed by: {d.filed_by}\n"
            f"Complaint: \"{d.statement}\"\n")
    if arm == "raw":
        return head + "\nRAW CASE RECORD (JSON)\n" + json.dumps(thin_case(case), ensure_ascii=False, separators=(",", ":")) + "\n\nIssue your Ruling."
    t = case.trip
    trip = (f"{t.service_type} {t.pickup.name} → {t.dropoff.name}, estimate {t.estimated_km:.1f} km / {t.estimated_min:.0f} min"
            + (f", cancelled by {t.cancelled_by} at {t.cancelled_at:%H:%M:%S}" if t.cancelled_at else f", pickup {t.pickup_at:%H:%M} drop-off {t.dropoff_at:%H:%M}"))
    return head + f"Trip: {trip}\n\nFACT TABLE\n" + fact_table_text(case) + "\n\nIssue your Ruling."


async def run_baseline(case: Case, arm: str) -> dict:
    """One structured call. Returns {ruling, latency_s, input_tokens, output_tokens, requests}."""
    agent = build_baseline(arm)
    t0 = time.monotonic()
    res = await agent.run(baseline_prompt(case, arm))
    u = usage_of(res)
    return {"ruling": res.output.model_dump(), "latency_s": round(time.monotonic() - t0, 2),
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "requests": u.requests}
