"""Meaning is read by the court, measured things by code, and missing evidence is a finding of its own.

Acceptance list (no model call; the engine, the verifier and the fact tools are exercised with real case files):
  * a paraphrased agreement leaves the consent question open to the judge instead of closing it
  * a negated "okay" is not labelled agreement; nothing in the fact table labels meaning at all
  * "I cannot find you at the pickup point" does not force an escalation; a threat without a keyword can still escalate
  * an exempt finding must rest on a rider message sent before the segment, never on the driver's statement alone
  * missing GPS, a hole in the trace, an untimed message, a metered trip without a distance fare: no ruling for either side
  * the judge's own escalate (undetermined finding, safety concern, evidence gap) is kept by the verifier
"""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from core.facts.tools import build_fact_table
from core.policy import citable_ids
from core.policy_engine import check_ruling, evaluate, expected_amount
from core.schemas import Case, ChatMessage, Ruling, SegmentFinding
from core.verify import verify_ruling


def _sf(**kw):
    """A SegmentFinding whose ground follows its finding (the tests here are about timing, basis and amounts, not the ground)."""
    kw.setdefault("ground", {"exempt": "general_route_consent", "counts": "consent_after_or_none", "undetermined": "named_road_untied"}[kw["finding"]])
    return SegmentFinding(**kw)


ROOT = Path(__file__).resolve().parents[1]


def load(cid):
    return Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))


def with_chat(case, lines):
    """lines: (seconds after the first message's time, from, text)."""
    t0 = case.chat[0].ts if case.chat else case.trip.accepted_at
    return case.model_copy(update={"chat": [ChatMessage(ts=t0 + timedelta(seconds=d), **{"from": who}, text=txt) for d, who, txt in lines]})


def ruling(**kw):
    base = dict(ruling="no_action", recommended_action="x", confidence=0.9, reasoning="[F1][RD-1]", cited_facts=["F1"], cited_policy=["RD-1"],
                safety_concern="none", evidence_status="sufficient")
    base.update(kw)
    return Ruling(**base)


def judge_items(cert):
    return [p for p in cert.predicates if p.status == "judge"]


# ---------------------------------------------------------------- consent is read, not matched

def test_paraphrased_agreement_keeps_the_question_open():
    case = with_chat(load("C-0001"), [(0, "driver", "Traffic on Orchard is bad, ok if I go round by Cavenagh?"), (40, "rider", "That works for me.")])
    cert = evaluate(case, build_fact_table(case))
    rd5 = [p for p in judge_items(cert) if p.clause == "RD-5"]
    assert rd5, cert.lines()                                        # the judge decides; code did not say "no exemption candidate"
    assert set(cert.allowed) >= {"refund_partial", "no_action", "escalate"}


def test_negated_okay_is_not_labelled_and_the_judge_may_still_find_counts():
    case = with_chat(load("C-0001"), [(0, "driver", "ok if I go round by Cavenagh?"), (40, "rider", "I am not okay with this detour.")])
    table = build_fact_table(case)
    assert not any("agreement" in (f.value or {}).get("flags", []) for f in table.facts)
    assert not any("[agreement]" in f.text for f in table.facts)
    cert = evaluate(case, table)
    open_segs = [s for s, sg in cert.segments.items() if sg["exempt"] is None]          # code settled the RD-4 one; these are the judge's
    assert open_segs
    f = [_sf(fact_id=s, finding="counts" if sg["exempt"] is None else "exempt", reason="refused [RD-5]") for s, sg in cert.segments.items()]
    amount = expected_amount(cert, {x.fact_id: x.exempt for x in f})
    r = ruling(ruling="refund_partial", amount=amount, segment_findings=f)
    ok, why = check_ruling(cert, r)
    assert ok, why


def test_exempt_finding_needs_a_rider_message_before_the_segment():
    case = load("C-0001")
    table = build_fact_table(case)
    cert = evaluate(case, table)
    seg = next(s for s in cert.segments if cert.segments[s]["exempt"] is None)
    stmt = next(f for f, m in cert.chat_index.items() if m["statement"])
    rider_before = [f for f, m in cert.chat_index.items() if m["from"] == "rider" and not m["statement"] and m["ts"] < cert.segments[seg]["start"]]
    others = [s for s in cert.segments if s != seg]
    def r(basis):
        return ruling(ruling="no_action", segment_findings=[_sf(fact_id=seg, finding="exempt", basis=basis, reason="[RD-5]")]
                      + [_sf(fact_id=s, finding="exempt", basis=rider_before, reason="[RD-5]") for s in others])
    ok, why = check_ruling(cert, r([stmt]))
    assert not ok and any("driver's statement" in w for w in why), why        # G11: the driver's own claim is not consent
    ok, why = check_ruling(cert, r([]))
    assert not ok and any("rests on no chat fact" in w for w in why), why
    ok, why = check_ruling(cert, r(rider_before))
    assert ok, why                                                              # well-formed: code does not second-guess the reading


