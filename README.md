# Akina Court · Ryde Dispute Court

**AI can argue; only verified policy can authorize an action.** Code computes the facts of a ride-hailing dispute, runs the policy clauses as code, and lets two AI advocates and an AI judge argue only the questions code cannot settle. A refund voucher is cleared automatically only when the ruling agrees with the policy as code; everything else goes to a person with the case prepared. About <!--n:court.latency_mean_s:.0f-->26<!--/n--> seconds per case.

Team **Akina Court** · Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 · Ryde track · built with CodeBuddy, DeepSeek-chat via the DeepSeek API.

**Live demo:** https://akina.kalitas.cc · **Results:** `/report.html` · **Architecture:** `web/architecture-system.png`

## Results at a glance

<!--n:cases-->65<!--/n--> synthetic cases (<!--n:types.route_deviation-->42<!--/n--> route deviation, <!--n:types.no_show-->18<!--/n--> no-show, <!--n:types.safety-->5<!--/n--> safety), one model, four systems. "Match" = same outcome, same hand-off decision, amount within a cent of the reference derived from the written policy.

| | Raw LLM, one call | Facts by code, one call | Judge + policy check | Full court |
|---|---|---|---|---|
| Right, or handed to a person (only a wrong decision that executes counts against a system) | <!--n:arms.raw.safe-->34<!--/n-->/<!--n:cases-->65<!--/n--> | <!--n:arms.facts_only.safe-->34<!--/n-->/<!--n:cases-->65<!--/n--> | <!--n:arms.judge_only.safe-->58<!--/n-->/<!--n:cases-->65<!--/n--> | **<!--n:arms.court.safe-->65<!--/n-->/<!--n:cases-->65<!--/n-->** |
| Wrong decision **and executed** | <!--n:arms.raw.wrong_executed_single_call-->31<!--/n-->/<!--n:cases-->65<!--/n--> | <!--n:arms.facts_only.wrong_executed_single_call-->31<!--/n-->/<!--n:cases-->65<!--/n--> | <!--n:arms.judge_only.wrong_and_executed_with_gate-->7<!--/n-->/<!--n:cases-->65<!--/n--> | **<!--n:arms.court.wrong_and_executed_with_gate-->0<!--/n-->/<!--n:cases-->65<!--/n-->** |
| Cleared automatically | – | – | <!--n:arms.judge_only.auto-->46<!--/n-->/<!--n:cases-->65<!--/n--> | **<!--n:arms.court.auto-->42<!--/n-->/<!--n:cases-->65<!--/n-->** |
| Invalid citations (fact + clause ids) | <!--n:per_arm.raw.cites_invalid-->29<!--/n--> / <!--n:per_arm.raw.cites_total-->309<!--/n--> | <!--n:per_arm.facts_only.cites_invalid-->2<!--/n--> / <!--n:per_arm.facts_only.cites_total-->1098<!--/n--> | <!--n:per_arm.judge_only.cites_invalid-->0<!--/n--> / <!--n:per_arm.judge_only.cites_total-->1141<!--/n--> | **<!--n:per_arm.court.cites_invalid-->0<!--/n--> / <!--n:per_arm.court.cites_total-->1242<!--/n-->** |
| Mean time | <!--n:per_arm.raw.latency_mean_s:.1f-->7.2<!--/n--> s | <!--n:per_arm.facts_only.latency_mean_s:.1f-->6.4<!--/n--> s | <!--n:per_arm.judge_only.latency_mean_s:.1f-->8.6<!--/n--> s | <!--n:per_arm.court.latency_mean_s:.1f-->26.5<!--/n--> s per case |

Identity-swap runs: <!--n:swap_note-->not yet re-run on this version<!--/n-->. Repeat runs: <!--n:repeat_note-->not yet re-run on this version<!--/n-->. These numbers measure conformance to our written policy on synthetic cases, not production accuracy. Per-case tables, ablations and caveats: `/report.html`. A held-out set written after the prompts were frozen is scored separately (`bench/blind_report.py`): <!--n:blind_note-->12 cases; full court 11/12 matched, 0/12 wrong and executed; judge + check 11/12<!--/n-->.

## How it works

1. **Code computes the facts.** GPS against the optimal OneMap route (each off-route segment with its extra kilometres, stops, who confirmed arrival when), fare lines, LTA incidents and speed bands, weather, both histories become a numbered fact table that is identical on every run. Chat and statements are copied verbatim with their times; what a message *means* is never computed by code. Missing evidence (no GPS, a hole, a trace that ends early, an untimed message, no record of who cancelled) is itself a fact (`core/facts/tools.py`).
2. **Code runs the policy first.** The <!--n:policy.predicates-->11<!--/n--> sourced clauses the three dispute types need run as predicates: applies, does not apply, or left to the judge. The result is the set of allowed outcomes, the amount formula and the open questions; escalating to a person is always allowed (`core/policy_engine.py`).
3. **Three agents argue, then code checks the form.** The Rider and Driver Advocates read facts through logged tool calls, write briefs that cite fact and clause ids, and rebut each other. Each advocate also states the policy ground its reading supports for every open segment: a ground both state binds the Judge; the Judge otherwise decides between the grounds argued, a finding on a ground neither side put forward is sent back once, then goes to a person, and an exemption does not execute while the two sides disagree on whether the rider agreed to a general route choice or to a named road. The Judge rules only on the open questions, names the policy ground each finding rests on (a rider-named stop, a general route choice, an agreement no record ties to the road driven), screens every case for safety and states whether the evidence is sufficient. Code then checks: every cited id exists; the outcome is allowed; the amount matches the formula within a cent; an exempt segment rests on a rider message sent before it; a named-road agreement without a record tying the driven segment to it stays undetermined; an account flag is only ever a structured field. Pass: the voucher is cleared and the notice to each party is checked against the ruling. Fail, undetermined, insufficient evidence or a safety concern: a person decides, with a fixed notice that promises nothing (`core/verify.py`, `core/orchestrate.py`). Every step is one event on an SSE stream, so the hearing is observable and replayable.

