#!/usr/bin/env bash
# Runs the benchmark suite with fixed, pinned parameters and captures each
# tool's raw stdout to raw/<tool>.txt. Determinism of *inputs* matters: same
# thread count, same duration, same block size every run (§4).
set -euo pipefail

RAW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/raw"
mkdir -p "$RAW_DIR"

THREADS="$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
DURATION="${BENCH_DURATION:-10}"
# libaio is Linux-only; override to posixaio for local macOS testing.
FIO_IOENGINE="${FIO_IOENGINE:-libaio}"

echo "==> sysbench cpu (threads=$THREADS, time=${DURATION}s)"
sysbench cpu \
  --cpu-max-prime=20000 \
  --threads="$THREADS" \
  --time="$DURATION" \
  run > "$RAW_DIR/sysbench_cpu.txt"

echo "==> sysbench memory (block-size=1K, total-size=10G)"
sysbench memory \
  --memory-block-size=1K \
  --memory-total-size=10G \
  run > "$RAW_DIR/sysbench_memory.txt"

echo "==> stress-ng cpu (threads=$THREADS, time=${DURATION}s)"
stress-ng \
  --cpu "$THREADS" \
  --cpu-method matrixprod \
  --metrics-brief \
  -t "${DURATION}s" > "$RAW_DIR/stress_ng_cpu.txt" 2>&1

echo "==> fio randread (bs=4k, size=256M, time=${DURATION}s)"
FIO_SCRATCH="$(mktemp -d)"
trap 'rm -rf "$FIO_SCRATCH"' EXIT
fio \
  --name=randread \
  --ioengine="$FIO_IOENGINE" \
  --rw=randread \
  --bs=4k \
  --size=256M \
  --runtime="${DURATION}s" \
  --time_based \
  --directory="$FIO_SCRATCH" \
  --output-format=json > "$RAW_DIR/fio_randread.txt"

echo "==> wrote raw output to $RAW_DIR"