# ---------------------------------------------------------------- safety is read, not matched

def test_pickup_chat_with_a_hint_word_is_not_an_escalation():
    case = with_chat(load("C-0002"), [(0, "rider", "I cannot find you at the pickup point."), (30, "driver", "Coming round now.")])
    table = build_fact_table(case)
    cert = evaluate(case, table)
    assert cert.dispute_type == "route_deviation" and "escalate" in cert.allowed and cert.allowed != ["escalate"]
    screen = next(p for p in cert.predicates if p.clause == "SAFE-1")
    assert screen.status == "judge" and screen.evidence                         # the hint is pointed at, not ruled on
    r = ruling(ruling="no_action", segment_findings=[_sf(fact_id=s, finding="exempt", basis=[], reason="x") for s in cert.segments]) \
        if cert.segments else ruling(ruling="no_action")
    out, lines = verify_ruling(ruling(ruling="no_action", safety_concern="none"), table, citable_ids(), certificate=evaluate(case, build_fact_table(load("C-0002"))))
    assert not any("keyword" in l for l in lines)


def test_threat_without_keyword_escalates_on_the_judges_reading():
    case = with_chat(load("C-0002"), [(0, "rider", "Why this way?"), (30, "driver", "Keep talking and you will see what happens when we stop.")])
    table = build_fact_table(case)
    cert = evaluate(case, table)
    assert not any((f.value or {}).get("keyword_hint") for f in table.facts if f.source == "chat" and f.value and "idx" in f.value)
    r = ruling(ruling="escalate", escalate=True, safety_concern="suspected", safety_basis=["F9"], reasoning="summary [F1][SAFE-1]", cited_policy=["SAFE-1"])
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and out.ruling == "escalate" and "safety concern suspected" in (out.escalation_reason or "")
    # a concern that the judge records but does not act on is acted on by code
    out2, _ = verify_ruling(ruling(ruling="no_action", safety_concern="suspected", safety_basis=["F9"]), table, citable_ids(), certificate=cert)
    assert out2.escalate


# ---------------------------------------------------------------- missing evidence is a finding, not a verdict

def test_missing_gps_on_a_route_dispute_is_insufficient_not_no_detour():
    case = load("C-0001").model_copy(update={"gps": []})
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == ["escalate"] and "GPS" in (cert.insufficient or "")
    ok, why = check_ruling(cert, ruling(ruling="no_action"))
    assert not ok and any("insufficient" in w for w in why)


def test_gps_hole_is_insufficient():
    case = load("C-0001")
    t = case.trip.pickup_at + timedelta(minutes=4)
    case = case.model_copy(update={"gps": [p for p in case.gps if not (t <= p.ts <= t + timedelta(minutes=5))]})
    table = build_fact_table(case)
    assert any("gps_gap_s" in (f.value or {}) for f in table.facts)
    cert = evaluate(case, table)
    assert cert.allowed == ["escalate"] and "hole" in (cert.insufficient or "")


def test_missing_gps_on_a_no_show_does_not_refund_by_default():
    case = load("C-0004").model_copy(update={"gps": []})       # driver cancelled as a no-show: NS-1 needs his trace
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == ["escalate"] and cert.insufficient


def test_untimed_consent_message_is_flagged_for_the_judge():
    case = load("C-0001")
    chat = [m.model_copy(update={"ts": None}) if m.sender == "rider" else m for m in case.chat]
    case = case.model_copy(update={"chat": chat})
    table = build_fact_table(case)
    rec = next(f for f in table.facts if (f.value or {}).get("count") is not None and "complete" in f.value)
    assert rec.value["complete"] is False
    cert = evaluate(case, table)
    rd5 = [p for p in judge_items(cert) if p.clause == "RD-5"]
    assert rd5 and all("undetermined" in p.detail for p in rd5)
    seg = list(cert.segments)[0]
    untimed = [f for f, m in cert.chat_index.items() if m["from"] == "rider" and not m["ts"]]
    ok, why = check_ruling(cert, ruling(ruling="no_action", segment_findings=[_sf(fact_id=s, finding="exempt", basis=untimed, reason="x") for s in cert.segments]))
    assert not ok and any("before the segment" in w for w in why)              # an untimed message cannot be "before"


