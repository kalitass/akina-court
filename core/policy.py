"""policy/policy.md as data: full text for prompts, clause ids + citability for verification."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / "policy" / "policy.md"
ACTIONS = ("refund_full", "refund_partial", "fee_waived", "no_action", "escalate")   # Ruling.ruling vocabulary
EXTRA_ACTIONS = ("flag_account",)                                                   # recommended_action add-ons


@lru_cache
def policy_text() -> str:
    return POLICY_PATH.read_text(encoding="utf-8")


@lru_cache
def policy_clauses() -> dict[str, bool]:
    """{clause_id: citable}. A clause line starts with **ID**; '不可引用' on that line = informational only."""
    out: dict[str, bool] = {}
    for line in policy_text().splitlines():
        m = re.match(r"\*\*([A-Z]+-\d+)\*\*", line)
        if m:
            out[m.group(1)] = "不可引用" not in line
    return out


def citable_ids() -> set[str]:
    return {k for k, v in policy_clauses().items() if v}


CITE_RE = re.compile(r"\[([A-Z]+-\d+|F\d+)\]")


def cited_in(text: str) -> tuple[set[str], set[str]]:
    """(fact ids, clause ids) written as [F3] / [RD-2] inside free text."""
    ids = set(CITE_RE.findall(text or ""))
    facts = {i for i in ids if re.fullmatch(r"F\d+", i)}
    return facts, ids - facts
