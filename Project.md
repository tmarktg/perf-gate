# perf-gate — Automated Performance-Regression Gate

A CI job that runs standard Linux benchmarks (`sysbench`, `stress-ng`, `fio`),
parses the results into structured numbers, compares them against a committed
baseline, and **fails the build when performance regresses beyond a tolerance** —
while tolerating the run-to-run noise inherent to shared CI runners.

> The point of this project is not "I can run a benchmark." It's "I can turn
> noisy benchmark output into a trustworthy pass/fail signal." That distinction
> is the entire craft of platform/systems test, and it's what the README and
> your interview answers should lead with.

---

## 1. Problem statement

Running a benchmark is easy. Running it _in CI_ and deciding "is this a real
regression or just noise?" is the hard part, because:

- CI runners are **shared, virtualized, and noisy** — the same commit can vary
  10–30% run-to-run on CPU-bound work with nothing changed.
- A naive absolute threshold (`fail if score < 5000`) will flag false
  regressions constantly and get muted/ignored — the classic failure mode of
  perf gates.

So the design problem is: **detect a genuine regression while tolerating
environmental variance.** Every decision below serves that goal.

---

## 2. Scope (deliberately small)

In scope:

- CPU, memory, thread, and disk-IO benchmarks via off-the-shelf tools.
- A parser turning tool stdout into structured metrics.
- A baseline file committed to the repo.
- A comparison step with tolerance logic.
- A GitHub Actions workflow that gates on the result.

Explicitly **out** of scope (say so in the README — scoping is a signal):

- Cross-machine comparison (baseline is per-runner-class, see §6 caveat).
- A time-series DB / dashboard. Overkill for a portfolio piece.
- Micro-benchmarking your own code. This gates _the system_, not a function.

---

## 3. Architecture

```
┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│ run_bench.sh│──▶│ raw output   │──▶│ parse.py      │──▶│ results.json │
│ (sysbench,  │   │ (per-tool    │   │ (stdout →     │   │ (structured  │
│  stress-ng, │   │  stdout)     │   │  metrics)     │   │  metrics)    │
│  fio)       │   └──────────────┘   └───────────────┘   └──────┬───────┘
└─────────────┘                                                  │
                                                                 ▼
                        ┌────────────────┐   ┌──────────────────────────┐
                        │ baseline.json  │──▶│ compare.py               │
                        │ (committed)    │   │ results vs baseline      │
                        └────────────────┘   │ + tolerance → exit 0/1   │
                                             └──────────────────────────┘
                                                                 │
                                                    ┌────────────┴───────────┐
                                                    │ exit 1 → CI job fails   │
                                                    │ + markdown summary      │
                                                    └─────────────────────────┘
```

Four moving parts, each independently testable:

1. **`run_bench.sh`** — thin wrapper that invokes each tool with fixed,
   pinned parameters and captures stdout to per-tool files. Determinism of
   _inputs_ matters: same thread count, same duration, same block size every run.
2. **`parse.py`** — the real engineering. Each tool has a different, ugly
   output format; you normalize them all into one schema.
3. **`compare.py`** — the decision logic. Reads `results.json` + `baseline.json`,
   applies tolerance, emits a verdict + human-readable diff, sets exit code.
4. **`.github/workflows/perf-gate.yml`** — orchestrates the above and gates the PR.

---

## 4. The benchmarks and what each measures

| Tool              | Command shape (pin these)                                                                           | Metric you extract  |
| ----------------- | --------------------------------------------------------------------------------------------------- | ------------------- |
| `sysbench cpu`    | `sysbench cpu --cpu-max-prime=20000 --threads=N --time=T run`                                       | events/sec          |
| `sysbench memory` | `sysbench memory --memory-block-size=1K --memory-total-size=10G run`                                | MiB/sec transferred |
| `stress-ng`       | `stress-ng --cpu N --cpu-method matrixprod --metrics-brief -t Ts`                                   | bogo-ops/sec        |
| `fio`             | `fio --name=randread --ioengine=libaio --rw=randread --bs=4k --size=256M --runtime=Ts --time_based` | IOPS, bw (KiB/s)    |

Notes:

- **Pin every parameter.** A benchmark whose workload changes between runs is
  useless as a gate. Duration `T` is a tradeoff: longer = less noise, but
  slower CI. Start at 10s per tool.