def test_metered_trip_without_distance_fare_is_insufficient():
    case = load("C-0001")
    case = case.model_copy(update={"fare": case.fare.model_copy(update={"distance_km": 0, "distance_fare": 0})})
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == ["escalate"] and "amount cannot be computed" in (cert.insufficient or "")


# ---------------------------------------------------------------- the judge's escalate stands

def test_undetermined_finding_blocks_execution_and_escalate_is_kept():
    case = load("C-0001")
    table = build_fact_table(case)
    cert = evaluate(case, table)
    segs = list(cert.segments)
    f = [_sf(fact_id=segs[0], finding="undetermined", reason="x")] + [_sf(fact_id=s, finding="counts", reason="x") for s in segs[1:]]
    ok, why = check_ruling(cert, ruling(ruling="no_action", segment_findings=f))
    assert not ok and any("undetermined" in w for w in why)
    out, lines = verify_ruling(ruling(ruling="escalate", escalate=True, segment_findings=f), table, citable_ids(), certificate=cert)
    assert out.escalate and "undetermined" in (out.escalation_reason or "")


def test_evidence_gap_escalate_is_not_reset_by_the_verifier():
    case = load("C-0004")
    table = build_fact_table(case)
    cert = evaluate(case, table)
    r = ruling(ruling="escalate", escalate=True, evidence_status="insufficient", evidence_gap="the arrival tap time contradicts the trace and the record does not say which is right", cited_policy=["NS-1"])
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and out.ruling == "escalate" and "evidence insufficient" in (out.escalation_reason or "")   # never turned back into a ruling
    ok, why = check_ruling(cert, r)
    assert not ok and any("end to end" in w for w in why)                      # ...but on a case the trace settles, the judge is asked once more first


# ---------------------------------------------------------------- an escalate needs a ground the trace leaves open

def test_undetermined_on_a_code_settled_segment_is_not_a_ground():
    case = load("C-0003")                                                      # RD-4 incident: code settled the segment exempt
    table = build_fact_table(case)
    cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is not None)
    r = ruling(ruling="escalate", escalate=True, segment_findings=[_sf(fact_id=seg, finding="undetermined", reason="RD-4 unclear")])
    ok, why = check_ruling(cert, r)
    assert not ok and any("settled that segment" in w for w in why)
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and any("not leave open" in l for l in lines)          # still a person's case, but recorded as such


def test_escalate_on_a_mechanical_case_without_a_missing_fact_is_sent_back():
    case = load("C-0005")                                                      # rider cancelled: NS-4 settles it end to end
    cert = evaluate(case, build_fact_table(case))
    assert cert.mechanical
    ok, why = check_ruling(cert, ruling(ruling="escalate", escalate=True, evidence_status="insufficient", evidence_gap="the gap is interpretive, not evidentiary"))
    assert not ok and any("settles this case end to end" in w for w in why)
    ok, why = check_ruling(cert, ruling(ruling="escalate", escalate=True))
    assert not ok and any("without a ground" in w for w in why)
    ok, _ = check_ruling(cert, ruling(ruling="escalate", escalate=True, safety_concern="suspected", safety_basis=["F6"]))
    assert ok


def test_exempt_finding_cannot_rest_on_rd4_the_trace_rejected():
    case = load("C-0001")
    table = build_fact_table(case)
    cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None)
    rider_before = [f for f, m in cert.chat_index.items() if m["from"] == "rider" and not m["statement"] and m["ts"] < cert.segments[seg]["start"]]
    others = [_sf(fact_id=s, finding="exempt" if sg["exempt"] else "counts", basis=rider_before, reason="[RD-5]") for s, sg in cert.segments.items() if s != seg]
    r = ruling(ruling="no_action", segment_findings=[_sf(fact_id=seg, finding="exempt", basis=rider_before, reason="the accident on record exempts it [RD-4]")] + others)
    ok, why = check_ruling(cert, r)
    assert not ok and any("rests on RD-4" in w for w in why)


# ---------------------------------------------------------------------------- a finding is held to its ground