## Where the numbers come from

- Model: deepseek-chat via the DeepSeek API (pydantic-ai), the same for all four systems. The API labels the served model `<!--n:provenance.served_model-->deepseek-flash<!--/n-->` in every stored response while the requested id is `deepseek-chat`; both ids and the API's own trace ids are kept in the audit sample.
- Runs: <!--n:provenance.window-->2026-10-10 17:35 to 2026-10-11 02:37 UTC<!--/n-->; <!--n:provenance.runs-->260<!--/n--> stored case-system runs, <!--n:provenance.calls_c-->622<!--/n--> recorded model calls, <!--n:provenance.input_tokens_m:.1f-->10.2<!--/n--> M input tokens. Every run file carries model id, timestamp, latency and API-reported usage; every court case has a `.record.json` with the full event log of its hearing, e.g. `bench/results/court/B-0024.record.json`.
- Audit sample: <!--n:provenance.audit_runs-->20<!--/n--> fresh runs (<!--n:provenance.http_calls-->73<!--/n--> HTTP calls) with the exact requests and raw responses: `bench/results/audit_sample/`.
- Citations: <!--n:per_arm.court.cites_invalid-->0<!--/n--> invalid citations in <!--n:per_arm.court.cites_total-->1242<!--/n--> for the full court; <!--n:arms.court.wrong_and_executed_with_gate-->0<!--/n-->/<!--n:cases-->65<!--/n--> wrong decisions executed.
- Reference answers are derived by `data/synth/scenarios.py` from the written policy and the scenario labels, never from a model; every change is logged in `data/bench/REFERENCE_CHANGES.md`. A rule shared by the engine and the reference would be invisible to this benchmark.
- Verify: `.venv/bin/python bench/provenance.py --hashes` recomputes the table from the run files. With a `DEEPSEEK_API_KEY`, `scripts/run_case.py C-0001` or the replay page's **Run live** produces a fresh ruling with a fresh receipt (case, policy, code and model fingerprints).

## The organisers' sample

`data/samples/DISP-002.md` imports as is (`.venv/bin/python -m core.ingest data/samples/DISP-002.md`) and runs through the same court. Result: the $<!--n:demo.disp002_fee:.2f-->5.00<!--/n--> cancellation charge is upheld, as the sample's own expected ruling states. The record's own parameters (8-minute no-show threshold, $<!--n:demo.disp002_fee:.2f-->5.00<!--/n--> fee) are read where the Ryde clauses say 3 minutes / $6.61, and the trace says so; the platform's automatic arrival confirmation is recorded as such, never as a driver's tap. What the sample lacks (traffic, weather, fare lines) stays empty. Replay: `/replay.html?case=DISP-002&phase=court`.

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env            # DEEPSEEK_API_KEY, only for live runs
scripts/dev.sh                  # http://localhost:8000
.venv/bin/python -m pytest -q   # <!--n:tests-->706<!--/n--> tests, no key needed
```

Without a key the pages play back the stored runs in `runs/` (seven demo rulings plus the organisers' sample, and eight pre-recorded fault injections and counterfactuals). Benchmark: `bench/run_bench.py --arms raw,facts_only,judge_only,court`, then `bench/report.py`, `bench/gate_ablation.py`, `bench/dashboard.py`. Deploy: `deploy/` (Docker + Caddy; `deploy/lighthouse.sh` for Tencent Cloud Lighthouse).

## Pages

- `/` landing · `/replay.html?case=C-0001` animated replay and court (`&mode=expert`, `&phase=court`, `&cf=<counterfactual>`, `&run=<stored run>`)
- `/ops.html` what reaches a person · `/policy.html` the policy with sources and the <!--n:policy.gaps-->13<!--/n--> disclosed gaps · `/report.html` results · `/court.html` expert court · `/submission.json` machine-readable claims

## Limits

Synthetic cases on real OneMap road geometry; one model; reference answers derived from the policy, not from human labelling; refunds are advice (a voucher), account actions always go to a person; single-worker demo service.

## Repository map

| path | what |
|---|---|
| `core/facts/tools.py` · `core/policy_engine.py` | facts by code; clauses as predicates, allowed outcomes, amount formula, open questions |
| `core/agents/` · `core/verify.py` · `core/orchestrate.py` | advocates, judge, notice writer; form checks; the hearing |
| `policy/` | <!--n:policy.clauses-->21<!--/n--> sourced clauses (<!--n:policy.citable-->17<!--/n--> citable + <!--n:policy.informational-->4<!--/n--> informational) + <!--n:policy.gaps-->13<!--/n--> open gaps; `clauses_en.json` behind `/policy.html` |
| `data/` · `runs/` | demo cases, benchmark and held-out sets with reference answers, stored runs |
| `bench/` · `scripts/` · `tests/` | benchmark runner, scoring, pages; CLI runner and pre-recording; offline tests |
| `web/` · `app/main.py` · `deploy/` | pages; FastAPI + SSE; Docker, Caddy, Lighthouse helper |

## CodeBuddy

Developed with CodeBuddy; conversation screenshots and a short development reflection are part of the submission package.
