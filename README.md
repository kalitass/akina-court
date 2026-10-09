# Akina Court · Ryde Dispute Court

**AI can argue; only verified policy can authorize an action.** Code computes the facts, tests every policy clause, and blocks unsupported outcomes or amounts. Two AI advocates and an AI judge hear a ride-hailing dispute (route deviation, no-show fee, safety) in about 23 seconds; a refund voucher is cleared automatically only when the ruling agrees with the policy as code, and everything else goes to a human with the case prepared.

Team **Akina Court** (named after Mount Akina, the pass where speed is everything: fast rulings, right rulings, every decision step reproducible). Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 · Ryde track · built with CodeBuddy.

**Live demo:** https://akina.kalitas.cc · **Results page:** `/report.html` · **Architecture:** `web/architecture-system.png` (components) · `web/architecture.png` (process)

## Results at a glance

3 core agents · 3 dispute categories · 6 runnable demo cases on real Singapore roads · 49-case benchmark · 4 systems compared · 196 case-system runs · 72 automated tests.

| | Raw LLM, one call | Facts by code, one call | Judge + policy check | Full court |
|---|---|---|---|---|
| Exact core decision (outcome + amount + escalation) | 55.1% | 81.6% | 100% | **49/49** |
| Wrongful refunds | 25% | 38% | 0% | **0%** |
| Core decision wrong **and executed** | 19 cases | 9 | 0 | **0** |
| Cleared for automatic execution | – | – | 42/49 | **42/49** |
| Invalid citations (fact ids + clause ids) | 16 / 220 | 1 / 802 | 0 / 892 | **0 / 961** |
| Identity-swap invariance | not yet re-run on this version (previous version: 81.6% / 91.8% / – / 100%, archived) | | | |
| Mean time per case | 6.7 s | 5.8 s | 8.8 s | 23.0 s |

Synthetic data, one model (DeepSeek-chat), reference answers derived from the written policy: these numbers measure **policy conformance**, not human-ops accuracy. Ablations, per-case tables and caveats are on the results page.

## Problem and users

A rider says the driver took the long way; the driver says the road was closed. A support agent has to read the GPS track, the chat, the fare breakdown, live traffic records and the policy by hand (current-workflow hypothesis; Ryde has not published handling times). Users: platform operations (primary), riders and drivers (plain-language notices), compliance (reproducibility receipt).

## How it works: three agents inside two layers of code

1. **Code computes the facts.** GPS vs the optimal OneMap route, each off-route segment with its extra kilometres, stops, who tapped what and when, fare lines, LTA speed bands and incidents, weather, both histories → a numbered fact table, identical on every run (`core/facts/tools.py`). Both parties' words are copied verbatim with their times and nothing more: what a message *means* (did the rider agree, is this a threat) is never computed by code — the advocates argue it and the judge finds it, and may find it undetermined. Missing evidence (no GPS trace, a hole in it, an untimed message, a metered trip without a distance fare) is itself a fact and never reads as "nothing happened". Then 21 sourced policy clauses run as predicates — applies / does not apply / left to the judge — producing the allowed outcomes and the amount formula; escalating to a person is always among them (`core/policy_engine.py`).
2. **Three agents argue (Pydantic AI, DeepSeek-chat via the DeepSeek API).** The **Rider Advocate** and **Driver Advocate** read facts through logged tool calls, write a brief each (claims citing fact ids and clause ids) and rebut each other point by point, append-only. The **Judge** reads both verified briefs, the policy trace and the open questions, and rules only on those questions (`core/agents/`). Every tool call, brief, rebuttal point and check is one event on an SSE stream: **inter-agent communication is observable** in the court UI.
3. **Code decides what may execute.** Every citation must resolve to a real fact and clause; the outcome must be one the policy allows; the amount must match the formula to the cent; an account flag exists only as a structured field, never as free text. The judge's reading of a message is checked for form, not re-read: an exempt segment must rest on a rider message that exists and was sent before the segment; a driver's statement that the rider agreed verbally is not consent. Pass → refund paid as a Ryde voucher. Fail → human review queue with the reason. A judge who records a safety concern, an undetermined finding or an evidence gap sends the case to a person and code never turns that back into a ruling (`core/verify.py`, `core/orchestrate.py`). Account actions always go to a human.

## Evidence by judging dimension

