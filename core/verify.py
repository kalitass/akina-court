"""Code-side checks on LLM output: citation validity and consistency with the policy certificate. Nothing here calls a model.

verify_brief   marks claims void when they cite facts or clauses that do not exist.
verify_ruling  hard rules -> escalate; a judge's own escalate (safety concern, undetermined finding, evidence gap) is
               kept as stated — code records the ground and never turns it back into an executable ruling.
Both return a new object plus a list of human-readable check lines for the Event log.
"""
from __future__ import annotations

from core.policy import ACTIONS, cited_in
from core.policy_engine import check_ruling, escalate_grounds
from core.schemas import CaseBrief, FactTable, Ruling



def verify_brief(brief: CaseBrief, table: FactTable, clause_ids: set[str],
                 seen: set[str] | None = None) -> tuple[CaseBrief, list[str]]:
    """seen = fact ids the advocate actually read through tools; citing an unread fact is void (no guessing)."""
    ids = table.ids()
    lines: list[str] = []
    claims = []
    seen_ids = set()
    for c in brief.claims:
        reason = None
        if c.id in seen_ids:
            reason = f"duplicate claim id {c.id}"
        seen_ids.add(c.id)
        if reason is None and not c.facts:
            reason = "citation check: no fact cited"
        elif reason is None and not c.policy:
            reason = "citation check: no clause cited"
        elif reason is None:
            bad_f = [f for f in c.facts if f not in ids]
            unread = [f for f in c.facts if seen is not None and f in ids and f not in seen]
            bad_p = [p for p in c.policy if p not in clause_ids]
            if bad_f:
                reason = f"citation check: cites {', '.join(bad_f)} — not in the fact table"
            elif unread:
                reason = f"citation check: cites {', '.join(unread)} without having read it (no tool call returned it)"
            elif bad_p:
                reason = f"citation check: cites {', '.join(bad_p)} — not a citable clause"
        claims.append(c.model_copy(update={"void": reason is not None, "void_reason": reason}))
        lines.append(f"{c.id}: {'VOID — ' + reason if reason else 'ok (' + ', '.join(c.facts + c.policy) + ')'}")
    if brief.requested_outcome.action not in ACTIONS:
        lines.append(f"warning: requested action {brief.requested_outcome.action!r} is not in the vocabulary")
    return brief.model_copy(update={"claims": claims}), lines


def verify_rebuttal(reb, own: CaseBrief, other: CaseBrief, table: FactTable, clause_ids: set[str], seen: set[str] | None = None):
    """Rebuttal points must target an existing live claim and cite only existing (and read) facts / clauses."""
    from core.schemas import Rebuttal  # local import to avoid cycles at module load
    ids = table.ids()
    targets = {c.id for c in other.claims if not c.void} | {c.id for c in own.claims if not c.void}
    pts, lines = [], []
    for p in reb.points:
        reason = None
        if p.target_claim_id not in targets:
            reason = f"targets {p.target_claim_id}, which is not a live claim"
        elif not p.facts or not p.policy:
            reason = "citation check: a rebuttal point must cite at least one fact and one clause"
        else:
            bad_f = [f for f in p.facts if f not in ids]
            unread = [f for f in p.facts if seen is not None and f in ids and f not in seen]
            bad_p = [q for q in p.policy if q not in clause_ids]
            if bad_f:
                reason = f"citation check: cites {', '.join(bad_f)} — not in the fact table"
            elif unread:
                reason = f"citation check: cites {', '.join(unread)} without having read it"
            elif bad_p:
                reason = f"citation check: cites {', '.join(bad_p)} — not a citable clause"
        pts.append(p.model_copy(update={"void": reason is not None, "void_reason": reason}))
        lines.append(f"→{p.target_claim_id}{' (concede)' if p.concede else ''}: {'VOID — ' + reason if reason else 'ok'}")
    return Rebuttal(side=reb.side, points=pts, revised_outcome=reb.revised_outcome), lines


def _fact_values(table: FactTable) -> dict[str, dict]:
    return {f.id: (f.value or {}) for f in table.facts}


def _source(table: FactTable, fid: str) -> str | None:
    return next((f.source for f in table.facts if f.id == fid), None)


def _escalate(r: Ruling, reason: str) -> Ruling:
    return r.model_copy(update={"ruling": "escalate", "amount": None, "escalate": True, "escalation_reason": reason})


def all_cited(ruling: Ruling) -> tuple[set[str], set[str]]:
    """Every fact id and clause id the ruling relies on, wherever it wrote them: the top-level lists, the reasoning,
    each segment finding's basis and reason, the safety basis, the rejected claims and the evidence gap."""
    facts = set(ruling.cited_facts) | set(ruling.safety_basis)
    clauses = set(ruling.cited_policy)
    texts = [ruling.reasoning, ruling.evidence_gap or ""] + [sf.reason for sf in ruling.segment_findings] + [rc.reason for rc in ruling.rejected_claims]
    for t in texts:
        f, c = cited_in(t)
        facts |= f; clauses |= c
    for sf in ruling.segment_findings:
        facts |= set(sf.basis)
    return facts, clauses


def citation_problems(ruling: Ruling, table: FactTable, clause_ids: set[str]) -> list[str]:
    """Human-readable list of non-existent fact / clause ids the ruling relies on anywhere (empty = clean).
    The orchestrator feeds this back to the judge for one self-correction before escalating."""
    cited_f, cited_p = all_cited(ruling)
    out = []
    bad_f = sorted(cited_f - table.ids())
    bad_p = sorted(cited_p - clause_ids)
    if bad_f:
        out.append(f"fact ids that do not exist in the fact table: {', '.join(bad_f)}")
    if bad_p:
        out.append(f"clause ids that do not exist or are marked 不可引用: {', '.join(bad_p)}")
    if ruling.ruling not in ACTIONS:
        out.append(f"ruling {ruling.ruling!r} is not in the vocabulary {ACTIONS}")
    return out


