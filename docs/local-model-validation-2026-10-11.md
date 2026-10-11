# Local model smoke test — 11 October 2026

## Environment

- Apple M5, 16 GB memory.
- Official Ollama 0.40.2, cloud disabled, loopback listener only.
- Model: `qwen3:4b-instruct-2507-q4_K_M`, Q4_K_M.
- Context: 16,384 tokens per worker. First tests used one worker.
- No paid API requests, no cloud key passed to the local backend.
- Synthetic fixture C-0004 only; this is not a replacement for the 65-case benchmark.

## Verified results

- A real local model returned the structured response `{status: READY}` through
  the project's Pydantic AI model interface.
- Offline regression suite: **694 passed, 1 skipped** (695 collected).
- Multilateral court, one worker: **review_failed** after 280.20 seconds,
  `Driver Advocate unavailable`. No completed paired hearings and no accuracy
  scores. The saved bundle is
  `review_runs/local-qwen3-2026-10-11/court/94fb0567cc0b4edfab7dbdb935e0de69.json`.
- Single judge, one worker: **reviewed**, two independent real hearings,
  152.06 seconds. The saved bundle is
  `review_runs/local-qwen3-2026-10-11/judge_only/837aed07aca243ba83e22ce26e15c16a.json`.
  - Before recovery: missing GPS, human review; matches the expected incomplete
    evidence outcome, but is not an automatic success.
  - After recovery: GPS is recognized as sufficient, but the model's structured
    refund/account fields conflict with the certificate. After correction, the
    refund has no executable positive amount. Verification routes to a person.
    The final core outcome does **not** match the reference full-refund result.
  - Correct automatic outcomes: 0/2; wrong automatic outcomes: 0/2. These two
    snapshots are not two independent benchmark scenarios.

The free local backend is functional. This smoke test does **not** establish
performance improvement or parity with the published DeepSeek benchmark.
Evidence validation is code-driven; the recovered GPS comes from a synthetic
provider, not a real Ryde integration.

## Concurrency investigation

A two-worker court retry is a separate resource configuration. An intermediate
diagnostic run was interrupted before completion and is excluded from scores.
The completed retry is recorded below. The original
court prompts, policy rules, validation checks, and stage timeouts are unchanged.

- Two-worker court retry: **review_failed**, 282.81 seconds,
  `Driver Advocate unavailable`. Live diagnostic events confirm the driver
  advocate exceeded the unchanged **120-second brief deadline**. The rider
  advocate produced a brief with two claims and no void claims, but the complete
  paired court review was not available. Accuracy scores remain null.
  Bundle: `review_runs/local-qwen3-2026-10-11/court-parallel2/562b5358ee754a0d954ab5c3ed5ea6b8.json`.

## Conclusion

Free local real-model execution is possible, and the single-judge recovery
workflow completed. This 4B model on this computer did not reliably complete
the full court within the current stage deadlines. Do not treat failure or
human referral as correct automatic adjudication. We have not run the 65-case
benchmark with this local model. Further full-court work needs a separately
recorded model/resource experiment or the team's existing benchmark provider.

## Opt-in batched retrieval experiment

The same local model and two-worker server were tested with `--batch-evidence`.
Each advocate uses one aggregate tool that calls all six original evidence
slice functions, retains their source events, and tracks the returned IDs.
This changes the retrieval condition; it is not the original benchmark arm.
No policy, citation checks, output validation, or stage deadlines were relaxed.

- Duration: **706.21 seconds**.
- State: **review_failed**, `Rebuttal skipped — rider; Rebuttal skipped — driver`.
- The first (missing-GPS) hearing completed: rider brief three claims with zero
  void claims, driver brief four claims with zero void claims; both rebuttals
  had three points. The final decision escalated. However, its reasoning
  contradicted that structured result by discussing a refund, and it put fact
  IDs in `cited_policy`. Verification blocked those invalid citations. A
  completed hearing here is not evidence of good reasoning or automatic success.
- The second (recovered-GPS) hearing failed at the rebuttal stage. The paired
  experiment therefore has **no accuracy scores**. The review bundle retains
  the first hearing and the failure message; it does not retain the failed
  second hearing's full events, a diagnostic limitation to address next.