| Dimension | Evidence | Where |
|---|---|---|
| Impact & Relevance | 3 dispute categories; 41/49 cleared automatically; the ops queue receives only what code could not clear (16%) | `/report.html` |
| Human-Centered Design | Plain-language notice to each party; money automatic, punishment never; "what would change this ruling" on every case; appeal route in the receipt | `/replay.html?case=C-0004&phase=court` |
| AI Interaction | Two advocates with tools and logged reads, briefs, rebuttals with concessions, judge constrained to open questions | `/replay.html?case=C-0001&phase=court` |
| Technical Execution | Fact engine, policy-as-code, verifier, SSE event log, 4-arm benchmark + gate ablation, 56 tests, Docker + Caddy | `core/`, `bench/`, `tests/`, `deploy/` |
| Feasibility | Every clause carries a source; 10 rules Ryde has not published are listed as gaps; Lighthouse deployment; limits table below | `policy/policy.md`, `deploy/` |
| Demo & Storytelling | Animated replay on real roads, plain-language court cards, pre-recorded fault injection and counterfactuals | `/` |
| Innovation & Creativity | The policy runs as code and locks the outcome space before the model speaks; the model fills only interpretive gaps | `core/policy_engine.py` |
| UX & Accessibility | Simple view for an audience, Expert view for auditors; text trip feed mirrors the animation; keyboard scrubbing; pause; reduced-motion respected; light theme | `/replay.html?case=C-0001&theme=light` |
| Responsible AI & Ethics | Citations verified, hallucinated evidence struck in public, safety cases never auto-ruled, identity-swap and prompt-injection audits, reproducibility receipt | `/replay.html?case=C-0001&run=C-0001~fake_fact&phase=court` |
| Overall | Honest numbers with a judge-only ablation and caveats on the first screen | `web/report.html` |

## Where the numbers come from

- Model: requested id deepseek-chat via the DeepSeek API (pydantic-ai client); the API reports serving deepseek-flash in the 2026-10-09 audit sample. One model for all four systems.
- Runs: 2026-10-09 19:03 to 19:52 UTC (the last of several batches that day, after the court stopped labelling chat by keyword; earlier batches are archived); 196 stored case-system runs, 499 recorded model calls, 6.7 M input tokens; every run file carries model id, timestamp, latency and API-reported usage.
- Cases: 49 synthetic scenarios (26 route deviation, 18 no-show, 5 safety), reference answers derived clause by clause from the written policy.
- Inputs: raw JSON with GPS every 30 s + policy; code-computed fact table + policy; judge with the policy trace + check; full court (advocates, rebuttal, judge, check).
- Audit sample: 20 fresh runs (5 cases × 4 systems, 70 HTTP calls) keep the exact requests, the raw responses, DeepSeek trace ids and system fingerprints: bench/results/audit_sample/. Against the reference: full court 5/5, judge + check 5/5, facts by code 4/5, raw LLM 3/5.
- Verify: python bench/provenance.py --hashes recomputes the table from the run files; the replay page's Run live re-runs any case (needs a DEEPSEEK_API_KEY). Method and limits: the section below.

"Match" means agreement with the policy-derived reference: a policy-conformance measure, not production accuracy; the data is synthetic and one model was used. Full method and limits: below.


### What a reviewer can do

1. `.venv/bin/python bench/provenance.py --hashes` recomputes the table above and prints a sha256 per run file.
2. Open any run file, e.g. `bench/results/court/B-0024.json`: parsed ruling, the judge's ruling before verification, verifier lines, tokens, latency, event count. Its companion `B-0024.record.json` holds the full event log of that hearing (every tool call with the fact ids it returned, both briefs, rebuttal points, the judge's ruling, every check) plus facts, certificate, eligibility and notices.
3. On a local copy with `DEEPSEEK_API_KEY` set, re-run any case live from the replay page (`Run live`) or the CLI (`scripts/run_case.py C-0001`): the same model, the same prompts, a fresh ruling with a fresh receipt. Benchmark cases: `bench/run_bench.py --cases B-0007 --arms raw,court --force`.
4. Compare with the provider's usage dashboard for 2026-10-09 19:03–19:52 UTC: the token totals above should match the account's usage for that window.
5. Open `bench/results/audit_sample/court/B-0001/calls/01.json` to read, verbatim, what the rider's advocate was asked and what the model answered, with the provider's trace id.

### Scoring rule, stated plainly

