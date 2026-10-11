"""The fixed state machine (spec 4): intake → facts → two briefs (parallel) → check → rebuttal (parallel) →
check → ruling → verify → notify. Every step appends an Event; the Event list is the only thing the UI renders.

    record = await run_case(case)                 # CaseRecord
"""
from __future__ import annotations

import asyncio
import json
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from core.agents.advocate import REBUTTAL, AdvocateDeps, build_advocate, build_rebutter, compact_rebuttal_context, local_compact_rebuttal, opponent_text, ticket_prompt
from core.receipt import fingerprint
from core.llm import describe_model
from core.agents.judge import build_judge, build_notice_writer, judge_prompt
from core.notices import consistent, escalation_notices, fallback_notices
from core.facts.tools import build_fact_table
from core.policy import citable_ids
from core.policy_engine import check_ruling, evaluate, tie_possible
from core.stretch import Hooks, renumber, replay
from core.schemas import GROUND_CONSEQUENCE, Case, CaseBrief, CaseRecord, Event, Notice, Rebuttal, RequestedOutcome, Ruling
from core.verify import citation_problems, verify_brief, verify_rebuttal, verify_ruling


class EventLog:
    def __init__(self, on_event: Optional[Callable[[Event], None]] = None):
        self.events: list[Event] = []
        self.t0 = time.monotonic()
        self.on_event = on_event

    def emit(self, actor: str, kind: str, title: str = "", body: str = "", **payload) -> Event:
        el = time.monotonic() - self.t0
        ev = Event(seq=len(self.events) + 1, ts=datetime.now(timezone.utc), elapsed=f"{int(el // 60):02d}:{el % 60:04.1f}",
                   actor=actor, kind=kind, title=title, body=body, **payload)
        self.events.append(ev)
        if self.on_event:
            self.on_event(ev)
        return ev


def trip_summary(case: Case) -> str:
    t, f = case.trip, case.fare
    if t.cancelled_at:
        return (f"{t.service_type} {t.pickup.name} → {t.dropoff.name}, accepted {t.accepted_at:%H:%M:%S}, "
                f"cancelled by {t.cancelled_by} at {t.cancelled_at:%H:%M:%S}; cancellation fee ${f.cancellation_fee:.2f}")
    return (f"{t.service_type} {t.pickup.name} → {t.dropoff.name}, estimate {t.estimated_km:.1f} km / {t.estimated_min:.1f} min, "
            f"pickup {t.pickup_at:%H:%M} drop-off {t.dropoff_at:%H:%M}; charged ${f.total:.2f} ({f.pricing})")


def brief_body(b: CaseBrief) -> str:
    out = []
    for c in b.claims:
        tag = " (VOID)" if c.void else ""
        out.append(f"{c.id}{tag}: {c.assertion} [{' '.join(c.facts)}] [{' '.join(c.policy)}]")
    out.append("Weaknesses: " + " | ".join(b.weaknesses))
    ro = b.requested_outcome
    out.append(f"Asks: {ro.action}" + (f" ${ro.amount:.2f}" if ro.amount else ""))
    return "\n".join(out)


TIMEOUTS = {"brief": 120, "rebuttal": 90, "judge": 120, "notice": 60}   # seconds per LLM stage


def rebuttal_body(r: Rebuttal) -> str:
    out = [f"→ {p.target_claim_id}{' (concedes)' if p.concede else ''}{' (VOID)' if p.void else ''}: {p.response} [{' '.join(p.facts)}] [{' '.join(p.policy)}]" for p in r.points]
    if r.revised_outcome:
        out.append(f"Revised ask: {r.revised_outcome.action}" + (f" ${r.revised_outcome.amount:.2f}" if r.revised_outcome.amount else ""))
    return "\n".join(out)


