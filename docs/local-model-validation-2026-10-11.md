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
