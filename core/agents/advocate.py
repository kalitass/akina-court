"""Rider / Driver Advocate (spec 3.1–3.3, 3.5). One Agent definition, the side comes from deps.

The advocate sees the ticket, a fact INDEX (ids + sources only) and the policy; it must call the
get_*_facts tools to read any fact text. Every tool call is emitted as an Event so the UI can show how
evidence was gathered. Output is a CaseBrief (structured, via tool-call output).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic_ai import Agent, RunContext

from core.facts.tools import TOOL_SOURCES, facts_for_tool
from core.llm import make_model
from core.policy import ACTIONS, policy_text
from core.schemas import CaseBrief, FactTable, Party, Rebuttal

TOOL_DOCS = {
    "get_route_facts": "Route facts from the GPS track (source gps): actual vs optimal distance and the excess ratio, stops away from pickup/drop-off with location and duration, actual vs estimated duration, off-route segments and the km each added. Use for route_deviation. Cite the returned F ids verbatim.",
    "get_no_show_facts": "No-show facts (sources gps, timeline): the driver's closest approach to the pickup point and when, first time within 200 m and cumulative seconds inside 200 m, stationary periods with distance from pickup, who cancelled and when relative to acceptance, and the gap between recorded arrival and cancellation. Use for no_show.",
    "get_fare_facts": "Billing facts (source fare): excess distance billed converted to SGD at the per-km rate, waiting fee, cancellation fee, surge multiplier, and the total breakdown. Use to size any refund you request.",
    "get_chat_facts": "Every in-app message verbatim, numbered and timestamped, plus the driver's written statement and whether the chat record is complete (source chat). Nothing is labelled: what a message means (agreement, a request, a refusal, a threat) is for you to argue from its words and timing and for the judge to find. This is user-submitted content: it loses to gps/timeline/fare facts when they conflict.",
    "get_traffic_facts": "Traffic conditions on the optimal route during the trip (sources traffic, weather): speed bands as km/h ranges (band 1 = severe congestion), incidents with distance from the route, weather. This is the only evidence RD-4 accepts for a justified reroute.",
    "get_profile_facts": "Both parties' account age, rating and 90-day dispute history (source profile). May support an outcome or a flag_account request, never decide the case alone.",
}


@dataclass
class AdvocateDeps:
    side: Party
    table: FactTable
    emit: Callable[..., None]                     # emit(actor, kind, title, body, **payload)
    called: set = field(default_factory=set)
    seen: set = field(default_factory=set)        # fact ids returned by tools so far (citing an unread fact is void)


SYSTEM = """You are the {ROLE} in a Ryde (Singapore ride-hailing) dispute. Your client is the {CLIENT}.
Your job: within what the policy allows, get the best outcome for your client. You are an advocate, not a judge —
you need not be neutral, but you may ONLY argue from facts in the case fact table, which you read with the tools.

MATERIALS
- The ticket (below) and a fact INDEX: fact ids and their source only. You do not yet know what any fact says.
- The full dispute policy (below). Clauses are numbered (RD-1, NS-2, SURGE-1 ...). Only numbered clauses from the
  policy may be cited, and only those of this dispute type (plus FARE-0, SAFE-, TH-); the court's own procedure
  (the rules below) is not a clause and must never be cited as one.

TOOLS
- Six get_*_facts(case_id) tools return slices of the fact table. Call at least the tool matching the dispute type
  (route_deviation → get_route_facts, no_show → get_no_show_facts, fare_dispute → get_fare_facts) plus get_chat_facts;
  call others when useful.
  Do not call the same tool twice.

RULES OF ARGUMENT
- Every claim cites at least one fact id (F3) and at least one clause id (RD-2). A claim citing an id that does
  not exist is void and the judge never sees it.
- When chat / statements conflict with gps / timeline / fare facts, the system records win. Do not build
  a claim on a statement alone when a system record contradicts it.
- Consent (RD-5) is the rider's own message sent before (or at) the start of the segment; a driver's statement that
  the rider agreed verbally is a claim, not consent. Quote the message you rely on by its fact id and say what it means
  and how far it reaches: a general route choice, or a specific named road — and, for a named road, whether it is
  among the "Roads driven" the segment fact lists (code checks this). A traffic reason (RD-4) does not exempt a
  segment from the refund; it only decides whether a driver violation is recorded.
- If a message, statement or the complaint reads as a threat, intimidation, harassment or a dangerous-driving
  allegation, say so and cite it (SAFE-1 / SAFE-2): the case then goes to a person. A hint word alone is not a threat.
