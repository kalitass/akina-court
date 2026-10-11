#!/usr/bin/env python3
"""Read saved evaluations; no model calls and no benchmark changes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.recovery_report import render, summarise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'review_runs/recovery-suite')
    args = parser.parse_args()
    paths = sorted(args.directory.glob('*/*.json'))
    try:
        report = summarise([(str(p), json.loads(p.read_text())) for p in paths])
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(f'Cannot produce trustworthy report: {exc}')
    print(render(report))


if __name__ == '__main__':
    main()