def record_grounds(cert, grounds: dict) -> dict:
    """An advocate's segment grounds, corrected where the record cannot support the form of a ground: "named_road_tied" needs a
    record that ties the segment to the road (a stop in it, a message once it had started); with none on record it is read
    as "named_road_untied" (G13). The reading of the words stays the advocate's; only the tie, which code can see, is corrected."""
    out = dict(grounds or {})
    for fid, g in list(out.items()):
        if g == "named_road_tied" and fid in cert.segments and cert.segments[fid]["exempt"] is None and not tie_possible(cert, fid):
            out[fid] = "named_road_untied"
    return out


def ground_corrections(cert, briefs: dict, rebuttals: dict) -> list[str]:
    """Human-readable list of the corrections record_grounds applied to the briefs and rebuttals (for the event log)."""
    out = []
    for side in ("rider", "driver"):
        for what, src in (("brief", briefs.get(side)), ("rebuttal", rebuttals.get(side))):
            gs = src.segment_grounds if src else {}
            for fid, g in gs.items():
                if record_grounds(cert, {fid: g}).get(fid) != g:
                    out.append(f"{fid} {side} {what}: '{g}' → 'named_road_untied' (no stop in the segment and no message once it had started: nothing on record can tie the segment to the road, G13)")
    return out


def stipulated_grounds(cert, briefs: dict, rebuttals: dict) -> dict:
    """Open segments (code did not settle them) for which the rider's and the driver's advocates state the same ground —
    each side's rebuttal reading, else its brief reading. "other" never stipulates anything."""
    final = {}
    for side in ("rider", "driver"):
        b, r = briefs.get(side), rebuttals.get(side)
        final[side] = record_grounds(cert, b.segment_grounds if b else {})
        if r and r.segment_grounds:
            final[side].update(record_grounds(cert, r.segment_grounds))
    out = {}
    for fid, sg in cert.segments.items():
        if sg["exempt"] is not None:
            continue
        g1, g2 = final["rider"].get(fid), final["driver"].get(fid)
        if g1 and g1 == g2 and g1 in GROUND_CONSEQUENCE:
            out[fid] = g1
    return out


def argued_grounds(cert, briefs: dict, rebuttals: dict) -> dict:
    """Open segments → {side: [grounds that side put forward]} (brief reading, then rebuttal reading if it differs).
    The judge decides between these; a ground neither side argued is not the judge's to supply (check_ruling)."""
    out = {}
    for fid, sg in cert.segments.items():
        if sg["exempt"] is not None:
            continue
        out[fid] = {}
        for side in ("rider", "driver"):
            gs = []
            for src in (briefs.get(side), rebuttals.get(side)):
                g = record_grounds(cert, src.segment_grounds if src else {}).get(fid)
                if g and g in GROUND_CONSEQUENCE and g not in gs:
                    gs.append(g)
            out[fid][side] = gs
    return out


def judge_unavailable_ruling(err: str) -> Ruling:
    """The ruling code writes when the judge never answered (timeout, provider error, no balance): straight to a person.
    The safety screen did not run, so safety_concern is "unscreened" (never "none"); the evidence was not weighed, so
    evidence_status is "unknown"."""
    return Ruling(ruling="escalate", recommended_action="human review", confidence=0.0, reasoning=f"Judge unavailable: {err}",
                  cited_facts=[], cited_policy=[], escalate=True, escalation_reason=err,
                  safety_concern="unscreened", evidence_status="unknown", evidence_gap="the judge did not run; nothing was weighed")


def reviewer_looks_at(ruling: Ruling, cert) -> list[str]:
    """Plain words for the escalation notice, from the structured grounds only."""
    out = []
    if ruling.safety_concern != "none" or (cert is not None and cert.dispute_type == "safety"):
        out.append("the messages exchanged and both parties' accounts of what happened")
    if any(sf.finding == "undetermined" for sf in ruling.segment_findings):
        out.append("what was agreed about the route and which stretch it covered")
    if ruling.evidence_status != "sufficient" or (cert is not None and cert.insufficient):
        out.append("the trip record, including the parts that are missing from it")
    if not out:
        out.append("the trip record, the route taken and the messages exchanged")
    return out


