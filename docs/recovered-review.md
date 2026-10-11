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

### Integration contract for the reviewer page

`GET /api/queue/C-0004/evidence-handoffs` (also C-0001) returns saved
server recovery packets by source case. Pass `X-Demo-Token` when the demo token
is configured. Join each queue row by `case_id`; each item has a unique
`review_id` and `run_id` for the existing recovery-status endpoint.

Display `review_state` separately from `evidence_state`: validated GPS can
remain useful even if an advocate timed out. Show `next_step`, `failure` and the
packet's source, investigation task and snapshot-labelled facts. Do not treat
`ready_for_court` as a ruling or `reviewed` as permission to close a queue item.
The endpoint never changes queue state, invokes models or applies an override.

Only flat `review_runs/<review_id>.json` server bundles are included. Nested CLI
experiment folders remain excluded. An empty list means no compatible saved
packet, not no outstanding work. `skipped_records` reports unreadable or
incompatible records without exposing their content. Source/snapshot hashes and
packet contents are checked against the current deterministic assessment;
incompatible older records stay on disk. These checks establish consistency,
not source authenticity. Items are ordered by ID, not recency; the page must not
label the last item as the latest review. Deployment still contains synthetic
data only and needs real access controls before handling customer records.

### Reviewer handoff without a model call

Supported recovery attempts now include `evidence.reviewer_packet` (the preview
API returns it under `report`). The packet contains both computed fact tables,
snapshot-local citations, requested interval, accepted source, fingerprints,
changed or newly assessable whole-case predicates, remaining interpretation
questions, and a specific investigation task when retrieval is blocked.
`/evidence.html` displays the summary and downloads its English plain text.

This works when the model is unavailable. It prepares evidence for a reviewer;
it does not submit an override, close a queue item, or produce a final ruling.
Before/current fact IDs must never be compared as if they identify the same
fact. Segment conditions are kept in their respective snapshot, not paired by
an F-id that may shift. A newly assessable condition is labelled "not assessed"
before recovery, rather than inventing a previous pass/fail value. No accepted
source or new GPS is shown for rejected/conflicting records.

Time saved for reviewers is a hypothesis to measure with people, not a result
of the offline tests. The provider remains synthetic and the 30-second record
completeness limit remains a demonstration assumption.

Offline tests use an explicitly fake runner to test orchestration, snapshot integrity, comparisons, failure handling, persistence and API guards. These tests are **not model-quality evidence**. A default unscreened/unavailable judge, missing ruling, wrong case identity or mutated input causes review failure; partial completion is never shown as two successful hearings.

The original 65-case no-op tests remain in place. A fresh-model benchmark still requires credentials. Before claiming improved accuracy or automation, run the frozen original benchmark for regression and a separate evidence-gap set for improvement, under equal model/tool access for judge-only and full court. Compare strict match, automatic-and-correct rate and the judge/court gap; do not count handoffs as automatic success. Existing benchmark metrics are not replaced by this implementation.

## Paired local effect experiment

The CLI now supports `--arm judge_only` and `--arm court`, with identical synthetic recovery access. Use separate output directories and the same provider/model settings. It scores the initial missing-GPS hearing against an escalation reference, and the recovered hearing against the unchanged `data/expected/<case>.json` reference. Each bundle includes strict match, automatic-and-correct, wrong-automatic, duration and model labels. Failure has no score. These two demo cases are a smoke test, not a replacement for the 65-case or held-out benchmark.

```
python scripts/review_recovery.py --case C-0004 --arm judge_only --out review_runs/experiment/judge_only
python scripts/review_recovery.py --case C-0004 --arm court --out review_runs/experiment/court
python scripts/review_recovery.py --case C-0001 --arm judge_only --out review_runs/experiment/judge_only
python scripts/review_recovery.py --case C-0001 --arm court --out review_runs/experiment/court
```

Use `--dry-run` to prepare snapshots without model calls; this produces no performance scores. Without a configured provider key, an available-record experiment exits with code 2 instead of producing a fake completed experiment. Unavailable/conflict modes require no model call and can be exercised locally without a key.
