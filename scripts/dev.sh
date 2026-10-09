#!/bin/zsh
# Start the local court service (reads .env; set DEEPSEEK_API_KEY there or in the environment for live runs)
cd "$(dirname "$0")/.."
exec .venv/bin/python -m uvicorn app.main:app --port "${PORT:-8000}" "$@"