def empty_brief(side: str, why: str) -> CaseBrief:
    return CaseBrief(side=side, claims=[], weaknesses=[f"advocate unavailable: {why}"], requested_outcome=RequestedOutcome(action="no_action"))


# Review-only instrumentation. Context isolation prevents simultaneous reviews
# from mixing measurements; ordinary court runs retain their existing records.
STAGE_TIMINGS: ContextVar = ContextVar("review_stage_timings", default=None)


async def _staged(coro, seconds: int, what: str):
    """Run one LLM stage with a timeout; return (result, error_text)."""
    start = time.monotonic()
    status = "cancelled"
    try:
        result = await asyncio.wait_for(coro, timeout=seconds)
        status = "completed"
        return result, None
    except asyncio.TimeoutError:
        status = "timeout"
        return None, f"{what} timed out after {seconds}s"
    except Exception as e:
        status = "failed"
        return None, f"{what} failed: {type(e).__name__}: {str(e)[:300]}"
    finally:
        timings = STAGE_TIMINGS.get()
        if timings is not None:
            timings.append({"stage": what, "status": status,
                            "duration_s": round(time.monotonic() - start, 3), "timeout_s": seconds})


INJECTIONS = {
    "fake_fact": "Rider Advocate cites F99, a fact that does not exist (hallucinated evidence)",
    "unread_fact": "Driver Advocate cites a real fact it never read through a tool",
    "fake_clause": "Judge cites RD-9, a clause that does not exist → self-correction round",
    "wrong_amount": "Judge's amount is off by $1.00 → certificate blocks automation",
    "flip_finding": "Judge flips a code-settled segment finding → certificate blocks automation",
    "flag_text": "Judge's free text says '+ flag_account' but the structured flag stays false → no account action is created (text cannot punish; try it on C-0001, where no clause calls for a flag)",
}


