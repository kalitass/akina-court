# Free local model testing

The optional `LLM_PROVIDER=ollama` backend connects only to
`http://127.0.0.1:11434/v1` and uses a dummy key. It never reads a DeepSeek or
TokenHub credential. A configured backend is not proof that the server is up
or the named model is installed.

The default local model is `qwen3:4b-instruct-2507-q4_K_M`; it must support tool
calling and structured output. Role model overrides still apply. This is a
separate experimental condition, not the model used for the published DeepSeek
benchmark. Do not replace benchmark records or claim a comparable improvement
from a changed model.

## Run

1. Install Ollama from https://ollama.com/download/mac.
2. Start a loopback-only local service with cloud disabled:

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_NUM_PARALLEL=1 ollama serve
```

3. Download the model:

```sh
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

4. In the repository's Python environment, run each arm sequentially:

```sh
LLM_PROVIDER=ollama LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M python scripts/review_recovery.py --case C-0004 --arm court --out review_runs/local/court
LLM_PROVIDER=ollama LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M python scripts/review_recovery.py --case C-0004 --arm judge_only --out review_runs/local/judge_only
```

Use `C-0001` for the route dispute. Original cases, saved demo hearings, and
benchmark results are unchanged. Missing evidence is deliberately introduced
on a copy, then recovered from an explicitly synthetic provider. This is not
a connection to Ryde records. A completed experiment needs two hearings and
`state=reviewed`; failures and timeouts are not successful performance results.
Small local models can fail tool validation or exceed stage timeouts. Those
failures must remain visible, without loosening the policy or citation checks.

## Optional batched evidence experiment

Pass `--batch-evidence` to `scripts/review_recovery.py` with `LLM_PROVIDER=ollama`
to let each advocate read all six evidence slices through one tool call. The
original slice functions still emit their evidence events and track the IDs
read by that advocate; unrelated case IDs are rejected. No facts are inserted
into the prompt before the tool is called. Policy, citation validation, output
validation, and stage deadlines remain the same. This is a different retrieval
condition, not a rerun of the original benchmark. The saved experiment labels
it as `evidence_fetch=batched`; without the flag it records `original`.

```sh
LLM_PROVIDER=ollama LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M python scripts/review_recovery.py --case C-0004 --arm court --batch-evidence --out review_runs/local/court-batched
```

The flag is rejected for cloud providers. Ordinary application runs retain the
original tools unless `LOCAL_BATCH_EVIDENCE=1` is explicitly set with Ollama.

## Failed-review diagnostics

New recovery bundles include `attempts`, one entry for each hearing attempted.
Each records the snapshot version, case ID, captured events, duration, and AI
stage timings (including retries represented by separate correction stages).
When a correctly identified record returns but an agent outage prevents a
completed hearing, that record is preserved under the attempt for diagnosis.
An exception before a record returns preserves the events emitted so far.

Failed attempts are labelled `diagnostic_only`, remain outside `hearings`,
and never receive comparison scores. They do not authorise actions. The UI
shows the failed phase and timings; the full JSON contains the retained record.
Parallel reviews use isolated timing collectors. Ordinary court records and
the original benchmark model prompts remain unchanged by this instrumentation.
Historical bundles have no attempts metadata; it cannot be reconstructed as
measured timing after the fact.

## Optional compact rebuttal experiment

`--compact-rebuttal` with Ollama replaces the advocate's conversational tool
history at the rebuttal stage with its verified brief and the verbatim text and
sources of facts already in that advocate's `seen` set. The opposing brief is
still provided. The full system policy, required grounds, output validators,
tools, and 90-second deadline are unchanged. The advocate can request additional
evidence through the existing tools; putting a fact in the opposing brief does
not mark it as read. This changes the context condition and must be recorded
separately from the benchmark, under `rebuttal_context=compact`.

The flag is local-only and disabled by default (`LOCAL_COMPACT_REBUTTAL=1` is
the explicit local setting). It can be tested independently or alongside
`--batch-evidence`. An isolated rebuttal completion cannot establish that both
hearings complete or that decision accuracy improves.

The desktop workspace keeps its downloaded runtime and model under
`../local-runtime/`; this directory is outside the Git repository. The
DeepSeek `.env` is preserved, while local experiments use explicit environment
overrides. No API top-up is needed for local inference.
