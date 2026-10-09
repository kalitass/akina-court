"""Benchmark harness for ryde-dispute: three arms (raw, facts_only, court) over data/bench/.

    bench/baseline.py    single-call LLM arms (raw case JSON / fact table), no advocates, no verification
    bench/run_bench.py   runs arms over the bench set with concurrency, timeouts, repeats, identity swap; resumable
    bench/report.py      metrics -> bench/results/summary.md + summary.json
"""
