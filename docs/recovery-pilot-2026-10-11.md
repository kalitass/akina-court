# Recovered-evidence model pilot — 2026-10-11

## Result and release decision

Do not enable recovery auto-clearance in the main workflow on the strength of this pilot. Two positive scenarios show that retrieving GPS can turn missing-evidence handoffs into correct outcomes, but the multi-agent arm failed a missing-chat-time boundary scenario and was unnecessarily escalated on one positive scenario. These small derived scenarios do not establish a population accuracy or benchmark improvement.

All roles requested DeepSeek `deepseek-chat`. A minimal API probe and the instrumented agent responses returned `deepseek-flash`. This alias mapping was observed, not assumed. The original 65-case results remain untouched and cannot be treated as a same-version model comparison.

| Scenario | Single judge after recovery | Full court after recovery | Draft reference |
|---|---|---|---|
| R-001: false arrival, driver 613 m away | $6.61 full refund; auto-cleared refund, account flag to a person | Same | $6.61 full refund; human account-flag review |
| R-003: one excused detour, one unexcused | $4.05 partial refund; auto-cleared | Escalated by the existing policy check because the finding consequence was not among the advocates' argued grounds | $4.05 partial refund |
| R-009: GPS restored but rider messages untimed | Escalated; missing timing recognised | $4.05 partial refund auto-cleared; reasoning supplies a nonexistent 14:01 rider-message time | Escalate; draft reference needs teammate review |

All six completed initial hearings correctly escalated the missing-GPS file. Twelve hearings completed across six paired-before/after evaluations. An additional first single-judge attempt was interrupted by the external usage recorder calling the installed runtime's usage property as a method; the recorder was fixed, the failed attempt was preserved and the case rerun. It is neither a successful hearing nor a model decision error. The formal report includes it in attempted-run counts and excludes the repeated R-001 from paired-arm comparison rather than selecting a best run.

## Important failure evidence

R-009 full court after recovery: final ruling says the rider's message was "timestamped 14:01", while snapshot chat timestamps for rider messages are null and the fact table explicitly says timing is unknown. The final policy check says the ruling is consistent and auto-clears it. This demonstrates a factual-support checking gap even if a reviewer later determines that the same monetary outcome follows for other reasons. Citation-ID validity alone did not detect the invented time. Treat the draft reference mismatch as a review finding; the monetary answer and its policy dependence require teammate adjudication.

R-003 full court after recovery: the judge computes $4.05, but the policy check blocks its proposed consequence because the rider and driver advocates supplied different grounds. This preserves a human fallback but loses automatic clearance. Do not relax this check solely to improve the pilot score.

## Next action

Keep the opt-in recovery hearing disabled in the main flow. Review R-009 with the team, including both snapshots, exact fact text, final findings and verification events. The first engineering target is to preserve missing timing explicitly through evidence handoff and prevent unsupported temporal claims from clearing review. Any modification to court policy verification or agent prompts needs the team's complete regenerated runs and ruling-logic gate. Continue reviewer handoff work without claiming that GPS acceptance itself permits automatic action.

References are frozen draft derivatives, not independently held-out cases. Requests, validated GPS, before/after snapshots, events, rulings, notices and receipts are included in the local evidence archive. No real refund or account action occurred. Runtime notice text is simulated and must be labelled as such in any demo.

Recorded usage and account debit are different measurements. The final read showed an account balance decrease of about CNY 0.23 during the pilot; account-wide activity, billing delay and rounding prevent exact per-request attribution. The archive publishes model/token metadata without account balances or credentials.

## Formal report (all attempted evaluations)

# Recovery evaluation report

Draft synthetic references. Failed runs are not correct handoffs; retrieval checks are not model accuracy. Repeated/unmatched trials are not selected for paired comparison. No monetary saving measured.

Preparation files excluded: 0

## Condition group 1

`{"code_hash": "ec8e76a6faaa53d7", "hearing_configuration": {"model": "deepseek:deepseek-chat", "recovery_code_sha256": "8d548be626ba6a097bad65313c8c094addf1f9e438eae57006ae8f098c777268", "role_models": {"ADVOCATE": "deepseek-chat", "JUDGE": "deepseek-chat"}, "stretch": {}, "tokenhub_base_url": null}, "model": "deepseek:deepseek-chat", "policy_hash": "22732a5091cb274a", "role_models": {"advocate": "deepseek-chat", "judge": "deepseek-chat"}, "suite_version": 1}`

| Arm | Attempts | Model completed | Failed | Correct handoffs | Accuracy / completed | Correct automatic / attempted | Wrong automatic |
|---|---:|---:|---:|---:|---:|---:|---:|
| court | 3 | 3 | 0 | 0/0 | 1/3 | 1/3 | 1 |
| judge_only | 4 | 3 | 1 | 0/0 | 3/3 | 2/4 | 0 |

Comparable completed case pairs: 2.
Court minus judge correct automatic count, paired cases only: -1/2.

### Source trials

- R-009 / court: reviewed; `records/42586fe4e5714883b083e118c27ffd29.json`
- R-001 / court: reviewed; `records/2f7f5fe1790f4b5782442887ac4ed5e7.json`
- R-003 / court: reviewed; `records/21156ec1c6734c4587c916885242f7a9.json`
- R-009 / judge_only: reviewed; `records/cf42b0466116428ab00a4f95b886239c.json`
- R-001 / judge_only: reviewed; `records/5aaea44152014d46bea0676ff25d725b.json`
- R-001 / judge_only: review_failed; `records/831c9e512ca64efe910d0f770190ca63.json`; failure: RuntimeError: judge unavailable: safety concern unscreened (no basis listed); evidence unknown: the judge did not run; nothing was weighed
- R-003 / judge_only: reviewed; `records/cc3430aaec7945b19587a317028dd6b0.json`