- Exact core decision = same outcome, same escalation flag, and amount within $0.01; a missing amount and $0.00 are treated as the same "no money" (`bench/report.py` and `bench/provenance.py` agree; under a strict null-vs-zero rule the raw and facts-only counts would be 21 and 36 instead of 22 and 38, the court and judge-only counts do not change).
- The reference answers are derived by `data/synth/scenarios.py` with the same fact tools and policy engine that the court's pre-execution check uses, plus developer-authored scenario labels for the interpretive exemptions. A bug shared by the policy engine and the reference would therefore be invisible. 49/49 is internal conformance to our written policy on synthetic scenarios, not independent or human-validated accuracy.

### Limits

Synthetic cases; one model; reference answers derived from the policy, not from blind human labelling; repeat runs only for the court arm (N=2) and swap runs for three arms. The numbers measure conformance to the written policy under controlled inputs, not production accuracy.

## Claims and where to check them

Each claim made on the landing page maps to code, data or a page. Paths are relative to the repository root; URLs are on the running service.

| Claim | Scope | Evidence |
|---|---|---|
| Facts are computed by code, never asked of the model | all cases | `core/facts/tools.py` · `/api/cases/C-0001/facts` |
| The policy runs as code and fixes allowed outcomes and the amount formula | 21 clauses | `core/policy_engine.py` · `/policy.html` · `policy/sources.md` |
| Advocates can only cite facts they read and clauses that exist; invalid claims are struck | 0 invalid citations in 961 (court arm) | `core/verify.py` · `/replay.html?case=C-0001&run=C-0001~fake_fact&phase=court` |
| Unsupported rulings cannot execute; account flags and safety always go to a person | 0 wrong core decisions executed in 49 cases | `core/orchestrate.py` · `/replay.html?case=C-0001&run=C-0001~wrong_amount&phase=court` · `/ops.html` |
| Inter-agent communication is observable and replayable | every run | `runs/*.json`, `bench/results/court/*.record.json` · `/replay.html?case=C-0001&phase=court&mode=expert` |
| Four systems compared on 49 synthetic cases, with a judge-only ablation | 196 case-system runs, 499 model calls | `bench/results/summary.md` · `bench/results/gate_ablation.json` · `/report.html` |
| Rulings are reproducible: case, policy, code and model fingerprints | every run stored by the service | `core/receipt.py` · `/receipt.html?run=C-0001` (rendered) · `/api/runs/C-0001/receipt` (JSON) |
| Benchmark provenance: model ids, time window, token counts, full-capture audit sample | 49 cases × 4 systems | this README (Where the numbers come from) · `bench/provenance.py --hashes` · `bench/results/audit_sample/` |
| Automated tests | 72 tests, no API key needed | `tests/` · `requirements.lock` |

Machine-readable summary with denominators and caveats: `web/submission.json`.

## The organisers' sample dataset

The RydeResolve sample (`data/samples/DISP-002.md`, a no-show charge dispute) imports as is and runs through the same court:

```bash
.venv/bin/python -m core.ingest data/samples/DISP-002.md     # official JSON → data/cases/DISP-002.json (OneMap route fetched or cached)
.venv/bin/python scripts/run_case.py DISP-002                 # full court; expected ruling in data/expected/DISP-002.json
```

