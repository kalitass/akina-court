# Human review workflow integration

## What this adds

The operations table now links to a functional reviewer workspace. It combines the original complaint, trip replay, computed facts, unresolved policy questions and actual stored advocate readings. A reviewer can confirm a verified stored recommendation, record a reasoned assessment, or request further evidence. This is the data/action integration for a final reviewer design, not a replacement for that design.

Open `/reviewer-workflow.html?case=B-0054` to inspect a real unresolved route interpretation. Open `/reviewer-workflow.html?case=C-0004&scenario=missing_gps` for the synthetic evidence-retrieval demonstration.

## Frontend contract

All endpoints honour the existing `X-Demo-Token` setting. The `scenario` query is `stored` (default) or `missing_gps` (C-0001/C-0004 only).

| Endpoint | Purpose |
| --- | --- |
| `GET /api/reviewer/{case_id}` | Source-linked workspace, current revision and saved history |
| `POST /api/reviewer/{case_id}/preview` | Calculate the conditional human outcome; no write |
| `POST /api/reviewer/{case_id}/actions` | Persist an assessment or investigation request |

The POST body carries a UUID `request_id`, the GET response's `source_fingerprint` and `revision`, `action` (`accept_ai`, `own_decision`, `request_evidence`), `reviewer` and a meaningful `reason`. Own decisions also use `outcome` and `choices`: every open segment maps to `exempt`, `counts` or `undetermined`. The server calculates amounts using the existing policy code. Evidence requests use `evidence_kind` (`gps`, `chat`, `other`) and a synthetic `response_mode` (`available`, `unavailable`, `conflict`).

Reload after a successful write. Retrying the same UUID and body returns the saved action; reusing it for another action is rejected. A stale revision or changed source is HTTP 409, invalid policy decisions are HTTP 400, invalid body fields are HTTP 422. The UI must retain unresolved choices and display a conflict rather than silently overwriting another reviewer.

## Evidence and decision safeguards

- Branches are conditional human policy assessments, not generated AI conclusions. Actual party claims are included only when their stored fact table matches the current case.
- Confirmation is disabled for unresolved/escalated recommendations and unverified receipts. Safety and missing evidence cannot be settled into a monetary outcome in this demonstration.
- Available synthetic GPS is validated by the existing recovery provider/validator. Rejected records never replace missing evidence. Accepted snapshots survive reload and are checked against their source hashes.
- Before GPS acceptance, the missing-GPS page hides the original full fixture map. After acceptance, the embedded replay is labelled as the original stored fixture, separate from the current reviewer decision.
- Human actions live in ignored `reviewer_runs/actions.sqlite`. They do not mutate `runs/`, benchmark results, case files, the original SLA queue, payments or account state. Reviewer identity is self-declared: authenticated staff permissions and actual SLA closure are future integration work.
- No model is called by these three endpoints. The separate opt-in recovery experiment remains responsible for paired AI rehearings; this UI does not claim a new AI verdict after retrieval.

## Verification on 2026-10-12

Synced main `ee6e04d`, preserving the voice intake and fraud demonstration additions. Core, policy, rates, case data and stored run files match main. The generator workflow completed with **772 passed, 1 skipped**. Seventeen reviewer tests cover source mismatch, calculated amounts, missing/safety evidence, idempotency, stale revisions, rejected/tampered GPS, token enforcement and end-to-end API persistence.

The browser demonstration completed: C-0004 missing GPS → request evidence → validated GPS retained → preview full refund SGD 6.61 with human-only account review → save human assessment → reload with both actions and accepted GPS intact. This verifies a synthetic operational workflow, not an improvement to model accuracy or real support handling time.