def verify_ruling(ruling: Ruling, table: FactTable, clause_ids: set[str],
                  briefs: tuple[CaseBrief, ...] = (), certificate=None, stipulated: dict | None = None) -> tuple[Ruling, list[str]]:
    lines: list[str] = []
    ids = table.ids()
    if table.dispute_type != "route_deviation" and ruling.segment_findings:
        lines.append(f"dropped {len(ruling.segment_findings)} segment finding(s): not a route case")
        ruling = ruling.model_copy(update={"segment_findings": []})
    if ruling.ruling in ("no_action", "escalate") and ruling.amount is not None:
        ruling = ruling.model_copy(update={"amount": None})
    elif ruling.amount is not None:
        ruling = ruling.model_copy(update={"amount": round(ruling.amount + 1e-9, 2)})   # money is kept to the cent
    vals = _fact_values(table)
    cited_f, cited_p = all_cited(ruling)

    # ---- hard rules ----
    bad_f = sorted(cited_f - ids)
    if bad_f:
        lines.append(f"HARD: ruling cites {', '.join(bad_f)} which do not exist → escalate")
        return _escalate(ruling, f"citation check: ruling cites non-existent facts {', '.join(bad_f)}"), lines
    bad_p = sorted(cited_p - clause_ids)
    if bad_p:
        lines.append(f"HARD: ruling cites {', '.join(bad_p)} which are not citable clauses → escalate")
        return _escalate(ruling, f"citation check: ruling cites non-citable clauses {', '.join(bad_p)}"), lines
    if ruling.ruling not in ACTIONS:
        lines.append(f"HARD: ruling action {ruling.ruling!r} not in vocabulary → escalate")
        return _escalate(ruling, f"ruling action {ruling.ruling!r} not in vocabulary"), lines
    if table.dispute_type == "safety":
        lines.append("HARD: complaint filed as a safety incident → escalate (SAFE-1 / SAFE-2)")
        if not ruling.escalate or ruling.ruling != "escalate":
            ruling = _escalate(ruling, "SAFE-1: a safety complaint is never ruled automatically")
        else:
            ruling = ruling.model_copy(update={"amount": None})
        return ruling, lines
    # ---- the judge's own escalate stands: its grounds are recorded, never second-guessed by code ----
    if ruling.ruling == "escalate" or ruling.escalate:
        grounds = escalate_grounds(ruling)
        why = "; ".join(grounds) if grounds else (ruling.escalation_reason or "judge sent the case to a person without naming a ground")
        ok_g, why_g = (check_ruling(certificate, ruling, stipulated) if certificate is not None else (True, []))
        if ok_g:
            lines.append("judge escalates → human review: " + why)
        else:
            lines.extend("✗ " + r for r in why_g)
            lines.append("judge escalates on a ground the trace does not leave open; recorded for the reviewer as is")
        return _escalate(ruling, why), lines
    if ruling.safety_concern != "none":
        lines.append(f"HARD: judge recorded a safety concern ({ruling.safety_concern}) but ruled → escalate (SAFE-1)")
        return _escalate(ruling, f"safety concern {ruling.safety_concern}: " + (", ".join(ruling.safety_basis) or "no basis listed")), lines
    if ruling.ruling in ("refund_full", "refund_partial", "fee_waived"):
        cap = None
        for v in vals.values():
            if "total" in v and "base_fare" in v:
                cap = v["total"]
            elif "cancellation_fee" in v and len(v) == 1:
                cap = v["cancellation_fee"]
        if ruling.amount is None or ruling.amount <= 0:
            lines.append("HARD: refund with no positive amount → escalate")
            return _escalate(ruling, "refund ruling without an executable amount"), lines
        if cap is not None and ruling.amount > cap + 0.005:
            lines.append(f"HARD: amount {ruling.amount:.2f} exceeds the charge on record {cap:.2f} → escalate")
            return _escalate(ruling, f"refund {ruling.amount:.2f} exceeds the charged amount {cap:.2f}"), lines
    live_claims = {c.id for b in briefs for c in b.claims if not c.void}
    kept = [rc for rc in ruling.rejected_claims if rc.id in live_claims]
    dropped = [rc.id for rc in ruling.rejected_claims if rc.id not in live_claims]
    if dropped:
        lines.append(f"dropped rejected_claims not in any live brief: {', '.join(dropped)}")
    ruling = ruling.model_copy(update={"rejected_claims": kept})

    # ---- empty citations: a ruling that rests on nothing is not executable ----
    if not cited_f or not cited_p:
        lines.append("HARD: ruling cites no facts or no clauses → review")
        return _escalate(ruling, "ruling cites no facts or no clauses"), lines

    # ---- policy execution certificate (code) vs the judge's ruling ----
    if certificate is not None:
        ok, reasons = check_ruling(certificate, ruling, stipulated)
        lines.extend(("✓ " if ok else "✗ ") + r for r in (reasons or ["ruling consistent with the policy certificate"]))
        if not ok:
            return _escalate(ruling, "not eligible for automation: " + "; ".join(reasons)), lines
    lines.append(f"model confidence {ruling.confidence:.2f} (diagnostic only; automation is decided by the certificate)")
    return ruling.model_copy(update={"escalate": False, "escalation_reason": None}), lines   # reached only by a non-escalate ruling that passed every check
