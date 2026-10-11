# Evidence recovery integration — 2026-10-11

## Baseline and scope

Integrated on main commit `88fa38fb57444e805fe6b293883e2481d47d6af3`, using the team's current 65-case benchmark. This PR replaces the recovery portion of PR #1; it does not carry the older notice templates, sample replay block, history-window mapping, architecture diagram, or 49-case pages.

The new read-only preview is at `/evidence.html`, with `/api/evidence-demo/{cid}` for C-0001 and C-0004 only. It removes GPS from a copy, requests a synthetic trip-record service, validates the response, and recomputes facts and the policy certificate on a new copy. Unavailable/conflicting/invalid records produce a human investigation task. No model runs, final rulings, refunds, persisted cases, or changes to the existing court pipeline are introduced. The source label identifies the in-process synthetic fixture; it is not authentication for a real external API. The 30-second trace-gap limit is a conservative demo assumption, not Ryde policy.

## Local validation

- Latest main baseline: 599 passed, 1 skipped.
- Integrated full suite: 677 passed, 1 skipped (678 collected).
- Added recovery tests: 78 passed, including one no-op regression check for each of all 65 current benchmark cases.
- The regression checks require no retrieval call, unchanged case hashes, identical computed facts, and identical policy assessment for every existing benchmark case.
- Regression checks also preserve current DISP-002 playback and held-out replay lookup.
- Latest main's existing agent prompts, court orchestration, fact/policy logic, case data, expected answers, benchmark records, and scoring scripts are unchanged by this PR.
- Generated submission/README test counts are refreshed using the team's existing generators; benchmark metrics remain the current 65-case values.

## Required metrics: local rescoring of saved model results

These are historical model outputs rescored locally, **not fresh model calls**, and not evidence of an improvement caused by recovery. Each denominator is all 65 cases. Strict match follows the team's definition: outcome + amount within one cent + escalation flag. Account actions can still require a human even when the core action is automatic.

| Metric | Single judge + check | Full court | Difference (court minus judge) |
| --- | --- | --- | --- |
| Strict reference match | 55/65 (84.6%) | 63/65 (96.9%) | +8 cases / +12.3 percentage points |
| Automatic AND correct core decision | 39/65 (60.0%) | 42/65 (64.6%) | +3 cases / +4.6 percentage points |
| All automatically cleared decisions | 46/65 | 42/65 | -4 cases; includes wrong decisions in judge arm |
| Wrong decisions cleared to execute | 7/65 | 0/65 | -7 cases |
| Core human review flow | 19/65 | 23/65 | +4 cases |

Counts derived with `bench.gate_ablation.court_arm('judge_only')` and `court_arm('court')`. The saved results and scoring implementation are unchanged. Repeating the scorer does not rerun the agents.

## Fresh model benchmark gate

No configured model API key is available in this local session. No fresh model run was performed. Before connecting recovery to agent judgement or changing cases/prompts/rules, run baseline and candidate on the same frozen 65 cases (plus the separate held-out set), same model/configuration, separate output directories. Compare strict accuracy, automatic-and-correct rate, and the judge/court gap; retain individual failures, human handoffs, latency and cost. Never count a human handoff as an automatically correct decision or silently replace stored benchmark figures with unverified results.
