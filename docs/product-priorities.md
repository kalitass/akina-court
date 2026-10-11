# Product priorities after the recovery experiment

Updated: 2026-10-11. This is a development plan, not a statement of delivered
features or production impact. Existing results use synthetic cases.

## Delivery checklist reconciled with the Feishu discussion

Read from the AkinaCourt desktop client and subsequently verified through the
bot history API on 2026-10-11 after the group-message permission was enabled.
The latest retrieved message is at 16:02; no newer development direction was found.
These are proposed tasks/owners, not assignments accepted
by teammates. No group message or shared document was edited.

Ouyang said he would inspect the reviewer page after Shirley said she was working
on recovery rather than that page. Our new recovery handoff UI should therefore
be offered as a component for that work, not developed as a competing workspace.
Fetching origin confirmed main is still `b465fa8` (PR #6 merged). PR #7 and the
additional local changes must not be described as deployed.

| Priority | Task | Proposed responsibility | Done when |
| --- | --- | --- | --- |
| P0 | Agree reviewer UI / recovery ownership and integration interface | Shirley + Ouyang + Kit | One agreed page owner; packet fields, queue linkage and branch scope recorded |
| P0 | Review and split the local changes for delivery | Shirley/Codex, reviewed by Kit | Default recovery/packet changes separated from opt-in local model experiments; no old generated benchmark pages carried over; PR against current main |
| P0 | Connect accepted or blocked evidence packets to the existing human workflow | Shirley/Codex backend, reviewer page owner for UI | Reviewer sees source, interval, facts, outstanding questions and failed recovery task; original record retained |
| P0 | Validate the recovery court with the team's working provider | Model runner to agree with Kit | Available/unavailable/conflict cases tested; identical provider for judge/court comparison; failures, strict match, correct automation, wrong automation, latency and cost saved separately |
| P0 | Complete the two-dispute end-to-end demo | Whole team | No-show and route case run from complaint to explanation; agent exchanges visible; recovery failure path shown without promising a decision |
| P0 | Audit presentation claims, tool evidence and submission fields | Shirley + team | English claims match saved results; CodeBuddy/WorkBuddy evidence retained; final form requirements and deadline checked against primary materials |
| P1 | Reuse a verified original hearing when reopening | Shirley/Codex | Input and policy fingerprints match; only updated evidence hearing reruns; stale reuse rejected |
| P1 | Finish human decision/appeal record | Backend + reviewer page owner | Human reason and identity saved; original ruling preserved; authorised override and duplicate handling tested; notices consistent |
| P2 | Count preventable evidence/consent gaps from records | After core demo freeze | Counts resolve to source records; synthetic/real and suspected/confirmed labels separate |

The earlier bot summary says 14 October; the later background/resource summary
says 16 October at 23:59 GMT+8. Neither is a newly verified primary-source
deadline in this read. Target **14 October for internal feature freeze**, subject
to team agreement, and confirm the actual submission cutoff in the handbook
and submission form. Do not add optional ADP/TRTC/Miora integration merely to
use every resource. Current local code verification is **715 passed, 1 skipped**;
this is not a fresh model benchmark or a production acceptance result.

## What we should optimise for

A dispute should end in either a supported decision or a useful human task.
More agents, more retries, and more pages are not success measures. Track
correct automatic decisions, incorrect automatic decisions, reviewer workload,
response latency, model cost, and whether both parties can understand the basis.

The recovery demonstration already validates a synthetic GPS interval and
rebuilds the facts. The local 4B model has repeatedly failed to complete the
paired court reliably; its structured fields can contradict its explanation.
Do not spend repeated experiments merely stretching timeouts on this model.
Local inference is useful for interface and integration checks. It has not
demonstrated a performance gain or replaced the team's model evaluation.

## Priority 1 — Make missing-evidence escalation useful

**User:** a support reviewer who would otherwise assemble GPS, chat, policy and
the cause of escalation manually.

**Delivered locally:** a source-linked reviewer packet in the recovery preview
and review bundle. It includes the two fact tables, snapshot fingerprints,
changed/newly assessable case conditions, open interpretation questions and
an actionable investigation task. It can be downloaded without model calls.
It is not connected to the team's live support queue or a real trip-record API.

**Delivered locally next:** a read-only case-linked integration endpoint,
`/api/queue/{case_id}/evidence-handoffs`, exposes internally checked server-saved
packets to the existing queue's page owner. Model-failure status remains distinct
from successful evidence validation; blocked recovery keeps its investigation
task. No queue row is created, resolved or overwritten by reading this endpoint.

**Next:** the reviewer page owner joins these packets to the existing queue by
source case ID. Reuse `core/stretch/sla.py` and the existing feedback endpoint
instead of creating a second queue. A reviewer must be able to see what is known,
what remains unresolved and which evidence supports each item. Keep the
original record and the new snapshot separate. Decide access control and
storage retention before introducing real customer records.

**Acceptance:** no rejected evidence enters the current fact table; all
references resolve in the right snapshot; an outage still leaves a readable
handoff; reviewing a synthetic packet never moves money or changes an account.
Compare manual case assembly with packet-assisted review on the same fixtures.
Measure time and omitted facts with team members; do not invent a saving figure.

## Priority 2 — Reopen a case economically when new evidence arrives

**Pain:** the current experimental comparison runs two fresh hearings. An actual
previously adjudicated case should not need its original hearing paid for again.

**Next:** accept an existing initial hearing only after matching its case,
policy and input fingerprint. Run one independent hearing on the validated new
snapshot, not a continuation conditioned on the previous outcome. Reject stale
or mismatched initial records. Keep the two-hearing mode for controlled tests.
Never repair a missing model amount by extracting a number from its prose.

**Acceptance:** matching original records avoid an extra hearing; changed policy
or inputs reject reuse; failure preserves the original decision and a diagnostic
record; the UI distinguishes a proposed new decision from an executed action.
Count actual calls, tokens and latency. Fewer hearings alone does not establish
a particular percentage cost saving.

**Quality gate:** test baseline/candidate with the team's benchmark provider,
same frozen cases and reference definitions, plus a separately labelled recovery
set. Keep strict match, automatic-and-correct, wrong-automatic, and judge/court
gap separate. Local timeout failures have no accuracy score.

## Priority 3 — Finish the reviewer feedback loop

**Existing components:** human queue routing, override recording and precedent
indexing already exist under `core/stretch/`. They are foundations, not proof
that a reviewer-facing resolution workflow is complete.

**Next:** one review workspace that displays evidence, receives a human decision
and reason, and records who changed what. Link a reviewer correction to the
original evidence receipt. Show the result to both parties with consistent
amount/action fields. Corrections become labelled evaluation examples; do not
automatically rewrite policy or train on unreviewed model outputs.

**Acceptance:** correcting a case preserves its original audit record; duplicate
submission cannot apply twice; unauthorised overrides are rejected; the queue
item resolves only after a recorded human decision. Safety and account sanctions
remain human responsibilities. All execution is simulated until a real adapter
and its operational controls are agreed.

## Priority 4 — Identify preventable causes, without profiling people

**User:** an operations manager deciding what to fix in the product.

**Next:** aggregate observed handoff reasons and confirmed evidence gaps: missing
GPS, ambiguous stop consent, incomplete arrival confirmation, model outage.
Keep suspected and human-confirmed causes distinct. Reuse stored events; do not
infer a driver's dishonesty from identity/history alone or count a synthetic
scenario as a real incident. This can inform better arrival UX or telemetry.

**Acceptance:** every count links to an underlying record; unknown reasons stay
unknown; simulated and real data are separated; any claimed business benefit
requires real operational measurements. Prioritise this after the reviewer
workflow is usable, not as another decorative dashboard.

## Stop rules and presentation

- Further local-model experiments require a concrete hypothesis and a bounded
  test. No open-ended retries to make one showcase succeed.
- New agent/policy/case changes require fresh model comparison before publishing
  improved performance. Packet/UI changes do not justify rerunning paid models.
- Do not change the published 65-case figures using two recovery snapshots.
- Demo story: evidence missing → bounded retrieval → source validation → conditions
  clarified → unresolved questions presented → court or human review → audit trail.
  Show available, unavailable and conflicting evidence, rather than only a happy path.
- Describe the distinctive capability as evidence-aware resolution and useful
  escalation. The adversarial court remains the component whose value is supported
  by the team's separately recorded comparisons. No production savings claimed yet.