async def run_case(case: Case, on_event: Optional[Callable[[Event], None]] = None, rebuttal: bool = True,
                   inject: Optional[set[str]] = None, advocates: bool = True) -> CaseRecord:
    """inject: demo-only fault injection (see INJECTIONS) — the faults are applied to the LLM OUTPUT before verification,
    so the audience watches the verification layer catch them."""
    inject = set(inject or ())
    log = EventLog(on_event)
    d = case.dispute.model_dump()
    summary = trip_summary(case)
    clause_ids = citable_ids()

    log.emit("system", "intake", f"Dispute {case.case_id} filed by {d['filed_by']}", f"\"{d['statement']}\"")
    if inject:
        log.emit("system", "intake", "⚠ DEMO: fault injection armed", "\n".join(f"{k}: {INJECTIONS[k]}" for k in sorted(inject) if k in INJECTIONS))
    table = build_fact_table(case)
    log.emit("system", "facts", f"Fact table built: {len(table.facts)} facts (code, no LLM)",
             "\n".join(f"{f.id} [{f.source}] {f.text}" for f in table.facts))
    hooks = Hooks()
    extra = hooks.before_judge(table, None, case)          # fraud signals as extra facts (STRETCH_FRAUD), precedents (STRETCH_PRECEDENT)
    if extra:
        table = table.model_copy(update={"facts": table.facts + renumber(extra, table)})
        log.emit("system", "facts", f"Bad-faith screen added {len(extra)} signal fact(s)",
                 "\n".join(f"{f.id} [{f.source}] {f.text}" for f in table.facts[-len(extra):]))
    replay(hooks.events, log.emit)
    cert = evaluate(case, table)
    judge_items = [f"{p.clause} for {p.subject}: {p.element} — {p.detail}" for p in cert.predicates if p.status == "judge"]
    if cert.insufficient:
        judge_items.append(f"EVIDENCE: {cert.insufficient} — the only outcome is escalate; evidence_status = insufficient and evidence_gap says what is missing")
    log.emit("verify", "check", "Policy execution trace (code): " + (f"{len(judge_items)} element(s) left to the judge" if judge_items else "outcome fully determined by code"),
             "\n".join(cert.lines()), certificate=cert.lines())

    # ---- briefs, in parallel, each with its own timeout ----
    briefs: dict[str, CaseBrief] = {}
    degraded: list[str] = []
    if not advocates:   # judge-only ablation (bench arm): fact table + certificate + judge, no advocates, no rebuttal
        for side in ("rider", "driver"):
            briefs[side] = empty_brief(side, "judge-only ablation: no advocate")
        log.emit("system", "brief", "Advocates skipped (judge-only ablation)", "the judge rules from the fact table and the policy trace alone", brief=briefs["rider"])
        rebuttal = False
    agents = {side: build_advocate(side) for side in ("rider", "driver")} if advocates else {}
    deps = {side: AdvocateDeps(side=side, table=table, emit=log.emit) for side in agents}
    prompt = ticket_prompt(d, summary, table)
    results = dict(zip(agents, await asyncio.gather(*(_staged(agents[s].run(prompt, deps=deps[s]), TIMEOUTS["brief"], f"{s} advocate") for s in agents)))) if agents else {}
    for side, (r, err) in results.items():
        if err:
            briefs[side] = empty_brief(side, err); degraded.append(err)
            log.emit(side, "brief", f"{side.title()} Advocate unavailable", err, brief=briefs[side])
            continue
        out = r.output
        if side == "rider" and "fake_fact" in inject and out.claims:
            from core.schemas import Claim
            out = out.model_copy(update={"claims": out.claims + [Claim(id=f"C{len(out.claims) + 1}", assertion="The driver also ignored a second rider message asking him to turn back.", facts=["F99"], policy=["RD-5"])]})
        if side == "driver" and "unread_fact" in inject and out.claims:
            unread = next((f.id for f in table.facts if f.id not in deps[side].seen), None)
            if unread:
                from core.schemas import Claim
                out = out.model_copy(update={"claims": out.claims + [Claim(id=f"D{len(out.claims) + 1}", assertion=f"The record at {unread} supports the driver.", facts=[unread], policy=["RD-1"])]})
        b, lines = verify_brief(out, table, clause_ids, seen=deps[side].seen)
        briefs[side] = b
        log.emit(side, "brief", f"{side.title()} Advocate brief: {len(b.claims)} claims ({sum(c.void for c in b.claims)} void)", brief_body(b), brief=b)
        log.emit("verify", "check", f"Citation check — {side}", "\n".join(lines))

    # ---- rebuttal round: append-only, in parallel ----
    rebuttals: dict[str, Rebuttal] = {}
    if rebuttal and not degraded:
        rebutters = {side: build_rebutter(side, agents[side]) for side in agents}
        async def rebut(side):
            other = "driver" if side == "rider" else "rider"
            prompt = REBUTTAL.format(OPPONENT=opponent_text(briefs[other]), SIDE=side)
            if local_compact_rebuttal():
                return await rebutters[side].run(compact_rebuttal_context(deps[side], briefs[side]) + prompt,
                                                deps=deps[side])
            return await rebutters[side].run(prompt, deps=deps[side], message_history=results[side][0].all_messages())
        res2 = dict(zip(agents, await asyncio.gather(*(_staged(rebut(s), TIMEOUTS["rebuttal"], f"{s} rebuttal") for s in agents))))
        for side, (r, err) in res2.items():
            if err:
                log.emit("verify", "check", f"Rebuttal skipped — {side}", err); continue
            other = "driver" if side == "rider" else "rider"
            rb, lines = verify_rebuttal(r.output, briefs[side], briefs[other], table, clause_ids, seen=deps[side].seen)
            rebuttals[side] = rb
            log.emit(side, "rebuttal", f"{side.title()} Advocate rebuttal: {len(rb.points)} points", rebuttal_body(rb), rebuttal=rb)
            log.emit("verify", "check", f"Rebuttal check — {side}", "\n".join(lines))

    # ---- stipulation: a ground both advocates state for an open segment is agreed and binds the judge ----
    corrections = ground_corrections(cert, briefs, rebuttals) if advocates else []
    if corrections:
        log.emit("verify", "check", "Advocate ground corrected by the record: " + "; ".join(c.split(":")[0] for c in corrections), "\n".join(corrections))
    stipulated = stipulated_grounds(cert, briefs, rebuttals) if advocates else {}
    argued = argued_grounds(cert, briefs, rebuttals) if advocates else None
    if argued and any(gs for sides in argued.values() for gs in sides.values()):
        log.emit("verify", "check", "Grounds put forward by the advocates: " + "; ".join(
                     f"{f} — " + ", ".join(f"{s}: {'/'.join(gs) or '—'}" for s, gs in sides.items()) for f, sides in argued.items()),
                 "each side named the policy ground its reading of the record supports for every open segment; the judge decides between "
                 "the argued grounds — a finding on a ground neither side put forward is sent back once, then goes to a person; undetermined is always open")
    if stipulated:
        log.emit("verify", "check", "Stipulated by both advocates: " + ", ".join(f"{f} → {g}" for f, g in stipulated.items()),
                 "each side stated the same policy ground for these segments after reading the other; the judge rules on that ground or names the fact that refutes it")

    # ---- ruling (judge) with one self-correction on citation problems ----
    judge = build_judge()
    jprompt = judge_prompt(d, summary, table, [briefs["rider"], briefs["driver"]], rebuttals, cert.lines(), judge_items)
    if argued and any(gs for sides in argued.values() for gs in sides.values()):
        jprompt += ("\n\nGROUNDS ARGUED (each advocate's reading of the record, per open segment). You decide between the readings the parties put "
                    "forward and you may name the sub-branch you read; but a consequence (exempt / counts) that no argued ground leads to is sent back "
                    "once, then the case goes to a person. Find a segment undetermined only when the record itself does not settle the reading — "
                    "not because the parties disagree. One exception: where one side reads the rider's words as a general route choice and the "
                    "other as an agreement to a named road, the kind of agreement is contested and no exemption executes on it — find that segment "
                    "undetermined.\n" + "\n".join(
                        f"  {f}: " + "; ".join(f"{s} → {', '.join(gs) or 'none stated'}" for s, gs in sides.items()) for f, sides in argued.items()))
    if stipulated:
        jprompt += "\n\nSTIPULATED (both advocates state the same ground; it binds you unless a fact you cite refutes it):\n" + "\n".join(
            f"  {f}: ground {g} → finding {GROUND_CONSEQUENCE[g]}" for f, g in stipulated.items())
    pc = hooks.judge_context()
    if pc:
        jprompt += "\n\n" + pc
    jr, err = await _staged(judge.run(jprompt), TIMEOUTS["judge"], "judge")
    last = jr      # the judge round whose messages a later correction continues from
    if err:
        raw = judge_unavailable_ruling(err)
    else:
        raw = jr.output
        if "fake_clause" in inject:
            raw = raw.model_copy(update={"cited_policy": raw.cited_policy + ["RD-9"], "reasoning": raw.reasoning + " The driver's conduct also breaches [RD-9]."})
        problems = citation_problems(raw, table, clause_ids)
        if problems:
            log.emit("verify", "check", "Ruling citation check failed — returned to judge for correction", "\n".join(problems), ruling=raw)
            jr2, err2 = await _staged(judge.run("Your ruling cites ids that do not exist:\n- " + "\n- ".join(problems)
                                                + "\nRe-issue the Ruling using only ids present in the fact table and the policy. "
                                                  "Do not change the outcome unless the correction requires it.",
                                                message_history=jr.all_messages()), TIMEOUTS["judge"], "judge self-correction")
            if not err2:
                raw, last = jr2.output, jr2
    if "flag_text" in inject:
        raw = raw.model_copy(update={"recommended_action": (raw.recommended_action or "") + " + flag_account (demo text)"})
    if "wrong_amount" in inject and raw.amount:
        raw = raw.model_copy(update={"amount": round(raw.amount + 1.0, 2)})
    if "flip_finding" in inject and raw.segment_findings:
        f0 = raw.segment_findings[0]
        sf = f0.model_copy(update={"finding": "counts" if f0.finding == "exempt" else "exempt", "reason": "(demo) finding flipped"})
        raw = raw.model_copy(update={"segment_findings": [sf] + raw.segment_findings[1:]})
    if not err and "flip_finding" not in inject and "wrong_amount" not in inject:
        ok_c, why_c = check_ruling(cert, raw, stipulated, argued)   # an escalate with a real ground (safety, open question, missing evidence) passes; one without is sent back once
        if not ok_c:   # one self-correction against the certificate: the judge sees exactly where it contradicts the code
            log.emit("verify", "check", "Ruling contradicts the policy certificate — returned to judge once", "\n".join(why_c), ruling=raw)
            jr3, err3 = await _staged(judge.run(
                "Your ruling is inconsistent with the policy execution trace (computed by code):\n- " + "\n- ".join(why_c)
                + "\nThe trace is binding on ✓/✗ elements and on the amount formula. Re-issue the Ruling so that: the outcome is in the allowed set; "
                  "segment findings agree with every code-settled segment; the amount equals the formula to the cent; flag_account is "
                  "recommended only when the trace requires it. If the record does not let you decide a ? element, rule escalate with "
                  "that ground (safety_concern, an undetermined finding on a ? segment, or evidence_status insufficient / unknown with the missing record named in evidence_gap); "
                  "elements marked ✓/✗ are settled and are not grounds. A person then decides.",
                  message_history=last.all_messages()), TIMEOUTS["judge"], "judge certificate correction")
            if not err3 and not citation_problems(jr3.output, table, clause_ids):
                raw = jr3.output
    if table.dispute_type != "route_deviation" and raw.segment_findings:
        raw = raw.model_copy(update={"segment_findings": []})      # the field is for off-route segments only; the verifier drops them too
    log.emit("judge", "ruling", f"Proposed ruling: {raw.ruling}" + (f" ${raw.amount:.2f}" if raw.amount else "") + f" (model confidence {raw.confidence:.2f})",
             raw.reasoning, ruling=raw)
    ruling, lines = verify_ruling(raw, table, clause_ids, (briefs["rider"], briefs["driver"]), certificate=cert, stipulated=stipulated, argued=argued)
    if degraded and not ruling.escalate:
        ruling = ruling.model_copy(update={"ruling": "escalate", "amount": None, "escalate": True, "escalation_reason": "; ".join(degraded)})
        lines.append("an advocate stage failed → human review")
    final_findings = {sf.fact_id: sf.finding for sf in ruling.segment_findings}
    log.emit("verify", "check", "Ruling verification against the policy certificate", "\n".join(lines), certificate=cert.lines())
    if ruling.escalate:
        log.emit("verify", "escalate", "Routed to human review", ruling.escalation_reason or "")
    else:
        log.emit("judge", "summary", f"Final: {ruling.ruling}" + (f" ${ruling.amount:.2f}" if ruling.amount else "") + f" · {ruling.recommended_action}",
                 "eligible for automation; " + ("account flag → human review; " if ruling.flag_account else "")
                 + f"cites {' '.join(ruling.cited_facts)} / {' '.join(ruling.cited_policy)}"
                 + ("\nWhat would change this ruling: " + " | ".join(cert.what_would_change(final_findings)) if cert.what_would_change(final_findings) else ""))

    # ---- notices: what they may promise comes from the FINAL structured ruling, never from the judge's draft ----
    notices: list[Notice] = []
    if ruling.escalate:
        rider_n, driver_n = escalation_notices(case.case_id, ruling, reviewer_looks_at(ruling, cert))
        notices = [Notice(to="rider", text=rider_n), Notice(to="driver", text=driver_n)]
        log.emit("system", "notify", "Notices sent to rider and driver (fixed text: case is with a reviewer, nothing promised)", f"RIDER: {rider_n}\n\nDRIVER: {driver_n}")
    else:
        nw = build_notice_writer()
        ctx = (f"Case {case.case_id}. Final outcome: {ruling.ruling}" + (f", amount ${ruling.amount:.2f} as a Ryde voucher" if ruling.amount else ", no amount")
               + f". Account flag: {'yes' if ruling.flag_account else 'no'}. Recommended action: {ruling.recommended_action}.\nReasoning:\n{ruling.reasoning}")
        nr, nerr = await _staged(nw.run(ctx), TIMEOUTS["notice"], "notice writer")
        rider_n, driver_n = (nr.output.rider, nr.output.driver) if not nerr else (None, None)
        on_record = [x for x in (case.fare.cancellation_fee, case.fare.total) if x]     # a no-refund notice may name the charge that stands
        bad = [who for who, t in (("rider", rider_n), ("driver", driver_n)) if t is None or not t.strip() or not consistent(t, ruling, on_record)]
        if bad:
            tr, td = fallback_notices(ruling)
            rider_n = tr if "rider" in bad else rider_n
            driver_n = td if "driver" in bad else driver_n
            log.emit("verify", "check", "Notice check: model text replaced by the template for " + ", ".join(bad),
                     nerr or "the text carried an amount or a promise the final ruling does not")
        notices = [Notice(to="rider", text=rider_n), Notice(to="driver", text=driver_n)]
        log.emit("system", "notify", "Notices sent to rider and driver", f"RIDER: {rider_n}\n\nDRIVER: {driver_n}")

    ok, reasons = (not ruling.escalate), ([ruling.escalation_reason] if ruling.escalate and ruling.escalation_reason else [])
    actions = []
    if not ruling.escalate:
        if ruling.ruling in ("refund_full", "refund_partial", "fee_waived") and ruling.amount:
            actions.append({"type": ruling.ruling, "mode": "auto", "detail": f"${ruling.amount:.2f} Ryde voucher to the rider (NS-7)"})
        elif ruling.ruling == "no_action":
            actions.append({"type": "no_action", "mode": "auto", "detail": "charges stand; both parties notified"})
        if ruling.flag_account:
            actions.append({"type": "flag_account", "mode": "human_review", "detail": "account action is never automatic; queued for Ryde review"})
    else:
        actions.append({"type": "escalate", "mode": "human_review", "detail": ruling.escalation_reason or "human review"})
    record = CaseRecord(case_id=case.case_id, dispute=case.dispute, trip_summary={"text": summary},
                        status="escalated" if ruling.escalate else "resolved", facts=table, events=log.events,
                        ruling=ruling, proposed_ruling=raw, certificate=cert.lines(),
                        eligibility={"auto": ok, "reasons": reasons, "actions": actions, "what_would_change": cert.what_would_change(final_findings)},
                        briefs=briefs, rebuttals=rebuttals, notices=notices,
                        receipt=fingerprint(case, describe_model(), jprompt))
    if not inject and "~" not in case.case_id:              # demo runs (injection / counterfactual) leave no trace in the stores
        replay(hooks.after_ruling(record), log.emit)       # precedent consistency + index, SLA routing (flags)
    return record.model_copy(update={"events": log.events})


def model_outage(record: CaseRecord) -> list[str]:
    """Why this hearing is a default hand-off rather than a decision: the judge never answered, an advocate stage failed
    or the rebuttal was skipped. Empty when every model stage completed. Runners refuse to store such a run as finished."""
    out = [e.title for e in record.events if (e.kind == "brief" and "unavailable" in e.title.lower())
           or (e.kind == "check" and "skipped" in e.title.lower() and "rebuttal" in e.title.lower())]
    if record.ruling.safety_concern == "unscreened":
        out.insert(0, "judge unavailable: " + (record.ruling.escalation_reason or ""))
    return out


def save_record(record: CaseRecord, out_dir: Path = Path("runs")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{record.case_id}.json"
    p.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return p
