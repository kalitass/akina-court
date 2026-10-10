"""Notice and action contracts used by the actual court workflow.

These tests exercise the production functions called by run_case. They do not
make a model call; a separate live run is required before replacing a stored
demonstration record.
"""
from __future__ import annotations

import pytest

from core.orchestrate import _build_actions, _sanitize_notices
from core.schemas import Ruling


def ruling(**changes):
    values = dict(ruling="no_action", amount=None, recommended_action="no action",
                  confidence=0.9, reasoning="test", cited_facts=["F1"], cited_policy=["NS-1"],
                  flag_account=False, escalate=False)
    values.update(changes)
    return Ruling(**values)


@pytest.mark.parametrize("invented", [
    "The $5 was paid to you as a voucher.",
    "We transferred $5 to your wallet.",
    "Your account was suspended after this case.",
    "Your balance increased by $5.",
])
def test_no_action_never_passes_model_claims_to_outward_notice(invented):
    result = _sanitize_notices({"rider": invented, "driver": invented}, ruling())
    assert invented not in result.values()
    assert all("recorded charge" in text for text in result.values())
    assert all("has not changed any payment" in text for text in result.values())


def test_no_action_with_account_flag_keeps_separate_human_review():
    result = _sanitize_notices({}, ruling(flag_account=True))
    assert all("account review is recommended for a person" in text for text in result.values())
    assert all("no account action has been taken automatically" in text for text in result.values())


def test_no_action_without_account_flag_omits_review():
    result = _sanitize_notices({"rider": "Your account is under review."}, ruling())
    assert all("account review" not in text for text in result.values())


def test_escalation_never_promises_a_refund():
    result = _sanitize_notices({"rider": "You will receive $10 tomorrow."},
                               ruling(ruling="escalate", amount=10, escalate=True))
    assert all("human review" in text for text in result.values())
    assert all("$10" not in text for text in result.values())


def test_refund_is_recommendation_and_not_execution():
    result = _sanitize_notices({"rider": "We paid you $5."},
                               ruling(ruling="refund_partial", amount=5))
    assert all("recommends a $5.00 Ryde voucher refund" in text for text in result.values())
    assert all("has not issued a voucher" in text for text in result.values())


def test_clean_model_draft_still_uses_verified_notice():
    result = _sanitize_notices({"rider": "The charge stands."}, ruling())
    assert "has not changed any payment" in result["rider"]
    assert "has not changed any payment" in result["driver"]


def test_fee_waiver_uses_verified_amount():
    result = _sanitize_notices({"rider": "Your $99 fee was waived."},
                               ruling(ruling="fee_waived", amount=6.61))
    assert "$6.61" in result["rider"]
    assert "$99" not in result["rider"]


def test_action_builder_keeps_no_action_without_money_transfer():
    assert _build_actions(ruling()) == [{"type": "no_action", "mode": "auto",
                                          "detail": "charges stand; no refund recommended"}]


def test_action_builder_keeps_account_review_human():
    actions = _build_actions(ruling(flag_account=True))
    assert [action["type"] for action in actions] == ["no_action", "flag_account"]
    assert actions[1]["mode"] == "human_review"


def test_action_builder_does_not_create_refund_without_amount():
    assert _build_actions(ruling(ruling="refund_partial")) == []


def test_action_builder_routes_escalation_to_human():
    assert _build_actions(ruling(ruling="escalate", escalate=True)) == [
        {"type": "escalate", "mode": "human_review", "detail": "human review"}]


def test_action_builder_keeps_refund_before_account_review():
    actions = _build_actions(ruling(ruling="refund_partial", amount=5, flag_account=True))
    assert [action["type"] for action in actions] == ["refund_partial", "flag_account"]
    assert actions[0]["mode"] == "auto"
