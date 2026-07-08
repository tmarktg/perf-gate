#!/usr/bin/env python3
"""Parse raw benchmark stdout into the normalized results schema (see §5)."""
import argparse
import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def parse_sysbench_cpu(text: str) -> dict:
    m = re.search(r"events per second:\s+([\d.]+)", text)
    if not m:
        raise ValueError("could not find 'events per second' in sysbench cpu output")
    return {
        "value": float(m.group(1)),
        "unit": "events/s",
        "higher_is_better": True,
    }


# raw filename -> (metric name, parser function)
PARSERS = {
    "sysbench_cpu.txt": ("sysbench_cpu_events_per_sec", parse_sysbench_cpu),
}


def cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def nproc() -> int:
    try:
        return int(subprocess.check_output(["nproc"], text=True).strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return int(subprocess.check_output(["sysctl", "-n", "hw.ncpu"], text=True).strip())


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_metadata() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runner_os": platform.platform(),
        "cpu_model": cpu_model(),
        "nproc": nproc(),
        "commit": git_commit(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_dir", type=Path, help="directory containing raw/*.txt benchmark output")
    ap.add_argument("-o", "--output", type=Path, default=Path("results.json"))
    args = ap.parse_args()

    metrics = {}
    for filename, (metric_name, parser) in PARSERS.items():
        raw_file = args.raw_dir / filename
        if not raw_file.exists():
            continue
        metrics[metric_name] = parser(raw_file.read_text())

    if not metrics:
        raise SystemExit(f"no known raw benchmark files found in {args.raw_dir}")

    results = {"metadata": build_metadata(), "metrics": metrics}
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
