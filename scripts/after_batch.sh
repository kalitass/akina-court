#!/bin/zsh
# After a benchmark batch: regenerate every derived file and every figure the pages quote, then verify. One command,
# no hand edits. Order matters: report and gate_ablation read the same result files and must be run together.
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY bench/report.py                 # bench/results/summary.{json,md}
$PY bench/gate_ablation.py          # bench/results/gate_ablation.json
$PY bench/dashboard.py              # web/report.html
$PY bench/ops_page.py               # web/ops.html
$PY scripts/build_policy_page.py    # web/policy.html
$PY scripts/build_submission.py     # web/submission.json (the `numbers` block is the single source for every page figure)
$PY scripts/sync_numbers.py         # README.md, web/index.html, web/i18n.zh.js
$PY scripts/check_wording.py
$PY -m pytest -q
echo "after_batch: done — review git diff, then commit"