- `fio` on a CI runner measures the runner's virtual disk, which is _extremely_
  noisy — consider making the disk gate advisory (warn, don't fail) while CPU
  is enforced. That decision is itself worth documenting.

---

## 5. The results schema (design this first)

Everything keys off a single normalized schema. Design it before writing parsers.

```json
{
  "metadata": {
    "timestamp": "2026-07-08T00:00:00Z",
    "runner_os": "ubuntu-24.04",
    "cpu_model": "read from /proc/cpuinfo",
    "nproc": 4,
    "commit": "git sha"
  },
  "metrics": {
    "sysbench_cpu_events_per_sec": {
      "value": 1234.5,
      "unit": "events/s",
      "higher_is_better": true
    },
    "sysbench_memory_mib_per_sec": {
      "value": 8910.0,
      "unit": "MiB/s",
      "higher_is_better": true
    },
    "stressng_cpu_bogo_ops_per_sec": {
      "value": 456.7,
      "unit": "bogo-ops/s",
      "higher_is_better": true
    },
    "fio_randread_iops": {
      "value": 12000,
      "unit": "IOPS",
      "higher_is_better": true
    }
  }
}
```

The `higher_is_better` flag lets `compare.py` stay generic — it never
hard-codes the direction of "good" per metric. (If you add latency metrics
later, those are `higher_is_better: false` and the same comparator handles them.)

`metadata.cpu_model` / `nproc` matter because of the caveat in §6 — a baseline
is only valid for the hardware class it was captured on.

---

## 6. The hard part: tolerance & noise (lead with this everywhere)

This is the section that makes the project worth building. Pick ONE strategy to
start, then mention the others in the README as "what I'd do next."

**Strategy A — Percentage tolerance band (simplest, start here).**
Fail only if a metric is worse than baseline by more than `X%`.

```
regression if:  higher_is_better and value < baseline * (1 - tol)
             or (not higher_is_better) and value > baseline * (1 + tol)
```

Set `tol` generously at first (e.g. 15–20%) precisely _because_ runners are
noisy. A gate that cries wolf gets disabled. Tuning this down as you gather
data is the real work — say that.

**Strategy B — Best-of-N runs.** Run each benchmark N times, take the _best_
result (peak throughput is less noise-corrupted than mean on a contended host).
Cuts false positives hard, costs CI time. Good "next step."

**Strategy C — Statistical.** Run N times, compute mean + stddev, flag a
regression only if the new value is > k standard deviations below baseline mean.
More principled, more code. Mention it; you don't need it for v1.

**What NOT to do (and say why in the README):** absolute thresholds, single-run
comparisons, or a tight (<5%) tolerance on a shared runner. Each of those
produces a gate nobody trusts.

The honest framing for interviews: _"The interesting problem wasn't measuring
performance — it was deciding how confident I could be that a drop was real
given the runner is shared. I started with a wide percentage band because a
false-alarming gate is worse than no gate, and my roadmap was to tighten it
using best-of-N once I'd collected variance data."_

---

## 7. `compare.py` behavior

- Input: `results.json`, `baseline.json`, `--tolerance` (default 0.15),
  optional `--advisory-metrics fio_randread_iops` (warn, don't fail).
- For each metric present in both: compute % delta, apply the §6 rule.
- Output a **markdown table** to stdout (metric | baseline | current | Δ% | verdict)
  so it renders cleanly in the GitHub Actions job summary.
- Exit `1` if any _enforced_ metric regressed; `0` otherwise. Advisory
  regressions print a ⚠️ but don't fail.
- Handle missing metrics gracefully (a metric in results but not baseline →
  print "new metric, no baseline" rather than crashing). This robustness is the
  same instinct as your stock-pipeline "distinguish expected-empty from failure."

---

## 8. GitHub Actions workflow (shape, not full YAML)

```
on: pull_request
jobs:
  perf-gate:
    runs-on: ubuntu-24.04
    steps:
      - checkout
      - install tools:  sudo apt-get install -y sysbench stress-ng fio
      - run: ./run_bench.sh            # produces raw/*.txt
      - run: python parse.py raw/ -o results.json
      - run: python compare.py results.json baseline.json --tolerance 0.15
             --advisory-metrics fio_randread_iops >> "$GITHUB_STEP_SUMMARY"
      - if: failure()  → upload results.json as artifact for debugging
```

Key touches that read as "this person has done CI":

- Write the comparison table to `$GITHUB_STEP_SUMMARY` so reviewers see the
  verdict without opening logs.
- Upload `results.json` as an artifact on failure so a regression is debuggable.
- Pin the runner image (`ubuntu-24.04`, not `ubuntu-latest`) — baselines are
  only valid per runner class (§6 caveat). Document this.

---

## 9. Regenerating the baseline

You need a deliberate, auditable way to update the baseline (you don't want it
silently drifting).

- A separate manually-triggered workflow (`workflow_dispatch`) or a `make
baseline` target that runs the benchmarks and writes `baseline.json`.
- Commit the baseline via PR so the change is reviewed — never auto-commit from
  CI. Treat "raising/lowering the bar" as a human decision.

---

## 10. Build order (so you're never blocked)

1. `run_bench.sh` with one tool (`sysbench cpu`), dump stdout to a file.
2. `parse.py` for that one tool → `results.json`. Design the schema here.
3. Copy `results.json` → `baseline.json` by hand for the first baseline.
4. `compare.py` with Strategy A tolerance. Prove it fails when you hand-edit
   the baseline to be unrealistically high.
5. Wrap in the GHA workflow. Confirm a red X on a forced regression.
6. _Then_ add the other three tools, each = one new parser + one schema entry.
7. Write the README, leading with §1 and §6.

Ship step 5 before adding tools. A working single-metric gate beats a
half-wired four-metric one.

---

## 11. README framing (the part that gets you the interview)

Structure the README as:

1. One-line what-it-is.
2. **The problem** (§1) — noisy runners, why naive gates fail.
3. **The approach** — parse → compare → gate, with the tolerance strategy.
4. A screenshot of the GitHub Actions summary table (green pass + a forced red fail).
5. "What I'd do next": best-of-N, statistical bands, per-runner baselines.

Do NOT open with "I ran sysbench." Open with the regression-detection problem.
The tool usage is table stakes; the noise-handling judgment is the differentiator,
and it maps almost word-for-word onto the Qualcomm JD's "automate industry-standard
benchmarks" plus the unstated skill of "tell a real regression from environmental
noise."

---

## 12. Suggested repo layout

```
perf-gate/
├── README.md
├── DESIGN.md            ← this file
├── run_bench.sh
├── parse.py
├── compare.py
├── baseline.json
├── raw/                 ← gitignored, benchmark stdout
├── tests/
│   └── test_parse.py    ← unit-test the parsers on captured sample output
└── .github/workflows/
    ├── perf-gate.yml
    └── baseline.yml
```

`tests/test_parse.py` is worth doing: capture a sample of each tool's real
output once, commit it as a fixture, and unit-test that your parser extracts the
right number. It's a small thing that signals "I test my test tooling" — exactly
the right note for a test-engineering role.
