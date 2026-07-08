#!/usr/bin/env bash
# Runs the benchmark suite with fixed, pinned parameters and captures each
# tool's raw stdout to raw/<tool>.txt. Only sysbench-cpu is wired up so far;
# other tools get added in the same shape (§10 build order).
set -euo pipefail

RAW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/raw"
mkdir -p "$RAW_DIR"

THREADS="$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
DURATION="${BENCH_DURATION:-10}"

echo "==> sysbench cpu (threads=$THREADS, time=${DURATION}s)"
sysbench cpu \
  --cpu-max-prime=20000 \
  --threads="$THREADS" \
  --time="$DURATION" \
  run > "$RAW_DIR/sysbench_cpu.txt"

echo "==> wrote $RAW_DIR/sysbench_cpu.txt"
