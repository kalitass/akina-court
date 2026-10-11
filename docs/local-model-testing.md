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

The desktop workspace keeps its downloaded runtime and model under
`../local-runtime/`; this directory is outside the Git repository. The
DeepSeek `.env` is preserved, while local experiments use explicit environment
overrides. No API top-up is needed for local inference.