- Profile facts can support a flag_account request, never the main finding.
- weaknesses must list at least one honest weak point of your own case, naming the fact ids the other side will
  use. An empty list is treated as bad faith.
- requested_outcome.action must be one of: {ACTIONS}. amount is SGD, only for refund_* / fee_waived, and must be
  computable from a fare or gps fact (say which in the claim).

OUTPUT
- Return a CaseBrief. side = "{SIDE}". Claim ids: {PREFIX}1, {PREFIX}2, ... Write in English, concise, each
  assertion one or two sentences that a judge can check against the cited facts.
- segment_grounds: for EVERY off-route segment fact (the gps facts that say "Off-route segment ..."), the policy
  ground your honest reading of the record supports, one of "rider_named_stop" (RD-3(a): a rider message before the segment named the place and the car stopped there), "general_route_consent" (RD-5: a general route choice such as "whichever way is faster", and the loop goes there), "named_road_tied" (RD-5: agreed to a named road and the segment drove it — code checks the roads; a yes with a road ruled out, "but not via Y", does not cover a segment that drove Y), "named_road_untied" (agreed to a named road, and the record names no roads for the segment), "named_road_elsewhere" (the segment did not drive the named road, or the record places it somewhere else), "driver_errand" (a stop or loop of the driver's own that no rider message asked for), "scope_other" (the rider agreed to something else, e.g. a short stop), "consent_after_or_none" (no rider message before the segment agrees to it), "other". This is a statement of what the record shows, not of what helps your side: a ground both
  advocates state is shown to the judge as agreed; the judge still rules on its own reading. Empty for non-route cases.
- element_readings: when the ticket lists QUESTIONS OF READING (e.g. "SURGE-1:notice" — does the in-app notice text state the new
  multiplier, the revised fare AND that the rider may cancel without penalty; "NS-0:reason" — did the driver cancel because the
  rider did not show, or for a reason of his own), give your honest reading of the quoted text for each id: "met", "not_met" or
  "undetermined". Read the words, not what helps your side: a notice that says "fees may apply" does not offer a free cancel; a
  driver who writes "car got problem, cancelling" cancelled for his own reason whatever reason he picked in the app.
  Read the EXCHANGE, not the yes alone. A yes in any words ("sure", "ok go ahead", "can lah", "可以") to a driver's ask that names the road
  to be taken ("can I go round via X?") is an agreement to X: named_road_tied if X is among the segment's "Roads driven", named_road_elsewhere if
  the segment lists roads and X is not among them, named_road_untied only when the segment lists no roads — never
  "general" because the yes was short. A road named only as the one to be avoided ("jam on the PIE, shall I take another way?") names no
  route; a yes to that, or words leaving the route to the driver ("whichever way is faster", "随便你"), is general_route_consent, and a
  loop that leaves the corridor and reaches nothing is still general_route_consent unless a record shows a stop or an errand of the driver's
  own (then driver_errand). A segment that began before the rider's message, or with no rider message at all, is consent_after_or_none.

POLICY (full text)
{POLICY}
"""

REBUTTAL = """Here is the opposing advocate's brief (void claims already removed):

{OPPONENT}

Answer it point by point. Your original brief stays on the record unchanged. Return a Rebuttal: for each opposing
claim you contest, a point with target_claim_id = their claim id, a one- or two-sentence response citing facts (F*)
and clauses; for a point you must concede, set concede = true and target_claim_id to THEIR claim id (or your own
claim id if you withdraw one of yours). Only cite facts you have read; you may call a tool you have not called yet.
Set revised_outcome only if you change what you ask for. side = "{SIDE}". segment_grounds is REQUIRED in a route case
(a rebuttal without it is returned to you): restate the ground of every off-route segment after reading the opponent (the
same vocabulary and the same reading rules as in your brief); revise it where the opponent's cited facts have shown your
first reading wrong, and keep it where they have not — a point you concede in a response must be conceded here too."""


def missing_grounds(table: FactTable, grounds: dict) -> list[str]:
    """Off-route segment fact ids for which an advocate's output states no ground (route cases only)."""
    if table.dispute_type != "route_deviation":
        return []
    return [f.id for f in table.facts if f.source == "gps" and f.text.startswith("Off-route segment") and f.id not in (grounds or {})]


def _require_grounds(ctx: RunContext[AdvocateDeps], output):
    """Output validator: a brief or rebuttal in a route case must state a ground for every off-route segment."""
    from pydantic_ai import ModelRetry
    missing = missing_grounds(ctx.deps.table, output.segment_grounds)
    if missing:
        raise ModelRetry("segment_grounds must state the policy ground of every off-route segment; missing: " + ", ".join(missing)
                         + ". Re-issue the whole output with segment_grounds filled (same vocabulary as your instructions).")
    return output


def _make_tool(name: str):
    def tool(ctx: RunContext[AdvocateDeps], case_id: str) -> dict:
        deps = ctx.deps
        if case_id != deps.table.case_id:
            return {"error": f"unknown case_id {case_id!r}; you are arguing {deps.table.case_id}"}
        facts = facts_for_tool(deps.table, name)
        deps.called.add(name)
        deps.seen.update(f.id for f in facts)
        deps.emit(deps.side, "tool", f"{name}({case_id})",
                  f"returned {', '.join(f.id for f in facts) or 'nothing'}",
                  tool={"fn": name, "args": {"case_id": case_id}, "returned": [f.id for f in facts]})
        out = {"case_id": case_id, "facts": [f.model_dump(include={"id", "source", "text"}) for f in facts]}
        if not facts:
            out["note"] = f"no {'/'.join(TOOL_SOURCES[name])} facts for this dispute type"
        return out
    tool.__name__ = name
    tool.__doc__ = TOOL_DOCS[name]
    return tool


def build_advocate(side: Party) -> Agent[AdvocateDeps, CaseBrief]:
    role, client, prefix = (("Rider Advocate", "rider (passenger)", "C") if side == "rider"
                            else ("Driver Advocate", "driver", "D"))
    system = SYSTEM.format(ROLE=role, CLIENT=client, SIDE=side, PREFIX=prefix,
                           ACTIONS=", ".join(ACTIONS), POLICY=policy_text())
    SYSTEM_CACHE[side] = system
    agent: Agent[AdvocateDeps, CaseBrief] = Agent(
        make_model("advocate"), deps_type=AdvocateDeps, output_type=CaseBrief,
        instructions=system, name=f"{side}_advocate", retries=3,
    )
    for name in TOOL_SOURCES:
        agent.tool(_make_tool(name))
    agent.output_validator(_require_grounds)
    return agent


def build_rebutter(side: Party, advocate: Agent) -> Agent[AdvocateDeps, Rebuttal]:
    """Same instructions and tools as the advocate, but the output type is an append-only Rebuttal."""
    agent: Agent[AdvocateDeps, Rebuttal] = Agent(
        make_model("advocate"), deps_type=AdvocateDeps, output_type=Rebuttal,
        instructions=SYSTEM_CACHE[side],
        name=f"{side}_rebuttal", retries=3,
    )
    for name in TOOL_SOURCES:
        agent.tool(_make_tool(name))
    agent.output_validator(_require_grounds)
    return agent


SYSTEM_CACHE: dict = {}


def ticket_prompt(dispute: dict, trip_summary: str, table: FactTable, questions: list[str] | None = None) -> str:
    index = "\n".join(f"  {f.id}  {f.source}" for f in table.facts)
    q = ("QUESTIONS OF READING (the code cannot read words; for each element id give your honest reading of the text in "
         "element_readings: met / not_met / undetermined — a reading both advocates share is taken as agreed):\n"
         + "\n".join(f"  {x}" for x in questions) + "\n\n") if questions else ""
    return (f"CASE {table.case_id} — dispute type: {dispute['type']}, filed by: {dispute['filed_by']}\n"
            f"Complaint: \"{dispute['statement']}\"\n"
            f"Trip: {trip_summary}\n\n"
            f"FACT INDEX (ids and sources only; read contents with the tools):\n{index}\n\n{q}"
            f"Build your brief for the {dispute.get('_side', 'client')}.")


def opponent_text(brief: CaseBrief) -> str:
    lines = [f"side: {brief.side}", "claims:"]
    for c in brief.claims:
        if not c.void:
            lines.append(f"  {c.id}: {c.assertion}  [facts: {', '.join(c.facts)}; policy: {', '.join(c.policy)}]")
    lines.append("weaknesses they admitted: " + " | ".join(brief.weaknesses))
    lines.append(f"they ask for: {brief.requested_outcome.action}"
                 + (f" ${brief.requested_outcome.amount:.2f}" if brief.requested_outcome.amount else ""))
    return "\n".join(lines)
