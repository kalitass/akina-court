"""The v3 rules the engine executes by code (no model call): no-show contact duty and free wait, driver did not arrive,
repeat no-shows, surge refunds, the system-or-person thresholds, citation scope and the refund wording."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from core.facts.tools import build_fact_table
from core.notices import consistent, fallback_notices
from core.policy_engine import (CANCEL_FEE, FREE_WAIT_S, GOODWILL, check_ruling, code_confidence, evaluate,
                                threshold_check)
from core.schemas import AccountRecord, CallRecord, Case, ChatMessage, ElementFinding, Ruling, SurgeLog
from core.verify import scope_citations
from test_facts import T0, no_show_case

ROOT = Path(__file__).resolve().parents[1]


def load(cid):
    return Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))


def ruling(**kw):
    base = dict(ruling="no_action", recommended_action="x", confidence=0.9, reasoning="[F1][NS-1]", cited_facts=["F1"], cited_policy=["NS-1"],
                safety_concern="none", evidence_status="sufficient")
    base.update(kw)
    return Ruling(**base)


def tapped(case):
    """no_show_case with the arrival confirmation at the moment the car stops."""
    return case.model_copy(update={"trip": case.trip.model_copy(update={"driver_pressed_here_at": case.trip.driver_arrived_at})})


def reading(eid, finding, basis=("F1",)):
    return ElementFinding(element=eid, finding=finding, basis=list(basis), reason="[F1][NS-0]")


# NS-1 (i)-(iv) hold and the driver wrote to the rider: why he cancelled is the judge's reading (NS-0 / NS-3)
NS1_HOLDS = ["no_action", "refund_full", "escalate"]


def element(cert, prefix):
    return next(p for p in cert.predicates if p.clause == "NS-1" and p.element.startswith(prefix))


# ---------------------------------------------------------------------------- NS-1 (iii): message AND call

def test_defaults_are_the_official_ones():
    assert (CANCEL_FEE, FREE_WAIT_S, GOODWILL) == (5.00, 300, 5.00)


@pytest.mark.parametrize("chat,ok", [
    ([("driver", "message"), ("driver", "call")], True),
    ([("driver", "message")], False),                        # no call
    ([("driver", "call")], False),                           # no message
    ([("rider", "message"), ("rider", "call")], False),      # the rider's contact is not the driver's duty
    ([], False),
])
def test_driver_must_message_and_call_before_cancelling(chat, ok):
    case = tapped(no_show_case(stop_offset_m=40, wait_s=360, contact=False))
    msgs = [ChatMessage(ts=T0 + timedelta(seconds=10 * i), **{"from": who}, text="hi", kind=kind) for i, (who, kind) in enumerate(chat)]
    case = case.model_copy(update={"chat": msgs})
    cert = evaluate(case, build_fact_table(case))
    iii = element(cert, "(iii)")
    assert (iii.status == "pass") is ok, iii.detail
    assert cert.allowed == (NS1_HOLDS if ok else ["refund_full", "escalate"])
    assert ("NS-0:reason" in cert.elements) is ok
    if not ok:
        assert cert.amount == 5.00


def test_a_call_after_the_cancellation_does_not_count():
    case = tapped(no_show_case(stop_offset_m=40, wait_s=360, contact=False))
    late = case.trip.cancelled_at + timedelta(seconds=30)
    case = case.model_copy(update={"chat": [ChatMessage(ts=T0, **{"from": "driver"}, text="hi"),
                                            ChatMessage(ts=late, **{"from": "driver"}, text="call", kind="call")]})
    assert element(evaluate(case, build_fact_table(case)), "(iii)").status == "fail"


def test_a_call_in_the_call_log_counts_and_the_same_call_logged_twice_counts_once():
    case = tapped(no_show_case(stop_offset_m=40, wait_s=360, contact=False))
    call_at = T0 + timedelta(seconds=20)
    only_log = case.model_copy(update={"chat": [ChatMessage(ts=T0, **{"from": "driver"}, text="hi")],
                                       "calls": [CallRecord(ts=call_at, caller="driver", callee="rider", answered=False)]})
    table = build_fact_table(only_log)
    contact = next(f for f in table.facts if f.value and "driver_calls" in f.value)
    assert contact.value == {"driver_messages": 1, "driver_calls": 1, "until": only_log.trip.cancelled_at.isoformat()}
    assert element(evaluate(only_log, table), "(iii)").status == "pass"
    both = only_log.model_copy(update={"chat": only_log.chat + [ChatMessage(ts=call_at + timedelta(seconds=40), **{"from": "driver"}, text="call", kind="call")]})
    assert next(f for f in build_fact_table(both).facts if f.value and "driver_calls" in f.value).value["driver_calls"] == 1


def test_disp002_contact_from_chat_and_app_events():
    case = load("DISP-002")
    table = build_fact_table(case)
    contact = next(f for f in table.facts if f.value and "driver_calls" in f.value)
    assert contact.value["driver_messages"] == 4 and contact.value["driver_calls"] == 1
    cert = evaluate(case, table)
    assert cert.allowed == NS1_HOLDS and cert.fraud_flag
    assert cert.elements["NS-0:reason"]["default"] == "met"          # the app reason is rider_no_show


# ---------------------------------------------------------------------------- NS-0 / NS-3: why the driver cancelled

def test_driver_cancel_reason_is_read_from_his_own_words():
    case = tapped(no_show_case(stop_offset_m=40, wait_s=360))
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == NS1_HOLDS and not cert.mechanical and cert.flag_required is None
    el = cert.elements["NS-0:reason"]
    assert el["outcome"] == {"met": "no_action", "not_met": "refund_full"}
    ok, why = check_ruling(cert, ruling(element_findings=[reading("NS-0:reason", "met")]))
    assert ok, why
    ok, why = check_ruling(cert, ruling(ruling="refund_full", amount=5.00, element_findings=[reading("NS-0:reason", "not_met")]))
    assert ok, why
    ok, why = check_ruling(cert, ruling(ruling="refund_full", amount=5.00, element_findings=[reading("NS-0:reason", "met")]))
    assert not ok and any("means no_action" in w for w in why)
    ok, why = check_ruling(cert, ruling())
    assert not ok and any("no element_findings entry for NS-0:reason" in w for w in why)
    ok, why = check_ruling(cert, ruling(element_findings=[reading("NS-0:reason", "undetermined")]))
    assert not ok and any("a person decides" in w for w in why)


# ---------------------------------------------------------------------------- NS-1 (ii): the free wait starts at the later of arrival and the scheduled time

def test_free_wait_starts_at_the_scheduled_time_when_the_driver_is_early():
    case = tapped(no_show_case(stop_offset_m=40, wait_s=420))          # 7 min at the pickup
    here = case.trip.driver_pressed_here_at
    on_time = case.model_copy(update={"trip": case.trip.model_copy(update={"scheduled_at": here})})
    assert element(evaluate(on_time, build_fact_table(on_time)), "(ii)").status == "pass"
    early = case.model_copy(update={"trip": case.trip.model_copy(update={"scheduled_at": here + timedelta(minutes=3)})})   # only 4 min after the scheduled time
    ii = element(evaluate(early, build_fact_table(early)), "(ii)")
    assert ii.status == "fail" and "scheduled time" in ii.detail


def test_a_record_stated_threshold_is_counted_from_arrival():
    case = load("DISP-002")                                   # arrived 08:43, scheduled 08:45, cancelled 08:51: 8 min from arrival
    ii = element(evaluate(case, build_fact_table(case)), "(ii)")
    assert ii.status == "pass" and "counted from arrival" in ii.detail


# ---------------------------------------------------------------------------- NS-4 / NS-8: the rider cancelled

@pytest.mark.parametrize("secs,allowed", [(180, ["refund_full", "escalate"]), (181, ["no_action", "escalate"])])
def test_rider_cancel_grace_is_three_minutes(secs, allowed):
    case = no_show_case(stop_offset_m=40, wait_s=360, cancelled_by="rider")
    case = case.model_copy(update={"trip": case.trip.model_copy(update={"cancelled_at": case.trip.accepted_at + timedelta(seconds=secs)})})
    case = case.model_copy(update={"gps": [p for p in case.gps if p.ts <= case.trip.cancelled_at] or case.gps[:1]})
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == allowed and any(p.clause == "NS-4" for p in cert.predicates)


def _driver_never_came(contact: bool):
    """Driver parked 600 m away; scheduled at acceptance; the rider cancelled 6 min later with the $5.00 fee charged."""
    case = no_show_case(stop_offset_m=600, wait_s=360, cancelled_by="rider", contact=contact)
    return case.model_copy(update={"trip": case.trip.model_copy(update={"scheduled_at": case.trip.accepted_at})})


def test_driver_did_not_arrive_refunds_the_fee_and_adds_goodwill_when_there_was_no_contact():
    case = _driver_never_came(contact=False)
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == ["refund_full", "escalate"] and cert.amount == 5.00 and cert.goodwill_required
    good = ruling(ruling="refund_full", amount=5.00, goodwill_credit=5.0, cited_policy=["NS-8"])
    ok, why = check_ruling(cert, good)
    assert ok, why
    ok, why = check_ruling(cert, good.model_copy(update={"goodwill_credit": None}))
    assert not ok and any("goodwill_credit" in w for w in why)


def test_driver_did_not_arrive_but_tried_to_reach_the_rider_gets_no_goodwill():
    case = _driver_never_came(contact=True)
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == ["refund_full", "escalate"] and not cert.goodwill_required
    ok, why = check_ruling(cert, ruling(ruling="refund_full", amount=5.00, goodwill_credit=5.0, cited_policy=["NS-8"]))
    assert not ok and any("does not call for it" in w for w in why)
    ok, why = check_ruling(cert, ruling(ruling="refund_full", amount=5.00, cited_policy=["NS-8"]))
    assert ok, why


# ---------------------------------------------------------------------------- NS-9: third no-show in 30 days

@pytest.mark.parametrize("prior,flag", [(None, False), (1, False), (2, True)])
def test_third_no_show_in_30_days_flags_the_rider(prior, flag):
    case = tapped(no_show_case(stop_offset_m=40, wait_s=360))
    case = case.model_copy(update={"profiles": case.profiles.model_copy(update={"rider_account": AccountRecord(no_shows_30d=prior)})})
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == NS1_HOLDS and cert.elements["NS-0:reason"]["flag_if_met"] is flag
    met = [reading("NS-0:reason", "met")]
    ok, why = check_ruling(cert, ruling(flag_account=flag, element_findings=met))
    assert ok, why
    ok, why = check_ruling(cert, ruling(flag_account=not flag, element_findings=met))
    assert not ok and any("flag_account" in w for w in why)
    # a reason of his own (NS-3) refunds the fee and is not a rider no-show: no flag
    ok, why = check_ruling(cert, ruling(ruling="refund_full", amount=5.00, element_findings=[reading("NS-0:reason", "not_met")]))
    assert ok, why


# ---------------------------------------------------------------------------- SURGE

def surge(**log):
    case = load("DISP-003")
    return case.model_copy(update={"surge": case.surge.model_copy(update=log)})


def test_disp003_refunds_the_surge_part():
    case = load("DISP-003")
    cert = evaluate(case, build_fact_table(case))
    assert cert.dispute_type == "fare_dispute" and cert.allowed == ["refund_partial", "escalate"] and cert.amount == 4.50
    ok, why = check_ruling(cert, ruling(ruling="refund_partial", amount=4.50, cited_policy=["SURGE-2"]))
    assert ok, why
    ok, why = check_ruling(cert, ruling(ruling="refund_partial", amount=7.50, cited_policy=["SURGE-2"]))
    assert not ok and any("amount" in w for w in why)


NOTICE = "Surge pricing is now 1.5x. Your revised estimated fare is $13.50. You may cancel now without penalty."
JUDGE_READS = ["refund_partial", "no_action", "escalate"]          # SURGE-1:notice — whether the text states all three items


@pytest.mark.parametrize("log,allowed", [
    (dict(rider_notified=True, notification_method="in_app", notification_text=NOTICE, at=-60), JUDGE_READS),
    (dict(rider_notified=True, notification_method="in_app", notification_text=NOTICE, at=0), JUDGE_READS),       # at pickup counts
    (dict(rider_notified=True, notification_method="in_app", notification_text=NOTICE, at=+60), ["refund_partial", "escalate"]),   # after the trip started
    (dict(rider_notified=True, notification_method="sms", notification_text=NOTICE, at=-60), ["refund_partial", "escalate"]),       # not in-app
    (dict(rider_notified=True, notification_method="in_app", at=-60), ["escalate"]),       # in time, but the text of the notice is not on record
    (dict(rider_notified=False), ["refund_partial", "escalate"]),
])
def test_surge_notice_must_be_timely_and_complete(log, allowed):
    log = dict(log)
    at = log.pop("at", None)
    case = load("DISP-003")
    if at is not None:
        log["notification_timestamp"] = case.trip.pickup_at + timedelta(seconds=at)
    case = case.model_copy(update={"surge": case.surge.model_copy(update=log)})
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == allowed
    assert ("SURGE-1:notice" in cert.elements) is (allowed == JUDGE_READS)
    if allowed == ["escalate"]:
        assert cert.insufficient and "text of the notice" in cert.insufficient


def test_surge_notice_content_is_the_judges_reading_and_code_fixes_the_consequence():
    case = load("DISP-003")
    case = case.model_copy(update={"surge": case.surge.model_copy(update=dict(
        rider_notified=True, notification_method="in_app", notification_text=NOTICE, notification_timestamp=case.trip.pickup_at - timedelta(seconds=60)))})
    cert = evaluate(case, build_fact_table(case))
    assert cert.amount == 4.50 and not cert.mechanical
    ok, why = check_ruling(cert, ruling(cited_policy=["SURGE-1"], element_findings=[reading("SURGE-1:notice", "met")]))
    assert ok, why
    ok, why = check_ruling(cert, ruling(ruling="refund_partial", amount=4.50, cited_policy=["SURGE-2"], element_findings=[reading("SURGE-1:notice", "not_met")]))
    assert ok, why
    ok, why = check_ruling(cert, ruling(ruling="refund_partial", amount=4.50, cited_policy=["SURGE-2"], element_findings=[reading("SURGE-1:notice", "met")]))
    assert not ok and any("means no_action" in w for w in why)
    ok, why = check_ruling(cert, ruling(cited_policy=["SURGE-1"], element_findings=[reading("SURGE-1:notice", "met", basis=())]))
    assert not ok and any("basis empty" in w for w in why)


@pytest.mark.parametrize("m1", [1.0, 0.8])
def test_surge_that_did_not_rise_refunds_nothing(m1):
    case = surge(trip_start_surge=m1)
    case = case.model_copy(update={"fare": case.fare.model_copy(update={"surge_multiplier": m1})})
    cert = evaluate(case, build_fact_table(case))
    assert cert.allowed == ["no_action", "escalate"]


def test_mixed_difference_refunds_only_the_surge_part():
    """SURGE-3: the trip also ran longer (surgeable subtotal 9.00 → 11.00); only (1.5 − 1.0) × 11.00 is surge."""
    case = load("DISP-003")
    case = case.model_copy(update={"fare_detail": case.fare_detail.model_copy(update={"surgeable_subtotal": 11.0}),
                                   "fare": case.fare.model_copy(update={"total": 19.5})})
    table = build_fact_table(case)
    diff = next(f for f in table.facts if f.value and "surge_part" in f.value)
    assert diff.value["difference"] == 7.5 and diff.value["surge_part"] == 5.5
    assert evaluate(case, table).amount == 5.5


# ---------------------------------------------------------------------------- TH-1 / TH-3

def test_code_confidence():
    case = load("DISP-003")
    cert = evaluate(case, build_fact_table(case))
    assert cert.mechanical and code_confidence(cert) == 1.0
    cert.mechanical = False
    assert code_confidence(cert) == 0.9
    cert.fraud_flag = True
    assert code_confidence(cert) == pytest.approx(0.873)


@pytest.mark.parametrize("amount,mechanical,fraud,ok", [
    (4.50, False, False, True),          # under $10: the system decides
    (25.0, False, False, True),          # $10–50: 90% ≥ 80%
    (50.0, True, False, True),
    (50.01, True, False, False),         # above $50: a person decides
    (4.50, True, True, True),            # fraud flag, code-settled: 97% ≥ 95%
    (4.50, False, True, False),          # fraud flag, judge reading: 87% < 95%
])
def test_threshold_check(amount, mechanical, fraud, ok):
    case = load("DISP-003")
    cert = evaluate(case, build_fact_table(case))
    cert.mechanical, cert.fraud_flag = mechanical, fraud
    got, why = threshold_check(cert, amount)
    assert got is ok, why


def test_goodwill_counts_toward_the_amount_band():
    case = _driver_never_came(contact=False)
    cert = evaluate(case, build_fact_table(case))
    ok, why = threshold_check(cert, 46.0)                     # 46 + 5 goodwill > 50
    assert not ok and "$51.00" in why


# ---------------------------------------------------------------------------- citation scope and notices

def test_citations_are_scoped_to_what_decides_the_case():
    r = ruling(cited_policy=["NS-0", "NS-1", "RD-6", "SAFE-1", "TH-3", "PREC-1", "SURGE-2"])
    out, pruned = scope_citations(r, "no_show")
    assert out.cited_policy == ["NS-0", "NS-1"] and set(pruned) == {"RD-6", "SAFE-1", "TH-3", "PREC-1", "SURGE-2"}
    out, _ = scope_citations(r.model_copy(update={"safety_concern": "suspected"}), "no_show")
    assert "SAFE-1" in out.cited_policy
    out, _ = scope_citations(ruling(cited_policy=["FARE-0", "SURGE-2", "RD-2"]), "fare_dispute")
    assert out.cited_policy == ["FARE-0", "SURGE-2"]


def test_refunds_go_back_to_the_original_payment_method_and_goodwill_may_be_named():
    r = ruling(ruling="refund_full", amount=5.00, goodwill_credit=5.0)
    rider, driver = fallback_notices(r)
    assert "original payment method" in rider and "voucher" not in rider.lower() and "goodwill credit" in rider
    assert consistent("We refund $5.00 and add a $5.00 goodwill credit.", ruling(ruling="refund_full", amount=4.0, goodwill_credit=5.0))
    assert not consistent("We refund $9.00.", ruling(ruling="refund_full", amount=4.0, goodwill_credit=5.0))
