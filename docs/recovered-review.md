# Recovered evidence court review (development)

This is stacked on the isolated recovery preview in PR #6. It adds an opt-in two-hearing review without changing existing agents, prompts, policy rules, case files, or benchmark records.

## Flow

1. Copy the initial case, identify the GPS gap and request the synthetic records.
2. Validate those records. Unavailable/conflicting records end in a specific human task without model calls.
3. Run the existing full court on the initial missing-GPS snapshot.
4. Run an independent full court on the validated new snapshot. Previous briefs/rulings are not put into the second prompt.
5. Compare ruling, amount, escalation, account flag and evidence status. Show each hearing's own reasoning, notices and eligibility; fact IDs belong to their respective hearing, not to a shared cross-version namespace.
6. Save one separate bundle in ignored `review_runs/`: both snapshots, both complete hearing records, evidence hashes/source, changed fields and failure state. A new unique ID prevents overwriting existing runs. Publish atomically, never overwrite an existing bundle.

The two hearings have unique `~recovery-` case IDs. They do not overwrite stored demos and do not write after-ruling precedent/SLA history. The web service retains its existing stretch configuration for fact enrichment; the standalone experiment runner disables all stretch flags for reproducible bare-court evaluation.

## Run

The page `/evidence.html` has a separate live-review button and optional demo access token. Availability requires live runs enabled and a configured provider key. `POST /api/runs/C-0004` with JSON `{"recovery":"available"}` starts a review; `GET /api/recovery-reviews/<returned run_id>` provides completion status and the bundle. Existing token, concurrent run and per-client budget checks apply. Each accepted evidence review uses two full court hearings, so its model cost is higher than one ordinary run. No real refund/account action is executed; the displayed eligibility is the existing simulation.

For a local experiment, configure the existing provider credentials in the environment and run:

```
python scripts/review_recovery.py --case C-0004 --mode available
```

Supported cases are C-0001 and C-0004. Modes are available/unavailable/conflict. Results go to a separate directory; original case data and benchmark outputs remain unchanged. The fixed 30-second recovery completeness constraint remains a demo assumption.

## Validation and performance limits

Offline tests use an explicitly fake runner to test orchestration, snapshot integrity, comparisons, failure handling, persistence and API guards. These tests are **not model-quality evidence**. A default unscreened/unavailable judge, missing ruling, wrong case identity or mutated input causes review failure; partial completion is never shown as two successful hearings.

The original 65-case no-op tests remain in place. A fresh-model benchmark still requires credentials. Before claiming improved accuracy or automation, run the frozen original benchmark for regression and a separate evidence-gap set for improvement, under equal model/tool access for judge-only and full court. Compare strict match, automatic-and-correct rate and the judge/court gap; do not count handoffs as automatic success. Existing benchmark metrics are not replaced by this implementation.