Result: cancellation charge upheld (`no_action`), as the sample's own "Expected ruling" states. The dataset's own policy block (5-minute free wait, 8-minute no-show threshold, $5.00 fee) is imported as `policy_params` and the policy check reads it where the Ryde clauses say 3 minutes / $6.61, saying so in the trace. The platform's auto-arrival event is recorded as `arrival_confirmed_by = platform_auto` (radius 10 m) and satisfies the arrival element alongside a driver's "I'm Here" tap; the platform wait timer and the logged call attempts become facts of their own. What the sample does not carry (traffic, weather, fare lines) stays empty and is listed in the case's provenance. Replay: `/replay.html?case=DISP-002&phase=court`.

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt     # or: pip install -r requirements.lock
cp .env.example .env                       # DEEPSEEK_API_KEY (only needed for live runs)
scripts/dev.sh                             # http://localhost:8000
.venv/bin/python -m pytest -q              # 72 tests, no API key needed; includes a link check over every page (paths, #ids, ?case=, shared header)
```

No key needed to browse: `runs/` ships the six demo rulings and eight pre-recorded audits (fault injection, counterfactuals); the replay page plays them back. A key is needed only for **Run live**; the public demo site runs without one, so there the button is disabled and every case plays back a stored run. CLI: `scripts/run_case.py C-0001` (or `all`) compares a fresh run with `data/expected/`. Benchmark: `bench/run_bench.py --arms raw,facts_only,judge_only,court`, then `bench/report.py`, `bench/gate_ablation.py`, `bench/dashboard.py`. Docker: `deploy/`.

## Deploy

`deploy/` holds the Dockerfile wiring, `docker-compose.yml` (app + Caddy TLS) and `lighthouse.sh`, a Tencent Cloud Lighthouse helper driven by `tccli` (`status | price | keypair | create | wait | firewall | deploy | ssh | teardown`; credentials via `TENCENTCLOUD_SECRET_ID/KEY` in the environment). On the server, `deploy/.env` carries `LIVE_RUNS=0` (public demo: stored runs only, no model key), `DEMO_TOKEN` and `DOMAIN`; `docker compose up -d --build` starts both containers and Caddy obtains the certificate. For a private instance with live runs, add `DEEPSEEK_API_KEY` and mount a volume on `/srv/runs`.

## Pages

- `/` — landing page: what it is, four numbers, guided cases, where each judging dimension is on screen.
- `/replay.html?case=C-0001` — animated replay + court. Simple view by default; `&mode=expert` shows every fact id, clause id and tool call. `&phase=court` skips to the court, `&cf=<name>` loads a counterfactual, `&run=<id>` replays a stored run, `&inject=a,b&autorun=1` runs live with fault injection, `&theme=light`.
- `/ops.html` — what reaches a human after the 49-case batch: funnel, the 8 human cases with reasons, account-action lane, boundary panel. `/policy.html` — the policy in English with every clause's source kind and the 10 disclosed gaps.
- `/report.html` — results dashboard. `/court.html` — expert court page (three columns, queue, override). `/submission.json` — machine-readable claims with denominators and caveats.
- API: `/api/cases`, `/api/runs/{id}` (GET / POST / `/stream` SSE / `/receipt`), `/api/demo-controls`, `/api/queue`, `/api/precedents`, `/api/policy`, `/api/health`.

## Limits and operations

| | Today | Production path |
|---|---|---|
| Data | 6 hand-built + 49 synthetic cases on real OneMap routes; no images | Ryde case export → `Case` schema (`core/schemas.py`) |
| Reference answers | Derived from the written policy + scenario labels | Blind human labelling of a sample; appeal outcomes as ground truth |
| Model | DeepSeek-chat only (the provider is a configuration switch) | Second-model smoke test before claiming model independence |
| Cost / latency | ~92k input tokens, 6 calls, 23.9 s per case (7× a single call) | Judge + policy check alone reaches 48/49 at 1/8 of the cost; use the full court where the rebuttal matters |
| Serving | Single uvicorn worker; live runs capped (`MAX_LIVE_RUNS`, `LIVE_RUNS_PER_IP_10MIN`), optional `DEMO_TOKEN`; timeouts per stage fall back to human review | Worker pool, queue, per-agent model keys and usage dashboards, OpenTelemetry → Tencent APM |
| Actions | Refund = Ryde voucher (advice, not execution); account flags queued for a person | Hook `eligibility.actions` to Ryde's wallet and trust-and-safety APIs |

## Repository map

| path | what |
|---|---|
| `core/facts/tools.py` | case → numbered fact table (pure code) |
| `core/policy_engine.py` | clauses as predicates → allowed outcomes, amount formula, open questions |
| `core/agents/` | Rider / Driver Advocate (tools, append-only rebuttal), Judge (no tools), notice writer |
| `core/verify.py`, `core/orchestrate.py` | citation checks, judge self-correction, pre-execution policy check, state machine, events, fault injection |
| `core/counterfactual.py`, `core/receipt.py` | case transforms for audits; reproducibility fingerprints |
| `core/stretch/` | pluggable: precedent store, bad-faith signals, SLA routing, human feedback (env flags) |
| `policy/policy.md` | 21 sourced clauses (17 citable + 4 informational) + 10 open gaps, with `sources.md`; `clauses_en.json` is the English clause table behind `/policy.html` |
| `data/`, `runs/` | cases, expected rulings, benchmark set, stored runs and pre-recorded audits |
| `bench/` | 4-arm benchmark, report, gate ablation, dashboard generator |
| `web/`, `app/main.py` | landing, replay, ops handoff, policy, results, expert court; FastAPI + SSE |
| `docs/` | the hackathon handbook |
| `scripts/` | dev server, CLI runner, pre-recording, wording check |

## CodeBuddy

Developed with CodeBuddy; conversation screenshots and a short development reflection are part of the submission package.