def test_every_ground_but_other_has_one_consequence():
    from core.schemas import GROUND_CONSEQUENCE, Ground
    import typing
    grounds = set(typing.get_args(Ground))
    assert grounds - set(GROUND_CONSEQUENCE) == {"other"}
    assert set(GROUND_CONSEQUENCE.values()) == {"exempt", "counts", "undetermined"}


def test_finding_that_contradicts_its_ground_is_blocked_and_other_cannot_execute():
    """B-0011's failure shape: the judge recognises a rider-named stop (RD-3(a)) and still refunds. With the ground
    named, code sees the contradiction; a finding on no named ground cannot execute either."""
    case = load("C-0001")                                             # segment 1 is settled by RD-4; the 7-Eleven loop is the judge's
    table = build_fact_table(case); cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None)
    rider_before = [f.id for f in table.facts if f.source == "chat" and f.value.get("from") == "rider"][:1]
    bad = ruling(ruling="refund_partial", amount=expected_amount(cert, {seg: False}),
                 segment_findings=[SegmentFinding(fact_id=seg, finding="counts", ground="rider_named_stop", basis=rider_before, reason="[RD-3]")])
    ok, why = check_ruling(cert, bad)
    assert not ok and any("rider_named_stop" in w and "exempt" in w for w in why), why
    vague = ruling(ruling="refund_partial", amount=expected_amount(cert, {seg: False}),
                   segment_findings=[SegmentFinding(fact_id=seg, finding="counts", ground="other", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, vague)
    assert not ok and any("no named ground" in w for w in why), why
    settled = [SegmentFinding(fact_id=s, finding="exempt" if sg["exempt"] else "counts", ground="incident" if sg["exempt"] else "consent_after_or_none", reason="[RD-4]")
               for s, sg in cert.segments.items() if sg["exempt"] is not None]
    good = ruling(ruling="refund_partial", amount=expected_amount(cert, {seg: False}),
                  segment_findings=settled + [SegmentFinding(fact_id=seg, finding="counts", ground="consent_after_or_none", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, good)
    assert ok, why


# ---------------------------------------------------------------------------- a ground both advocates state binds the judge

def test_stipulated_ground_binds_the_judge_and_needs_both_sides():
    from core.orchestrate import stipulated_grounds
    from core.schemas import CaseBrief, Rebuttal, RequestedOutcome
    case = load("C-0001")
    table = build_fact_table(case); cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None)
    settled = next(s for s, sg in cert.segments.items() if sg["exempt"] is not None)
    brief = lambda side, g: CaseBrief(side=side, claims=[], weaknesses=["x"], requested_outcome=RequestedOutcome(action="no_action", amount=None), segment_grounds={seg: g, settled: "incident"})
    # one side only, or "other": nothing is stipulated; a settled segment never is
    assert stipulated_grounds(cert, {"rider": brief("rider", "rider_named_stop"), "driver": brief("driver", "consent_after_or_none")}, {}) == {}
    assert stipulated_grounds(cert, {"rider": brief("rider", "other"), "driver": brief("driver", "other")}, {}) == {}
    # both sides agree in their briefs; a rebuttal may revise one side and dissolve the agreement
    both = {"rider": brief("rider", "rider_named_stop"), "driver": brief("driver", "rider_named_stop")}
    assert stipulated_grounds(cert, both, {}) == {seg: "rider_named_stop"}
    reb = {"rider": Rebuttal(side="rider", points=[], segment_grounds={seg: "scope_other"})}
    assert stipulated_grounds(cert, both, reb) == {}
    # the judge's finding must rest on the stipulated ground: a different ground is sent back, the right one passes
    rider_before = [f.id for f in table.facts if f.source == "chat" and f.value.get("from") == "rider"][:1]
    base = [SegmentFinding(fact_id=settled, finding="exempt", ground="incident", reason="[RD-4]")]
    wrong = ruling(ruling="refund_partial", amount=expected_amount(cert, {seg: False}),
                   segment_findings=base + [SegmentFinding(fact_id=seg, finding="counts", ground="scope_other", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, wrong, {seg: "rider_named_stop"})
    assert not ok and any("stipulated" in w for w in why), why
    right = ruling(ruling="no_action", amount=None,
                   segment_findings=base + [SegmentFinding(fact_id=seg, finding="exempt", ground="rider_named_stop", basis=rider_before, reason="[RD-3]")])
    ok, why = check_ruling(cert, right, {seg: "rider_named_stop"})
    assert ok, why
