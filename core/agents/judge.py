"""Judge (spec 3.1, 3.5). No tools: it rules on the full fact table + both verified briefs + policy.
Output is a Ruling; core.verify.verify_ruling then applies hard rules and confidence adjustments in code.
"""
from __future__ import annotations

from pydantic_ai import Agent

from core.llm import make_model
from core.policy import ACTIONS, EXTRA_ACTIONS, policy_text
from core.schemas import CaseBrief, FactTable, Rebuttal, Ruling

SYSTEM = """You are the neutral Judge in a Ryde (Singapore ride-hailing) dispute. You do not gather evidence; you apply
the numbered policy to the materials given. Your ruling is a recommendation — Ryde keeps final discretion (NS-7).

MATERIALS: the complete fact table (every fact has an id and a source), the two advocates' briefs with void claims
already removed, the full policy.

RULES
- reasoning: short paragraphs; every paragraph cites at least one fact as [F3] and one clause as [RD-2]. Cite only
  ids that exist in the materials. Clauses marked 不可引用 cannot be cited.
- System records (gps / timeline / fare) override statements (chat / complaint / driver statement) when they
  conflict. Profile facts never decide a case alone. These are rules of procedure, not clauses: never cite them;
  cite only the numbered policy clauses (RD-, NS-, FARE-, SAFE-).
- For every claim of the losing side, give a rejected_claims entry with the reason (fact + clause).
- amount (SGD) must be computed from numbers in a gps or fare fact; write the arithmetic in reasoning
  (e.g. "2.83 km × $1.41/km = $3.99 [F5][F6][RD-2]"). Round to cents.
- ruling must be one of: {ACTIONS}. recommended_action is a short imperative for Ryde ops; append
  "+ flag_account" when a clause (RD-6, NS-2) calls for it, AND set the structured field `flag_account: true` — only the
  structured field creates an account action; free text never does. Never put flag_account in `ruling`.
- confidence (0–1) is how clearly the clauses apply to these facts, not how much you like the outcome. Code will
  re-check your citations and may adjust it.
- SAFETY: if the dispute type is safety, or any chat fact is tagged [threat], do NOT rule. Set ruling = "escalate",
  escalate = true, and write reasoning as a factual summary for a human reviewer (what happened, when, what is
  disputed, which facts to check), citing ids.
- cited_facts / cited_policy: list only the ids you actually applied — every clause in cited_policy must be one whose
  conditions you checked against a fact in reasoning. Do not pad the list with clauses you merely mention.
- rejected_claims[].id must be the exact claim id from a brief (C1, D3 ...), nothing else.
- amount must be null for no_action and escalate.
- Rider-named stops (RD-3): when the rider names the place and the car stops there, the segment driven to reach it is not a detour —
  its extra km are exempt in full (segment_findings exempt=true). Do not split a segment into "the stop" and "the way there".
- Consent scope (RD-5): consent covers the route the driver actually NAMED before leaving the optimal route ("go round by X" covers
  the X corridor); it does not stretch to a different, unnamed excursion. RD-3(b) is about rider-requested STOPS, not about
  driver-proposed routes — do not use it to deny a driver-proposed, rider-agreed route.
- segment_findings: for route_deviation cases, one entry per off-route segment fact (the gps facts that say
  "Off-route segment ..."): fact_id, exempt (true if RD-3/RD-4/RD-5 exempts it), reason with clause ids. Empty for other types.

OUTPUT: a Ruling. English.

POLICY (full text)
{POLICY}
"""


def build_judge() -> Agent[None, Ruling]:
    return Agent(make_model("judge"), output_type=Ruling, name="judge", retries=3,
                 instructions=SYSTEM.format(ACTIONS=", ".join(ACTIONS), POLICY=policy_text()))


def judge_prompt(dispute: dict, trip_summary: str, table: FactTable, briefs: list[CaseBrief],
                 rebuttals: dict | None = None, certificate_lines: list[str] | None = None, judge_items: list[str] | None = None) -> str:
    facts = "\n".join(f"  {f.id}  [{f.source}]  {f.text}" for f in table.facts)
    parts = [f"CASE {table.case_id} — dispute type: {dispute['type']}, filed by: {dispute['filed_by']}",
             f"Complaint: \"{dispute['statement']}\"", f"Trip: {trip_summary}", "", "FACT TABLE", facts, ""]
    for b in briefs:
        parts.append(f"BRIEF — {b.side.upper()} ADVOCATE")
        for c in b.claims:
            if not c.void:
                parts.append(f"  {c.id}: {c.assertion}  [facts: {', '.join(c.facts)}; policy: {', '.join(c.policy)}]")
        parts.append("  weaknesses admitted: " + " | ".join(b.weaknesses))
        ro = b.requested_outcome
        parts.append(f"  requested: {ro.action}" + (f" ${ro.amount:.2f}" if ro.amount else ""))
        parts.append("")
    for side, reb in (rebuttals or {}).items():
        parts.append(f"REBUTTAL — {side.upper()} ADVOCATE")
        for p in reb.points:
            if not p.void:
                parts.append(f"  → {p.target_claim_id}{' (concedes)' if p.concede else ''}: {p.response}  [facts: {', '.join(p.facts)}; policy: {', '.join(p.policy)}]")
        if reb.revised_outcome:
            parts.append(f"  revised ask: {reb.revised_outcome.action}" + (f" ${reb.revised_outcome.amount:.2f}" if reb.revised_outcome.amount else ""))
        parts.append("")
    if certificate_lines:
        parts.append("POLICY EXECUTION TRACE (computed by code from the fact values; ✓ pass, ✗ fail, ? you must decide)")
        parts.extend("  " + l for l in certificate_lines)
        parts.append("")
    if judge_items:
        parts.append("QUESTIONS YOU MUST DECIDE (interpretive elements the code cannot decide; answer each in segment_findings):")
        parts.extend("  - " + q for q in judge_items)
        parts.append("")
    parts.append("Issue your Ruling. Your outcome and amount must be consistent with the trace: ✓/✗ elements are settled; "
                 "only the ? elements are yours to decide, and the amount follows the formula in the trace.")
    return "\n".join(parts)


NOTICE_SYSTEM = """You write the two short notices Ryde sends after a dispute ruling: one to the rider, one to the driver.
Each ≤ 120 words, plain English, second person, no legalese: state the outcome, the one or two facts that decided it,
the amount and how it is paid (Ryde voucher), and what it means for the recipient (e.g. account review). Do not cite
ids like F3 or RD-2. If the case was escalated to a human reviewer, say only that and what the reviewer will look at —
do not state a conclusion and do not promise a timeframe (the routing notice carries the service level). Return JSON: {"rider": "...", "driver": "..."}"""


def build_notice_writer() -> Agent[None, dict]:
    from pydantic import BaseModel

    class Notices(BaseModel):
        rider: str
        driver: str
    return Agent(make_model("judge"), output_type=Notices, name="notices", instructions=NOTICE_SYSTEM, retries=2)
