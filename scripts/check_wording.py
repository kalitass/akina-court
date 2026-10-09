#!/usr/bin/env python3
"""Release wording check: fail if judge-facing docs still carry superseded numbers or claims.

    .venv/bin/python scripts/check_wording.py        # exit 1 and list offenders if any stale term is found

Terms that must not appear in judge-facing text (retired wording, overclaims). Add to STALE whenever a
number or framing is replaced, so the next regeneration cannot quietly resurrect it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["web/index.html", "web/i18n.zh.js", "web/ops.html", "web/policy.html", "web/replay.html", "web/receipt.html", "web/submission.json",
         "README.md", "web/report.html"]
STALE = [
    (r"法庭 \*\*95\.9|court 95\.9|95\.9 / 95\.9|\*\*95\.9%\*\*", "pre-rerun court accuracy"),
    (r"0\s*/\s*412", "pre-rerun citation count"),
    (r"\b343\b", "run count before the judge_only arm (392 case-system runs now)"),
    (r"100% accurate|100% correct", "say 'matched the policy-derived reference 49/49', not accurate/correct"),
    (r"三臂", "there are four arms now (raw, facts_only, judge_only, court)"),
    (r"人工标准答案|human-labell?ed (reference|answers|truth)|hand-labelled (reference|answers|truth)", "reference answers are policy-derived, not human-labelled"),
    (r"解决(最后一个|了最后)?解释性|settle the last interpretive|interpretive tail", "judge_only's miss was an amount error, not an interpretive one"),
    (r"25 sourced clauses|25 条", "policy has 21 sourced clauses (17 citable + 4 informational)"),
    (r"独立贡献|independent contribution", "+32.7 pp is a raw-30s vs code-facts-from-5s comparison"),
    (r"闸门让系统安全|gate makes the system safe", "retired framing: facts_only + gate still leaks"),
    (r"S\$0\.10", "price claim without a dated calculation"),
    (r"Independent review", "say 'adversarial model review'"),
    (r"paid automatically|executed automatically|auto-executed", "wallet is simulated: say 'cleared for automatic voucher issuance' / 'auto-cleared'"),
    (r"real Singapore routes|real routes", "say 'synthetic trips on real OneMap road geometry'"),
    (r"nothing is a mock-up", "case data and wallet/trust integrations are simulated; say so"),
    (r"TokenHub", "TokenHub was never used; judge-facing text names the DeepSeek API only"),
    (r"\b392 LLM runs|[Tt]hree-arm", "392 case-system runs / 1,191 model calls; four arms"),
]


def main() -> int:
    bad = 0
    for rel in FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if any(tok in line for tok in ("check_wording", "旧文", "retired", "不说", "不要说", "不是纯粹", "不能说", "never say", "do not say")):
                continue   # lines that quote a stale term on purpose, to forbid it
            for pat, why in STALE:
                if re.search(pat, line):
                    bad += 1
                    print(f"{rel}:{i}: /{pat}/ — {why}\n    {line.strip()[:140]}")
    print("wording check:", "clean" if not bad else f"{bad} stale mention(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
