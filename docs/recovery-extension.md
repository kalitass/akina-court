# Recovered-evidence review extension (draft)

## Purpose and boundaries

A missing-GPS dispute can request the relevant interval from a synthetic record service, validate it with the existing evidence validator, rebuild facts, and prepare a source-linked reviewer handoff. Available evidence can be submitted to two separate hearings (initial and recovered snapshots) using the unchanged court. Unavailable or conflicting evidence produces an investigation task, not a fabricated ruling. All actions remain simulated.

The implementation lives in `recovery/`. `core/`, policy, rates, benchmark cases, stored court runs, and benchmark results are unchanged from main at `11a3669`. The API and evidence page add an opt-in extension; this still needs team review before main-flow use. Moving the extension outside the court fingerprint is not evidence of model correctness or a substitute for the team's ruling-logic gate.

Recovery hearings are disabled unless both `LIVE_RUNS` is enabled and `RECOVERY_REVIEW_ENABLED=1`. Existing access-token and concurrency controls apply. Use the team's DeepSeek configuration with `deepseek-chat` for all roles. Do not commit keys. Saved reviews go under ignored `review_runs/`; they never overwrite benchmark records. A matching saved initial hearing can be reused only after snapshot, receipt and hearing-context checks, including an independent extension code hash.

## Validation on 2026-10-11

- Full local suite after integration and admission checks: 747 passed, 1 skipped.
- Judge-facing wording check and diff whitespace check: clean.
- Browser: available GPS accepted and policy-condition changes shown; conflicting GPS retained the original file and produced a human investigation handoff. Live hearing control is disabled by default.
- Subsequent funded pilot: see `docs/recovery-pilot-2026-10-11.md`. Twelve hearings completed; the multi-agent arm had a reference mismatch with an invented rider-message time. No overall accuracy or automation improvement is claimed; keep disabled pending review.
- The 10 recovery scenarios are draft derivatives of existing synthetic fixtures, not an independently held-out benchmark. Their references require review.
- The evidence validator now lives in `app/evidence.py`, matching merged main. Core fingerprint is restored to `aff787edf0b9b629`. Some older single-judge records still carry a previous fingerprint; this extension does not repair or regenerate those records.

## Reproduce and evaluate

```sh
python -m pytest tests/ -q
python scripts/check_wording.py
python scripts/evaluate_recovery.py
# With configured, funded team credentials, run paired arms for each reviewed scenario:
python scripts/evaluate_recovery.py --live --case R-001 --arm judge_only
python scripts/evaluate_recovery.py --live --case R-001 --arm court
python scripts/report_recovery.py
```

Check manifest IDs before running. Preparation calls no model. Report matching requires the same input, policy, code and model context; failed runs and retrieval handoffs are separated from completed court accuracy. Measure exact decision accuracy, correct automatic clearance, and the court-versus-single-judge gap. Report denominators and failures, not just successful examples.

Before enabling this in the main workflow: review reference answers, run the required funded experiments, meet the team's complete benchmark/regenerated-data requirement for ruling changes, inspect both notices and before/after outcomes, and obtain teammate approval. A path-based CI skip does not satisfy these acceptance conditions.

## Recovery admission check

After GPS acceptance, route disputes with any untimed rider message are conservatively handed to a human before model calls. This is an extension admission rule, not a policy ruling or a correction to the core court. It retains the validated GPS snapshot, message indices, original untimed chat and source-linked investigation task. Driver timestamps are never substituted for rider timestamps. Cases with complete rider timestamps still follow the existing independent hearings.

R-009's preparation expectation now reflects this handoff. Its draft monetary reference is unchanged and still needs team review. A handoff is not an automatic model success; the original pilot's unsupported timestamp remains documented. This check deliberately may hand off cases a human could resolve, and does not prove overall accuracy improvement. The extension remains disabled by default; the core temporal-verification weakness and R-003 conservative escalation are not solved by this PR.

## Post-integration verification (2026-10-11)

- Synced main `11a3669`; no diff in core, policy, rates or baseline prompt.
- Generator workflow completed; 747 passed and 1 skipped (748 collected). Generated pages are current.
- All 10 draft recovery scenarios prepared successfully with no model calls.
- Funded R-001 court rerun: initial hearing escalated; recovered hearing recommended refund_full SGD 6.61, flag_account true with human-only account review. Strict draft reference matched; simulated auto clearance true.
- R-009 rerun: validated GPS retained; missing rider timestamp at chat index 1 handed off before any model call. Classified as retrieval handoff, never as model accuracy or correct automatic clearance.
- Requested model deepseek-chat for all roles; returned deepseek-flash. This small rerun does not establish overall improvement.
- Normal PR gate: trace clean; gated-path rerun skipped. Forced gate: completeness, pages and score floor pass; 67 pre-existing single-judge receipt mismatches remain. Therefore the forced gate is not fully passing. Main core files are byte-identical; no attempt was made to rewrite old receipts or charge for a full baseline rerun.
- Integration is suitable for teammate review with the extension disabled by default. This is not clearance to enable production automatic reviews.

Local post-integration experiment bundles: `32409aa8a9534af095613b54b8d8d93b.json` (R-001) and `a536a218937e4e8c918b94a4cc33fa2a.json` (R-009), stored under ignored review_runs. Historical pilot results remain unchanged.
