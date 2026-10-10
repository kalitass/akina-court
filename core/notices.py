"""The two notices Ryde sends after a case. Code decides what they may promise; a model only phrases a ruled outcome.

An escalated case gets a fixed notice: no outcome, no amount, no voucher — only that a person will look, and at what.
A ruled case's model-written notice is checked against the final ruling (every dollar amount in the text must be the
ruling's amount; a no-refund ruling carries no amount at all); if it disagrees, a template takes its place.
"""
from __future__ import annotations

import re

from core.schemas import Ruling

AMOUNT_RE = re.compile(r"(?:S?\$|SGD)\s?(\d+(?:\.\d{1,2})?)", re.I)   # $3.99, S$3.99, SGD 3.99

PLAIN = {
    "refund_full": "the cancellation fee is refunded in full",
    "refund_partial": "part of the fare is refunded",
    "fee_waived": "the fee is waived",
    "no_action": "the charge stands",
}


def escalation_notices(case_id: str, ruling: Ruling, looks_at: list[str]) -> tuple[str, str]:
    """Fixed text for a case that goes to a person. It promises nothing and states no conclusion."""
    what = "; ".join(x for x in looks_at if x) or "the trip record and the messages exchanged"
    rider = (f"Your dispute on trip {case_id} has been passed to a Ryde reviewer. No decision has been made yet: nothing has been "
             f"refunded or charged as part of this review. The reviewer will look at {what}. Ryde will contact you once the review is complete.")
    driver = (f"The dispute on trip {case_id} has been passed to a Ryde reviewer. No decision has been made yet, and nothing changes on "
              f"your account or earnings as part of this review. The reviewer will look at {what}. Ryde will contact you once the review is complete.")
    return rider, driver


def consistent(text: str, ruling: Ruling, on_record: list[float] = ()) -> bool:
    """Every dollar amount in a notice must be the ruling's amount; a no-refund ruling may only name a charge that is on
    record (the cancellation fee or the total that stands); an escalated case allows none."""
    amounts = [float(a) for a in AMOUNT_RE.findall(text or "")]
    if ruling.escalate or ruling.ruling == "escalate":
        return not amounts and "voucher" not in (text or "").lower()
    if not ruling.amount:
        return all(any(abs(a - x) < 0.005 for x in on_record) for a in amounts)
    return all(abs(a - ruling.amount) < 0.005 for a in amounts)


def fallback_notices(ruling: Ruling) -> tuple[str, str]:
    """Template notices for a ruled case, built from the structured ruling only."""
    outcome = PLAIN.get(ruling.ruling, ruling.ruling)
    money = f" You will receive ${ruling.amount:.2f} as a Ryde voucher." if ruling.amount else ""
    money_d = f" A ${ruling.amount:.2f} Ryde voucher is issued to the rider." if ruling.amount else ""
    flag = " Your account has been referred for review." if ruling.flag_account else ""
    rider = f"We have reviewed your dispute: {outcome}.{money} The decision follows Ryde's dispute policy and the trip record."
    driver = f"We have reviewed the dispute on this trip: {outcome}.{money_d}{flag} The decision follows Ryde's dispute policy and the trip record."
    return rider, driver