- Bundle: `review_runs/local-qwen3-2026-10-11/court-batched/6dd3948b04ad4835a84472260ffe8b8e.json`.
- Regression verification after adding the experiment: **696 passed, 1 skipped**.

One trial cannot establish a reliable latency improvement. Batched retrieval
remains disabled by default and cannot be enabled by the experiment script for
cloud providers. The next local experiment should retain failed-stage events
and measure per-stage latency before choosing any further prompt/resource
change. Production and 65-case performance claims remain unchanged.

## Isolated compact driver rebuttal

An opt-in local context experiment replaced tool-call history with the verified
driver brief and verbatim facts already read by that side. Using the first
(missing-GPS) hearing from the batched bundle above, a single driver rebuttal
completed in **55.291 seconds**, within the unchanged 90-second deadline.
All three response citations passed `verify_rebuttal` (C1, C2, C3).

This verifies completion and valid references, not substantive correctness:
the first response interpreted the rider's waiting message and the driver's
arrival claim as mutual agreement that the driver was at the pickup point.
Those messages do not establish physical arrival. The output also requested a
full refund despite missing GPS. A later judge and policy check are necessary;
no decision or automatic action was evaluated in this isolated test.

Only one side ran, without the other agent competing for local resources. It
uses the missing-GPS snapshot, not the recovered-GPS snapshot whose rebuttals
failed previously. This is not a measured before/after speed improvement, a
completed paired court run, or a performance score. Full concurrent validation
remains outstanding. The standalone diagnostic bundle is
`review_runs/local-qwen3-2026-10-11/driver-compact-rebuttal.json`.

Code regression verification after the compact-context option: **701 passed,
1 skipped**. Original model prompts and history remain the default for cloud
providers; the opt-in experiment is labelled separately.

## Concurrent paired court with batched retrieval and compact rebuttal

The two-worker local server ran both advocates concurrently, with both opt-in
flags enabled. The full experiment took **461.64 seconds** and ended in
**review_failed: Driver Advocate unavailable**. This is a single trial with
changed retrieval and context conditions, not a comparable benchmark score.

| Hearing | Stage | Status | Seconds | Deadline |
| --- | --- | --- | ---: | ---: |
| Missing GPS | Rider brief | Completed | 64.170 | 120 |
| Missing GPS | Driver brief | Completed | 71.025 | 120 |
| Missing GPS | Rider rebuttal | Completed | 64.098 | 90 |
| Missing GPS | Driver rebuttal | Completed | 57.371 | 90 |
| Missing GPS | Judge | Completed | 108.154 | 120 |
| Recovered GPS | Rider brief | Completed | 102.612 | 120 |
| Recovered GPS | Driver brief | Timeout | 120.031 | 120 |
| Recovered GPS | Judge | Completed | 57.539 | 120 |
| Recovered GPS | Judge correction | Completed | 40.562 | 120 |

The missing-GPS hearing completed in **243.422 seconds** and escalated due to
insufficient evidence. Both concurrent rebuttals finished inside the original
deadline. Their citation checks passed, but some arguments still treated chat
claims as proof of physical arrival or absence; valid IDs do not establish
sound reasoning. This does not prove improvement over the original workflow.

The recovered-GPS attempt took **218.216 seconds**. The driver brief timed out,
so no complete adversarial rebuttal stage was available. The subsequent judge
and correction described a full $6.61 refund and an account flag in prose, but
left the structured amount null and flag false. The hard check rejected a
refund without a positive amount and escalated. This diagnostic record is
retained under `attempts`, not counted as a completed hearing or a success.

The saved bundle contains **39 events** for the first attempt and **29 events**
for the failed second attempt, both full records, and all stage timings.
`comparison` and experiment `scores` remain null. The original demo and 65-case
benchmark were not overwritten. Bundle:
`review_runs/local-qwen3-2026-10-11/court-batched-compact/e32d46c62af247e8bebf922fc9c7e418.json`.

One local server request returned HTTP 500 during this experiment; subsequent
requests succeeded. That observation alone does not establish the cause of
the driver timeout. Further work should separate provider reliability, brief
latency, and structured-output correctness rather than increase deadlines or
populate missing adjudication fields from generated prose. These opt-in
changes are still local and uncommitted; no PR update or deployment is implied.
