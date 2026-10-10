"""The fixed state machine (spec 4): intake → facts → two briefs (parallel) → check → rebuttal (parallel) →
check → ruling → verify → notify. Every step appends an Event; the Event list is the only thing the UI renders.

    record = await run_case(case)                 # CaseRecord
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from core.agents.advocate import REBUTTAL, AdvocateDeps, build_advocate, build_rebutter, opponent_text, ticket_prompt
from core.receipt import fingerprint
from core.llm import describe_model
from core.agents.judge import build_judge, judge_prompt
from core.facts.tools import build_fact_table
from core.policy import citable_ids
from core.policy_engine import check_ruling, evaluate
from core.stretch import Hooks, renumber, replay
from core.schemas import Case, CaseBrief, CaseRecord, Event, Notice, Rebuttal, RequestedOutcome, Ruling
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
    return (f"{t.service_type} {t.pickup.name} → {t.dropoff.name}, estimate {t.estimated_km:.1f} km / {t.estimated_min:.0f} min, "
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


TIMEOUTS = {"brief": 120, "rebuttal": 90, "judge": 120}   # seconds per LLM stage


def rebuttal_body(r: Rebuttal) -> str:
    out = [f"→ {p.target_claim_id}{' (concedes)' if p.concede else ''}{' (VOID)' if p.void else ''}: {p.response} [{' '.join(p.facts)}] [{' '.join(p.policy)}]" for p in r.points]
    if r.revised_outcome:
        out.append(f"Revised ask: {r.revised_outcome.action}" + (f" ${r.revised_outcome.amount:.2f}" if r.revised_outcome.amount else ""))
    return "\n".join(out)


def empty_brief(side: str, why: str) -> CaseBrief:
    return CaseBrief(side=side, claims=[], weaknesses=[f"advocate unavailable: {why}"], requested_outcome=RequestedOutcome(action="no_action"))


async def _staged(coro, seconds: int, what: str):
    """Run one LLM stage with a timeout; return (result, error_text)."""
    try:
        return await asyncio.wait_for(coro, timeout=seconds), None
    except asyncio.TimeoutError:
        return None, f"{what} timed out after {seconds}s"
    except Exception as e:
        return None, f"{what} failed: {type(e).__name__}: {str(e)[:300]}"


INJECTIONS = {
    "fake_fact": "Rider Advocate cites F99, a fact that does not exist (hallucinated evidence)",
    "unread_fact": "Driver Advocate cites a real fact it never read through a tool",
    "fake_clause": "Judge cites RD-9, a clause that does not exist → self-correction round",
    "wrong_amount": "Judge's amount is off by $1.00 → certificate blocks automation",
    "flip_finding": "Judge flips a code-settled segment finding → certificate blocks automation",
    "flag_text": "Judge's free text says '+ flag_account' but the structured flag stays false → no account action is created (text cannot punish; try it on C-0001, where no clause calls for a flag)",
}


def _safe_notice(side: str, ruling: Ruling) -> str:
    """Draft a notice from verified fields; the prototype never moves money."""
    if ruling.escalate:
        return "This dispute needs human review. No refund or account change has been made by this prototype."
    if ruling.ruling == "no_action":
        text = "The review recommends keeping the recorded charge. This prototype has not changed any payment."
    elif ruling.ruling in ("refund_full", "refund_partial", "fee_waived") and ruling.amount is not None:
        text = (f"The review recommends a ${ruling.amount:.2f} Ryde voucher refund to the rider. "
                "This prototype has not issued a voucher or changed any payment.")
    else:
        text = "The review recommends further handling. This prototype has not changed any payment or account."
    if ruling.flag_account:
        text += " A separate account review is recommended for a person; no account action has been taken automatically."
    return text


def _sanitize_notices(raw: dict[str, str], ruling: Ruling) -> dict[str, str]:
    """Use verified ruling fields for outward notices, regardless of draft wording.

    A list of forbidden words cannot reliably detect every invented payment or
    account claim. The old model notice writer is no longer called.
    """
    return {side: _safe_notice(side, ruling) for side in ("rider", "driver")}


def _build_actions(ruling: Ruling) -> list[dict[str, str]]:
    """Build proposed actions from the verified structured ruling."""
    actions: list[dict[str, str]] = []
    if ruling.escalate:
        return [{"type": "escalate", "mode": "human_review", "detail": ruling.escalation_reason or "human review"}]
    if ruling.ruling in ("refund_full", "refund_partial", "fee_waived") and ruling.amount is not None:
        actions.append({"type": ruling.ruling, "mode": "auto", "detail": f"Recommend ${ruling.amount:.2f} Ryde voucher to the rider"})
    elif ruling.ruling == "no_action":
        actions.append({"type": "no_action", "mode": "auto", "detail": "charges stand; no refund recommended"})
    if ruling.flag_account:
        actions.append({"type": "flag_account", "mode": "human_review", "detail": "account action is never automatic; queued for Ryde review"})
    return actions




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
        judge_items.append(f"EVIDENCE: {cert.insufficient} — the only outcome is escalate; state what is missing in evidence_gap")
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
            return await rebutters[side].run(REBUTTAL.format(OPPONENT=opponent_text(briefs[other]), SIDE=side),
                                            deps=deps[side], message_history=results[side][0].all_messages())
        res2 = dict(zip(agents, await asyncio.gather(*(_staged(rebut(s), TIMEOUTS["rebuttal"], f"{s} rebuttal") for s in agents))))
        for side, (r, err) in res2.items():
            if err:
                log.emit("verify", "check", f"Rebuttal skipped — {side}", err); continue
            other = "driver" if side == "rider" else "rider"
            rb, lines = verify_rebuttal(r.output, briefs[side], briefs[other], table, clause_ids, seen=deps[side].seen)
            rebuttals[side] = rb
            log.emit(side, "rebuttal", f"{side.title()} Advocate rebuttal: {len(rb.points)} points", rebuttal_body(rb), rebuttal=rb)
            log.emit("verify", "check", f"Rebuttal check — {side}", "\n".join(lines))

    # ---- ruling (judge) with one self-correction on citation problems ----
    judge = build_judge()
    jprompt = judge_prompt(d, summary, table, [briefs["rider"], briefs["driver"]], rebuttals, cert.lines(), judge_items)
    pc = hooks.judge_context()
    if pc:
        jprompt += "\n\n" + pc
    jr, err = await _staged(judge.run(jprompt), TIMEOUTS["judge"], "judge")
    if err:
        raw = Ruling(ruling="escalate", recommended_action="human review", confidence=0.0, reasoning=f"Judge unavailable: {err}",
                     cited_facts=[], cited_policy=[], escalate=True, escalation_reason=err)
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
                raw = jr2.output
    if "flag_text" in inject:
        raw = raw.model_copy(update={"recommended_action": (raw.recommended_action or "") + " + flag_account (demo text)"})
    if "wrong_amount" in inject and raw.amount:
        raw = raw.model_copy(update={"amount": round(raw.amount + 1.0, 2)})
    if "flip_finding" in inject and raw.segment_findings:
        f0 = raw.segment_findings[0]
        sf = f0.model_copy(update={"finding": "counts" if f0.finding == "exempt" else "exempt", "reason": "(demo) finding flipped"})
        raw = raw.model_copy(update={"segment_findings": [sf] + raw.segment_findings[1:]})
    if not err and "flip_finding" not in inject and "wrong_amount" not in inject:
        ok_c, why_c = check_ruling(cert, raw)   # an escalate with a real ground (safety, open question, missing evidence) passes; one without is sent back once
        if not ok_c:   # one self-correction against the certificate: the judge sees exactly where it contradicts the code
            log.emit("verify", "check", "Ruling contradicts the policy certificate — returned to judge once", "\n".join(why_c), ruling=raw)
            jr3, err3 = await _staged(judge.run(
                "Your ruling is inconsistent with the policy execution trace (computed by code):\n- " + "\n- ".join(why_c)
                + "\nThe trace is binding on ✓/✗ elements and on the amount formula. Re-issue the Ruling so that: the outcome is in the allowed set; "
                  "segment findings agree with every code-settled segment; the amount equals the formula to the cent; flag_account is "
                  "recommended only when the trace requires it. If the record does not let you decide a ? element, rule escalate with "
                  "that ground (safety_concern, an undetermined finding on a ? segment, or the specific missing fact in evidence_gap); "
                  "elements marked ✓/✗ are settled and are not grounds. A person then decides.",
                  message_history=jr.all_messages()), TIMEOUTS["judge"], "judge certificate correction")
            if not err3 and not citation_problems(jr3.output, table, clause_ids):
                raw = jr3.output
    log.emit("judge", "ruling", f"Proposed ruling: {raw.ruling}" + (f" ${raw.amount:.2f}" if raw.amount else "") + f" (model confidence {raw.confidence:.2f})",
             raw.reasoning, ruling=raw)
    ruling, lines = verify_ruling(raw, table, clause_ids, (briefs["rider"], briefs["driver"]), certificate=cert)
    if degraded and not ruling.escalate:
        ruling = ruling.model_copy(update={"ruling": "escalate", "amount": None, "escalate": True, "escalation_reason": "; ".join(degraded)})
        lines.append("an advocate stage failed → human review")
    log.emit("verify", "check", "Ruling verification against the policy certificate", "\n".join(lines), certificate=cert.lines())
    if ruling.escalate:
        log.emit("verify", "escalate", "Routed to human review", ruling.escalation_reason or "")
    else:
        log.emit("judge", "summary", f"Final: {ruling.ruling}" + (f" ${ruling.amount:.2f}" if ruling.amount else "") + f" · {ruling.recommended_action}",
                 "eligible for automation; " + ("account flag → human review; " if ruling.flag_account else "")
                 + f"cites {' '.join(ruling.cited_facts)} / {' '.join(ruling.cited_policy)}"
                 + ("\nWhat would change this ruling: " + " | ".join(cert.what_would_change()) if cert.what_would_change() else ""))

    ok, reasons = (not ruling.escalate), ([ruling.escalation_reason] if ruling.escalate and ruling.escalation_reason else [])
    actions = _build_actions(ruling)

    # ---- notices from verified fields only; no extra model call ----
    safe = _sanitize_notices({}, ruling)
    log.emit("verify", "check", "Notices generated from verified ruling fields",
             "Payment and account language comes from the structured ruling; no notice model call was made.")
    notices = [Notice(to="rider", text=safe["rider"]), Notice(to="driver", text=safe["driver"])]
    log.emit("system", "notify", "Notices drafted for rider and driver", f"RIDER: {safe['rider']}\n\nDRIVER: {safe['driver']}")
    record = CaseRecord(case_id=case.case_id, dispute=case.dispute, trip_summary={"text": summary},
                        status="escalated" if ruling.escalate else "resolved", facts=table, events=log.events,
                        ruling=ruling, proposed_ruling=raw, certificate=cert.lines(),
                        eligibility={"auto": ok, "reasons": reasons, "actions": actions, "what_would_change": cert.what_would_change()},
                        briefs=briefs, rebuttals=rebuttals, notices=notices,
                        receipt=fingerprint(case, describe_model(), jprompt))
    if not inject and "~" not in case.case_id:              # demo runs (injection / counterfactual) leave no trace in the stores
        replay(hooks.after_ruling(record), log.emit)       # precedent consistency + index, SLA routing (flags)
    return record.model_copy(update={"events": log.events})


def save_record(record: CaseRecord, out_dir: Path = Path("runs")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{record.case_id}.json"
    p.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return p
