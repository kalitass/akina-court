# Recovered-evidence review extension (draft)

## Purpose and boundaries

A missing-GPS dispute can request the relevant interval from a synthetic record service, validate it with the existing evidence validator, rebuild facts, and prepare a source-linked reviewer handoff. Available evidence can be submitted to two separate hearings (initial and recovered snapshots) using the unchanged court. Unavailable or conflicting evidence produces an investigation task, not a fabricated ruling. All actions remain simulated.

The implementation lives in `recovery/`. `core/`, policy, rates, benchmark cases, stored court runs, and benchmark results are unchanged from main at `665fb38`. The API and evidence page add an opt-in extension; this still needs team review before main-flow use. Moving the extension outside the court fingerprint is not evidence of model correctness or a substitute for the team's ruling-logic gate.

Recovery hearings are disabled unless both `LIVE_RUNS` is enabled and `RECOVERY_REVIEW_ENABLED=1`. Existing access-token and concurrency controls apply. Use the team's DeepSeek configuration with `deepseek-chat` for all roles. Do not commit keys. Saved reviews go under ignored `review_runs/`; they never overwrite benchmark records. A matching saved initial hearing can be reused only after snapshot, receipt and hearing-context checks, including an independent extension code hash.

## Validation on 2026-10-11

- Full local suite: 745 passed, 1 skipped.
- Judge-facing wording check and diff whitespace check: clean.
- Browser: available GPS accepted and policy-condition changes shown; conflicting GPS retained the original file and produced a human investigation handoff. Live hearing control is disabled by default.
- Subsequent funded pilot: see `docs/recovery-pilot-2026-10-11.md`. Twelve hearings completed; the multi-agent arm had a reference mismatch with an invented rider-message time. No overall accuracy or automation improvement is claimed; keep disabled pending review.
- The 10 recovery scenarios are draft derivatives of existing synthetic fixtures, not an independently held-out benchmark. Their references require review.
- Existing main already has stored-run receipt/code fingerprint differences: current court code hash `ec8e76a6faaa53d7`, 15 stored demo receipts use `aff787edf0b9b629`. This extension does not repair or regenerate those records.

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
