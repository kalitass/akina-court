"""Meaning is read by the court, measured things by code, and missing evidence is a finding of its own.

Acceptance list (no model call; the engine, the verifier and the fact tools are exercised with real case files):
  * a paraphrased agreement leaves the consent question open to the judge instead of closing it
  * a negated "okay" is not labelled agreement; nothing in the fact table labels meaning at all
  * "I cannot find you at the pickup point" does not force an escalation; a threat without a keyword can still escalate
  * an exempt finding must rest on a rider message sent before the segment, never on the driver's statement alone
  * missing GPS, a hole in the trace, an untimed message, a metered trip without a distance fare: no ruling for either side
  * the judge's own escalate (undetermined finding, safety concern, evidence gap) is kept by the verifier when the trace
    leaves something open; on a case the trace settles end to end, the one outcome the policy allows is carried out
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


def bench(cid):
    from core.case_format import read_case
    return Case.model_validate(read_case(ROOT / "data" / "bench" / "cases" / f"{cid}.json"))


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
    case = with_chat(bench("B-0013"), [(0, "driver", "ok if I go round by West Coast Road?"), (40, "rider", "I am not okay with this detour.")])
    table = build_fact_table(case)
    assert not any("agreement" in (f.value or {}).get("flags", []) for f in table.facts)
    assert not any("[agreement]" in f.text for f in table.facts)
    cert = evaluate(case, table)
    open_segs = [s for s, sg in cert.segments.items() if sg["exempt"] is None]          # the rider wrote before the segment: the judge reads it
    assert open_segs
    f = [_sf(fact_id=s, finding="counts" if sg["exempt"] is None else "exempt", reason="refused [RD-5]") for s, sg in cert.segments.items()]
    amount = expected_amount(cert, {x.fact_id: x.exempt for x in f})
    r = ruling(ruling="refund_partial", amount=amount, segment_findings=f)
    ok, why = check_ruling(cert, r)
    assert ok, why


def test_exempt_finding_needs_a_rider_message_before_the_segment():
    case = bench("B-0015")                                     # rider's "ok" before both off-route segments
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


def test_evidence_gap_escalate_is_kept_when_the_trace_leaves_the_gap_open():
    case = bench("B-0035")                                     # a hole in the GPS during the wait that could decide the case
    table = build_fact_table(case)
    cert = evaluate(case, table)
    assert cert.insufficient and cert.allowed == ["escalate"]
    r = ruling(ruling="escalate", escalate=True, evidence_status="insufficient", evidence_gap="the GPS trace has a hole during the wait", cited_policy=["NS-1"])
    ok, why = check_ruling(cert, r)
    assert ok, why
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate and out.ruling == "escalate" and "evidence insufficient" in (out.escalation_reason or "")   # never turned back into a ruling


def test_evidence_gap_escalate_on_a_case_the_trace_settles_is_carried_out():
    case = bench("B-0030")                                     # driver cancelled after 4 min 50 s: NS-1 (ii) fails, the fee is refunded
    table = build_fact_table(case)
    cert = evaluate(case, table)
    assert cert.mechanical and cert.allowed == ["refund_full", "escalate"] and not cert.elements
    r = ruling(ruling="escalate", escalate=True, evidence_status="insufficient", evidence_gap="the arrival tap time contradicts the trace and the record does not say which is right", cited_policy=["NS-1"])
    ok, why = check_ruling(cert, r)
    assert not ok and any("end to end" in w for w in why)
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert not out.escalate and out.ruling == "refund_full" and out.amount == 5.00 and out.evidence_status == "sufficient"
    assert any("carried out as the policy requires" in l for l in lines)
    # a safety concern is always a ground of its own: kept as an escalate
    out2, _ = verify_ruling(r.model_copy(update={"safety_concern": "suspected", "safety_basis": ["F10"]}), table, citable_ids(), certificate=cert)
    assert out2.escalate and out2.ruling == "escalate"


# ---------------------------------------------------------------- an escalate needs a ground the trace leaves open

def test_undetermined_on_a_code_settled_segment_is_not_a_ground():
    case = bench("B-0016")                                     # no rider message before the detour: code settled it (counts)
    table = build_fact_table(case)
    cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is not None)
    assert cert.mechanical and cert.allowed == ["refund_partial", "escalate"]
    r = ruling(ruling="escalate", escalate=True, segment_findings=[_sf(fact_id=seg, finding="undetermined", reason="consent unclear [RD-5]")])
    ok, why = check_ruling(cert, r)
    assert not ok and any("settled that segment" in w for w in why)
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    # the trace settles the case end to end: the one outcome it allows is carried out, at the RD-2 amount
    assert not out.escalate and out.ruling == "refund_partial" and any("carried out as the policy requires" in l for l in lines)
    assert out.amount == expected_amount(cert, {}) == 4.08


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


def test_exempt_finding_cannot_rest_on_rd4():
    """RD-2 (v3): a traffic reason never exempts a segment, whether the judge says so in words or names the ground."""
    case = load("C-0001")
    table = build_fact_table(case)
    cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None and sg["traffic"])
    rider_before = [f for f, m in cert.chat_index.items() if m["from"] == "rider" and not m["statement"] and m["ts"] < cert.segments[seg]["start"]]
    others = [_sf(fact_id=s, finding="counts", reason="[RD-5]") for s in cert.segments if s != seg]
    r = ruling(ruling="no_action", segment_findings=[_sf(fact_id=seg, finding="exempt", basis=rider_before, reason="the accident on record exempts it [RD-4]")] + others)
    ok, why = check_ruling(cert, r)
    assert not ok and any("rests on RD-4" in w for w in why)
    r2 = ruling(ruling="no_action", segment_findings=[SegmentFinding(fact_id=seg, finding="exempt", ground="incident", reason="[RD-4]")] + others)
    ok, why = check_ruling(cert, r2)
    assert not ok and any("traffic reason does not exempt" in w for w in why), why


# ---------------------------------------------------------------------------- a finding is held to its ground

def test_every_ground_but_other_has_one_consequence():
    from core.schemas import GROUND_CONSEQUENCE, Ground
    import typing
    grounds = set(typing.get_args(Ground))
    assert grounds - set(GROUND_CONSEQUENCE) == {"other"}
    assert set(GROUND_CONSEQUENCE.values()) == {"exempt", "counts", "undetermined"}


def test_finding_that_contradicts_its_ground_is_blocked_and_other_cannot_execute():
    """A known failure shape: the judge recognises a rider-named stop (RD-3) and still refunds. With the ground
    named, code sees the contradiction; a finding on no named ground cannot execute either."""
    table, cert, seg, base, rider_before = _open_segments()
    amt = expected_amount(cert, {**{b.fact_id: b.exempt for b in base}, seg: False})
    bad = ruling(ruling="refund_partial", amount=amt,
                 segment_findings=base + [SegmentFinding(fact_id=seg, finding="counts", ground="rider_named_stop", basis=rider_before, reason="[RD-3]")])
    ok, why = check_ruling(cert, bad)
    assert not ok and any("rider_named_stop" in w and "exempt" in w for w in why), why
    vague = ruling(ruling="refund_partial", amount=amt,
                   segment_findings=base + [SegmentFinding(fact_id=seg, finding="counts", ground="other", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, vague)
    assert not ok and any("no named ground" in w for w in why), why
    good = ruling(ruling="refund_partial", amount=amt,
                  segment_findings=base + [SegmentFinding(fact_id=seg, finding="counts", ground="consent_after_or_none", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, good)
    assert ok, why


# ---------------------------------------------------------------------------- a ground both advocates state is advice, not a binding

def test_stipulated_ground_needs_both_sides_and_informs_but_does_not_bind_the_judge():
    from core.orchestrate import stipulated_grounds
    from core.policy_engine import code_confidence
    from core.schemas import CaseBrief, Rebuttal, RequestedOutcome
    table, cert, seg, base, rider_before = _open_segments()
    brief = lambda side, g: CaseBrief(side=side, claims=[], weaknesses=["x"], requested_outcome=RequestedOutcome(action="no_action", amount=None), segment_grounds={seg: g})
    # one side only, or "other": nothing is stipulated
    assert stipulated_grounds(cert, {"rider": brief("rider", "rider_named_stop"), "driver": brief("driver", "consent_after_or_none")}, {}) == {}
    assert stipulated_grounds(cert, {"rider": brief("rider", "other"), "driver": brief("driver", "other")}, {}) == {}
    # both sides agree in their briefs; a rebuttal may revise one side and dissolve the agreement
    both = {"rider": brief("rider", "rider_named_stop"), "driver": brief("driver", "rider_named_stop")}
    assert stipulated_grounds(cert, both, {}) == {seg: "rider_named_stop"}
    reb = {"rider": Rebuttal(side="rider", points=[], segment_grounds={seg: "scope_other"})}
    assert stipulated_grounds(cert, both, reb) == {}
    # the judge may read the words otherwise: a different ground is not sent back, but the reading then rests on nothing
    # else and the code confidence drops (TH-3); following the stipulation keeps it at 100%
    other = ruling(ruling="refund_partial", amount=expected_amount(cert, {**{b.fact_id: b.exempt for b in base}, seg: False}),
                   segment_findings=base + [SegmentFinding(fact_id=seg, finding="counts", ground="scope_other", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, other, {seg: "rider_named_stop"})
    assert ok, why
    right = ruling(ruling="no_action", amount=None,
                   segment_findings=base + [SegmentFinding(fact_id=seg, finding="exempt", ground="rider_named_stop", basis=rider_before, reason="[RD-3]")])
    ok, why = check_ruling(cert, right, {seg: "rider_named_stop"})
    assert ok, why
    stip = {seg: "rider_named_stop", base[0].fact_id: "general_route_consent"}
    assert code_confidence(cert, right, stip) == 1.0
    assert code_confidence(cert, other, stip) == 0.9


def test_a_code_settled_segment_is_never_stipulated():
    from core.orchestrate import stipulated_grounds
    from core.schemas import CaseBrief, RequestedOutcome
    case = load("C-0002")
    cert = evaluate(case, build_fact_table(case))
    settled = next(s for s, sg in cert.segments.items() if sg["exempt"] is not None)
    brief = lambda side: CaseBrief(side=side, claims=[], weaknesses=["x"], requested_outcome=RequestedOutcome(action="no_action", amount=None), segment_grounds={settled: "general_route_consent"})
    assert stipulated_grounds(cert, {"rider": brief("rider"), "driver": brief("driver")}, {}) == {}


# ---------------------------------------------------------------------------- the judge decides between the grounds the parties argued

def _open_segments():
    """B-0015 has two open segments (the rider's "ok" came before both). The second is the one under test; the first is
    held exempt on the rider's general route consent so the amount is fixed by the second alone. The road names are taken
    off the GPS samples, so no named-road check applies and the segments stay the judge's to read."""
    case = bench("B-0015")
    case = case.model_copy(update={"gps": [p.model_copy(update={"road": None}) for p in case.gps]})
    table = build_fact_table(case); cert = evaluate(case, table)
    first, seg = list(cert.segments)[:2]
    rider_before = [f.id for f in table.facts if f.source == "chat" and f.value.get("from") == "rider"][:1]
    base = [SegmentFinding(fact_id=first, finding="exempt", ground="general_route_consent", basis=rider_before, reason="[RD-5]")]
    return table, cert, seg, base, rider_before


def test_argued_grounds_inform_the_judge_but_do_not_limit_it():
    """v3: both advocates can miss the right reading, so a finding on a ground neither side argued may still execute."""
    table, cert, seg, base, rider_before = _open_segments()
    argued = {seg: {"rider": ["named_road_untied"], "driver": ["general_route_consent"]}}
    unargued = ruling(ruling="refund_partial", amount=expected_amount(cert, {**{b.fact_id: b.exempt for b in base}, seg: False}),
                      segment_findings=base + [SegmentFinding(fact_id=seg, finding="counts", ground="driver_errand", basis=rider_before, reason="[RD-5]")])
    for a in (argued, {seg: {"rider": ["scope_other"], "driver": ["general_route_consent"]}}, None, {seg: {"rider": [], "driver": []}}):
        ok, why = check_ruling(cert, unargued, None, a)
        assert ok, (a, why)
    # the ground still fixes the consequence, argued or not
    wrong = unargued.model_copy(update={"segment_findings": base + [SegmentFinding(fact_id=seg, finding="counts", ground="general_route_consent", basis=rider_before, reason="[RD-5]")]})
    ok, why = check_ruling(cert, wrong, None, argued)
    assert not ok and any("means exempt" in w for w in why), why
    # exempt on the driver's argued ground passes (the rider disputes that consent exists, not what kind it was)
    argued_ok = ruling(ruling="no_action", amount=None,
                       segment_findings=base + [SegmentFinding(fact_id=seg, finding="exempt", ground="general_route_consent", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, argued_ok, None, {seg: {"rider": ["consent_after_or_none"], "driver": ["general_route_consent"]}})
    assert ok, why
    # undetermined is always open to the judge, argued or not
    und = ruling(ruling="escalate", escalate=True, amount=None,
                 segment_findings=base + [SegmentFinding(fact_id=seg, finding="undetermined", ground="scope_other", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, und, None, argued)
    assert ok, why


def test_undetermined_on_a_stipulated_ground_is_sent_back_once():
    table, cert, seg, base, rider_before = _open_segments()
    und = ruling(ruling="escalate", escalate=True, amount=None,
                 segment_findings=base + [SegmentFinding(fact_id=seg, finding="undetermined", ground="general_route_consent", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, und, {seg: "general_route_consent"})
    assert not ok and any("stipulated" in w for w in why), why
    ok, why = check_ruling(cert, und, {seg: "named_road_untied"})      # the stipulated ground itself means undetermined: fine
    assert ok, why
    ok, why = check_ruling(cert, und, None)                            # no advocates: an undetermined finding is a ground to escalate
    assert ok, why


def test_advocate_output_must_state_a_ground_for_every_segment():
    from core.agents.advocate import missing_grounds
    table, cert, seg, base, rider_before = _open_segments()
    segs = [f.id for f in table.facts if f.source == "gps" and f.text.startswith("Off-route segment")]
    assert segs and missing_grounds(table, {}) == segs
    assert missing_grounds(table, {s: "general_route_consent" for s in segs}) == []
    ns = load("C-0005"); nt = build_fact_table(ns)
    assert nt.dispute_type != "route_deviation" and missing_grounds(nt, {}) == []


def test_exemption_cannot_execute_while_the_kind_of_agreement_is_contested():
    table, cert, seg, base, rider_before = _open_segments()
    ex = ruling(ruling="no_action", amount=None,
                segment_findings=base + [SegmentFinding(fact_id=seg, finding="exempt", ground="general_route_consent", basis=rider_before, reason="[RD-5]")])
    # one side reads a general route choice, the other an agreement to a named road: sent back (undetermined → a person)
    ok, why = check_ruling(cert, ex, None, {seg: {"rider": ["named_road_untied"], "driver": ["general_route_consent"]}})
    assert not ok and any("contested" in w for w in why), why
    # the same disagreement, exempt on the named-road side: also sent back
    ex2 = ruling(ruling="no_action", amount=None,
                 segment_findings=base + [SegmentFinding(fact_id=seg, finding="exempt", ground="named_road_tied", basis=rider_before, reason="[RD-5]")])
    ok, why = check_ruling(cert, ex2, None, {seg: {"rider": ["named_road_tied"], "driver": ["general_route_consent"]}})
    assert not ok and any("contested" in w for w in why), why
    # both sides read the same kind (consent exists or not is a different question): the exemption may execute
    ok, why = check_ruling(cert, ex, None, {seg: {"rider": ["consent_after_or_none"], "driver": ["general_route_consent"]}})
    assert ok, why
    ok, why = check_ruling(cert, ex2, None, {seg: {"rider": ["named_road_untied"], "driver": ["named_road_tied"]}})
    assert ok, why


def _c0003_with_roads(roads: list[str]):
    """C-0003: the rider said "Ok" to the driver's "I'll go by ECP instead" before the detour. `roads` are written on
    the GPS samples inside the off-route segment (the official record's location_desc)."""
    case = load("C-0003")
    cert = evaluate(case, build_fact_table(case))
    sg = next(iter(cert.segments.values()))
    start, end = sg["start"], sg["end"]
    # the v3 demo record names the roads on every sample: they are taken off, and only `roads` are written in the segment
    gps = [p.model_copy(update={"road": roads[i % len(roads)] if roads and start <= p.ts.isoformat() <= end else None}) for i, p in enumerate(case.gps)]
    return case.model_copy(update={"gps": gps})


def test_tied_ground_is_read_as_untied_when_nothing_on_record_can_tie_the_segment():
    from core.orchestrate import argued_grounds, ground_corrections, record_grounds, stipulated_grounds
    from core.policy_engine import tie_possible
    from core.schemas import CaseBrief, RequestedOutcome
    case = _c0003_with_roads([])                            # both messages precede the segment, no stop in it, no road names
    table = build_fact_table(case); cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None)
    assert not cert.segments[seg]["stops"] and not cert.segments[seg]["roads"] and not tie_possible(cert, seg)
    assert record_grounds(cert, {seg: "named_road_tied"}) == {seg: "named_road_untied"}
    assert record_grounds(cert, {seg: "general_route_consent"}) == {seg: "general_route_consent"}
    brief = lambda side, g: CaseBrief(side=side, claims=[], weaknesses=["x"], requested_outcome=RequestedOutcome(action="no_action", amount=None), segment_grounds={seg: g})
    both = {"rider": brief("rider", "named_road_tied"), "driver": brief("driver", "named_road_tied")}
    assert stipulated_grounds(cert, both, {}) == {seg: "named_road_untied"}
    assert argued_grounds(cert, both, {})[seg] == {"rider": ["named_road_untied"], "driver": ["named_road_untied"]}
    assert len(ground_corrections(cert, both, {})) == 2
    # road names on the segment's samples make a tie possible, and the ground is left as stated
    c2 = evaluate(_c0003_with_roads(["EAST COAST PARKWAY"]), build_fact_table(_c0003_with_roads(["EAST COAST PARKWAY"])))
    assert c2.segments[seg]["roads"] == ["EAST COAST PARKWAY"] and tie_possible(c2, seg)
    assert record_grounds(c2, {seg: "named_road_tied"}) == {seg: "named_road_tied"}
    # a stop measured inside the segment (C-0001's 7-Eleven loop) also makes a tie possible
    c1 = load("C-0001"); cc = evaluate(c1, build_fact_table(c1))
    assert any(tie_possible(cc, s) for s, sg in cc.segments.items() if sg["stops"])


def test_named_road_consent_is_checked_against_the_roads_the_segment_drove():
    """RD-5 (v3): the judge reads WHICH road the rider agreed to (named_road); code says whether the segment drove it."""
    case = _c0003_with_roads(["Tampines Avenue 10", "EAST COAST PARKWAY", "ECP"])
    table = build_fact_table(case); cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None)
    seg_fact = next(f for f in table.facts if f.id == seg)
    assert "Roads driven:" in seg_fact.text and "EAST COAST PARKWAY" in seg_fact.value["roads"]
    rider = [f for f, m in cert.chat_index.items() if m["from"] == "rider"]
    f = lambda ground, named, finding: ruling(ruling="no_action" if finding == "exempt" else "refund_partial",
                                             amount=None if finding == "exempt" else expected_amount(cert, {seg: False}),
                                             segment_findings=[SegmentFinding(fact_id=seg, finding=finding, ground=ground, named_road=named, basis=rider, reason="[RD-5]")])
    ok, why = check_ruling(cert, f("named_road_tied", "East Coast Parkway", "exempt"))
    assert ok, why                                                      # case does not matter
    ok, why = check_ruling(cert, f("named_road_tied", "ECP", "exempt"))
    assert ok, why
    ok, why = check_ruling(cert, f("named_road_tied", "Pan Island Expressway", "exempt"))
    assert not ok and any("named_road_elsewhere" in w for w in why), why
    ok, why = check_ruling(cert, f("named_road_elsewhere", "Pan Island Expressway", "counts"))
    assert ok, why
    ok, why = check_ruling(cert, f("named_road_untied", "ECP", "undetermined").model_copy(update={"ruling": "no_action", "amount": None}))
    assert not ok and any("named_road_tied" in w for w in why), why     # roads are on record: untied is not a reading
    ok, why = check_ruling(cert, f("named_road_tied", None, "exempt"))
    assert not ok and any("needs named_road" in w for w in why), why


def test_untied_escalate_is_sent_back_when_the_roads_are_on_record():
    case = _c0003_with_roads(["EAST COAST PARKWAY"])
    cert = evaluate(case, build_fact_table(case))
    seg = next(iter(cert.segments))
    r = ruling(ruling="escalate", escalate=True, segment_findings=[
        SegmentFinding(fact_id=seg, finding="undetermined", ground="named_road_untied", named_road="ECP", reason="[RD-5]")])
    ok, why = check_ruling(cert, r)
    assert not ok and any("named_road_tied" in w for w in why), why


def test_tolerance_applies_after_exempt_segments():
    """C-0003: deviation 1.28 km, one 0.80 km segment. Exempt → 0.48 km left, within the 1 km tolerance → no refund;
    counts → the whole 1.28 km is refunded."""
    case = load("C-0003")
    cert = evaluate(case, build_fact_table(case))
    seg = next(iter(cert.segments))
    assert cert.deviation_km == pytest.approx(1.28, abs=0.01)
    assert expected_amount(cert, {seg: True}) == 0.0
    assert expected_amount(cert, {seg: False}) == round(cert.deviation_km * cert.rate_per_km + 1e-9, 2)
    assert expected_amount(cert, {}) is None                           # an open segment with no finding: nothing can execute


def test_rebuttal_verification_keeps_the_segment_grounds():
    from core.schemas import CaseBrief, Rebuttal, RequestedOutcome, RebuttalPoint
    from core.verify import verify_rebuttal
    case = load("C-0001")
    table = build_fact_table(case); cert = evaluate(case, table)
    seg = next(s for s, sg in cert.segments.items() if sg["exempt"] is None)
    own = CaseBrief(side="rider", claims=[], weaknesses=["x"], requested_outcome=RequestedOutcome(action="no_action", amount=None))
    reb = Rebuttal(side="rider", points=[RebuttalPoint(target_claim_id="D1", response="x [F1][RD-1]", facts=["F1"], policy=["RD-1"])], segment_grounds={seg: "scope_other"})
    out, _ = verify_rebuttal(reb, own, own, table, citable_ids(), seen={"F1"})
    assert out.segment_grounds == {seg: "scope_other"}


def test_no_rider_message_before_the_segment_is_settled_by_code():
    """RD-5 / RD-3 both need a rider message sent before the segment: with none (only later messages, or only the driver's
    statement) code settles the segment as counting, and nothing about it is left to the judge."""
    case = bench("B-0012")                                     # the rider's only message comes after the segment started
    table = build_fact_table(case); cert = evaluate(case, table)
    seg = next(iter(cert.segments))
    rider = [c for c in cert.chat_index.values() if c["from"] == "rider" and not c["statement"]]
    assert rider and all(c["ts"] >= cert.segments[seg]["start"] for c in rider)
    assert cert.segments[seg]["exempt"] is False and "after the segment started" in next(p for p in cert.predicates if p.clause == "RD-5" and p.subject == seg).detail
    assert not judge_items(cert) or all(p.clause == "SAFE-1" for p in judge_items(cert))
    # only the driver's statement on record (B-0016: the rider's words are in an unrecorded call): a claim, not consent → settled too
    c5 = bench("B-0016")
    t5 = build_fact_table(c5); k5 = evaluate(c5, t5)
    assert all(sg["exempt"] is False for sg in k5.segments.values())
    # a rider message before the segment keeps the question open (C-0001)
    c1 = load("C-0001"); k1 = evaluate(c1, build_fact_table(c1))
    assert any(sg["exempt"] is None for sg in k1.segments.values())
