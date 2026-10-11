# Human review workflow integration

## What this adds

The team's `review-question-card` branch (80e722f) is integrated on this development branch, preserving its authors' commits. Operations links for escalated cases now open the team's `/review.html` page and `/api/review` API. Automatically cleared cases keep their replay link, without a misleading human-review entry. The independent recovery demonstration below remains a separate evidence ledger; navigation is connected, but decisions are not silently copied between the two stores.

Open `/review.html?case=B-0054` for the team's real unresolved route interpretation. Open `/reviewer-workflow.html?case=C-0004&scenario=missing_gps` for the synthetic evidence-retrieval demonstration, linked from the team's review page. The recovery API's before/after comparison is computed from both snapshots and includes the saved human assessment separately; it never labels that assessment as a new AI verdict.

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

Synced main `ee6e04d`, preserving the voice intake and fraud demonstration additions. Core, policy, rates, case data and stored run files match main. Nineteen reviewer tests cover source mismatch, calculated amounts, missing/safety evidence, idempotency, stale revisions, rejected/tampered GPS, token enforcement, before/after source consistency, end-to-end API persistence, every reviewable case on the integrated team's queue, and a confirmed evidence request keeping its case open. Complete generator/test results are reported with the PR.

The browser demonstration completed: C-0004 missing GPS → request evidence → validated GPS retained → preview full refund SGD 6.61 with human-only account review → save human assessment → reload with both actions and accepted GPS intact. This verifies a synthetic operational workflow, not an improvement to model accuracy or real support handling time.

## 90-second demonstration

1. On `/review.html?case=B-0054`, show the actual remaining question and verbatim evidence. Explain: "The court does not guess which road the driver used. A reviewer sees the precise unresolved issue."
2. Open the linked GPS recovery demonstration. Read the **Before** column: zero GPS samples; only escalation is permitted. Explain: "A missing record is not evidence against either party."
3. On a fresh demonstration ledger, choose Request more evidence, GPS interval, Available, enter a reviewer and reason, then save. On an already completed ledger, show the saved request and validation history rather than pretending to submit a new one.
4. Read the **After** column: 114 GPS samples for C-0004; the closest approach and stationary distance come from the unchanged facts code. Explain: "We retrieved synthetic recorded telemetry, validated its source and coverage, and recomputed the facts. We did not ask a model to invent GPS."
5. Preview and save a human full-refund assessment with its reason (or inspect the existing saved assessment). Show the calculated SGD 6.61 and reload to demonstrate persistence. Explain: "This is a traceable simulated human decision. No payment occurs. AI rehearing is a separate experiment."

Do not say this experiment proves increased model accuracy, lower support costs, or production-ready recovery. Queue feedback and recovery-ledger evidence are currently separate; production source integration, staff authentication and an explicitly reviewed bridge between those stores remain necessary.

## Formal reviewer page: same-case evidence continuation

Open `/review.html?case=C-0004&scenario=missing_gps`. This explicitly synthetic
intake now uses the **formal** reviewer page, request API, decision API and SLA
store throughout, rather than the independent SQLite demonstration ledger.

1. GPS is removed from a copy of C-0004; the original case and stored AI verdict
   are not loaded into this assessment. Fee decisions have no selectable finding.
2. Request the platform GPS interval, confirm the source review and submit.
   The formal request and an open SLA item are saved.
3. Receive a simulated available, unavailable or conflicting response on this
   same page. The existing GPS validator checks trip/request linkage, source,
   ordering, timezone, interval coverage and the 30-second completeness limit.
4. Only accepted telemetry is persisted as a new case snapshot. Reloading shows
   the same case with refreshed facts and map. Failed retrieval stays awaiting
   the original request; it can be retried. A stale request cannot supply evidence.
5. The human reviews the original complaint/messages and recovered GPS, records
   a finding, reason and fact citations. The unchanged policy calculates $6.61;
   any account referral needs a second confirmation. Only that final human
   decision resolves the demonstration SLA item.

Scope: C-0004 complete GPS absence only; no new AI hearing or actual payment.
The scenario's formal request, recovery, decision, precedent and SLA records
share `runs/review_recovery_demo/C-0004/`, isolated from the benchmark queue and
its original precedents. This is not a production GPS integration, road-name
recovery for B-0054, a multi-worker transaction system, or evidence of improved
model accuracy. A fixture change invalidates previously accepted telemetry.

Verification: `tests/test_formal_review_recovery.py` exercises the whole HTTP
cycle, blocked pre-evidence decisions, unavailable/conflicting retries, token
checks, stale request rejection, scope rejection, fixture invalidation, final
queue resolution and byte preservation of cases/archived benchmark runs.
