#!/usr/bin/env python3
"""Compare results.json against baseline.json with a tolerance band (§6/§7).

Fails the build (exit 1) if any *enforced* metric regressed beyond
--tolerance. Metrics listed in --advisory-metrics still print a warning on
regression but never fail the build.
"""
import argparse
import json
import sys
from pathlib import Path


def pct_delta(value: float, baseline: float) -> float:
    return (value - baseline) / baseline * 100.0


def fmt(value: float) -> str:
    return f"{value:,.2f}"


def is_regression(value: float, baseline: float, higher_is_better: bool, tol: float) -> bool:
    if higher_is_better:
        return value < baseline * (1 - tol)
    return value > baseline * (1 + tol)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", type=Path)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("--tolerance", type=float, default=0.15, help="fractional tolerance, e.g. 0.15 = 15%%")
    ap.add_argument(
        "--advisory-metrics",
        nargs="*",
        default=[],
        help="metric names that warn on regression instead of failing the build",
    )
    args = ap.parse_args()

    advisory = {m for group in args.advisory_metrics for m in group.split(",")}

    results = json.loads(args.results.read_text())["metrics"]
    baseline = json.loads(args.baseline.read_text())["metrics"]

    rows = []
    build_should_fail = False

    for name in sorted(set(results) | set(baseline)):
        if name not in baseline:
            rows.append((name, "—", fmt(results[name]["value"]), "—", "🆕 new metric, no baseline"))
            continue
        if name not in results:
            rows.append((name, fmt(baseline[name]["value"]), "—", "—", "⚠️ missing in results"))
            continue

        r, b = results[name], baseline[name]
        delta = pct_delta(r["value"], b["value"])
        regressed = is_regression(r["value"], b["value"], b["higher_is_better"], args.tolerance)

        if not regressed:
            verdict = "✅ pass"
        elif name in advisory:
            verdict = "⚠️ regression (advisory)"
        else:
            verdict = "❌ FAIL (regression)"
            build_should_fail = True

        rows.append((name, fmt(b["value"]), fmt(r["value"]), f"{delta:+.1f}%", verdict))

    print(f"## Perf gate results (tolerance: {args.tolerance:.0%})\n")
    print("| metric | baseline | current | Δ% | verdict |")
    print("|---|---|---|---|---|")
    for name, b, r, d, v in rows:
        print(f"| {name} | {b} | {r} | {d} | {v} |")

    sys.exit(1 if build_should_fail else 0)


if __name__ == "__main__":
    main()
