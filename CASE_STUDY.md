# Building perf-gate: a case study

**[perf-gate](https://github.com/tmarktg/perf-gate)** is a CI job that fails a
pull request when a Linux performance benchmark regresses beyond a tolerance,
while tolerating the noise that comes with running on a shared GitHub Actions
runner. This is a writeup of how it got built, and — more useful than the
happy path — what broke along the way and what that taught me.

## The design problem, stated once so it doesn't get re-litigated

Running `sysbench` in CI is a one-liner. The actual engineering problem is
deciding, from a single noisy number, whether a build should be blocked. Two
bad answers are easy to reach for:

- **An absolute threshold** (`fail if score < 5000`) breaks the moment the
  runner's neighbor is busy.
- **A single-run comparison with no tolerance** breaks for the same reason,
  just with extra steps.

Both produce a gate that cries wolf, gets muted, and stops meaning anything.
So the actual deliverable isn't "a benchmark runs in CI" — it's a percentage
tolerance band wide enough to survive shared-runner variance, with a clear
account of *why* that width and a plan to tighten it. Everything below is in
service of that one decision.

## Build order: prove the single-metric gate before adding tools

I didn't start by wiring up four benchmarks. I built one metric —
`sysbench cpu` — end to end first: `run_bench.sh` → `parse.py` → a
hand-copied `baseline.json` → `compare.py` → a real GitHub Actions workflow
→ a real red X on a forced regression, all before touching `sysbench
memory`, `stress-ng`, or `fio`. A working single-metric gate is worth more
than a half-wired four-metric one, and it meant every later addition
(memory, stress-ng, fio) was just "one new parser + one schema entry" against
infrastructure already proven to work.

## What actually broke (this is the useful part)

### The baseline was wrong before the gate was even finished

The first `baseline.json` was captured locally, on my Apple Silicon laptop:
**53.8 million events/sec**. The first real CI run, on GitHub's pinned
`ubuntu-24.04` runner (an AMD EPYC 7763, 4 vCPUs), measured **3,128
events/sec** and the gate correctly failed the build.

Nothing had regressed. The two machines just aren't comparable, and the gate
did exactly what it was designed to do: refuse to trust a number it can't
verify against a matching baseline. I'd written that caveat into the design
doc before writing a line of code (§6: *"a baseline is only valid for the
hardware class it was captured on"*) — and then proved it by tripping over
it myself in the first real run. I regenerated the baseline from the actual
CI runner's output and moved on. It's a better anecdote for explaining the
project than anything I could have written by hand, because it happened.

### Proving the red X, not just asserting it

It's easy to write a comparator, run it locally against numbers you control,
and call the gate "done." I didn't trust that. I hand-inflated a *committed*
baseline on a real pull request, pushed it, and watched the actual GitHub
Actions check fail — exit code 1, a red X on the PR, `results.json` uploaded
as a debug artifact — then closed the PR without merging. The difference
between "I wrote code that should fail on a regression" and "I watched it
fail on a regression, in CI, on a real PR" is the entire point of a
regression gate, so I wasn't willing to skip that step.

### Every tool's output format fights back a little differently

- `stress-ng` writes its metrics line to **stderr**, not stdout — silently
  dropped until I redirected `2>&1` in `run_bench.sh`.
- `fio`'s human-readable summary reports IOPS as `39.2k` — a string, not a
  number, and actively hostile to a regex parser. I ran it with
  `--output-format=json` instead and parsed structured output, which is more
  robust than the plain-text approach the design doc originally sketched.
- `fio`'s two metrics ended up marked **advisory** (warn, don't fail) once it
  became clear a CI runner's virtual disk is noisier than its CPU — the same
  principle as the tolerance band itself, applied per-metric instead of
  globally.

Each of these got caught by `tests/test_parse.py`, which unit-tests every
parser against a real captured output sample rather than a synthetic string
I typed by hand — the fixtures are the actual stdout from real runs of each
tool.

### The baseline-regeneration workflow hit a real security gate

Phase 4 (§9 of the design doc) called for a `workflow_dispatch` job that
regenerates the baseline and opens a PR for human review instead of
auto-committing — "raising or lowering the bar is a human decision," not
something CI does silently. The first dispatch failed with:

```
GitHub Actions is not permitted to create or approve pull requests.
```

New repositories ship with that permission off by default. It's a real
security boundary, not a bug, so I stopped and asked before flipping it —
that's a repo-level, security-relevant setting, not something to change
unilaterally on someone's behalf. Once enabled, the workflow ran for real:
it re-benchmarked on the same runner class, diffed the proposed numbers
against the committed baseline (by reusing `compare.py` — the proposed
numbers are just another `results.json` from the comparator's point of
view), and opened an actual pull request with a real diff table. All five
metrics landed within about 3% of the prior baseline — comfortably inside
the 15% tolerance, and a good illustration of what "just noise" is supposed
to look like.

### Screenshots needed a browser, and GitHub Actions summaries need a login

For the README, I wanted real screenshots of a green pass and the red fail,
not mockups. There's no browser tool available by default, so I installed
Playwright and Chromium and drove it myself against the actual public run
pages. That surfaced one more real constraint: GitHub's job **summary**
content (the markdown table `compare.py` writes to
`$GITHUB_STEP_SUMMARY`) isn't visible to a logged-out viewer, even on a
public repository — the page shows "Sign in to view logs" and the summary
text simply isn't in the unauthenticated DOM. The run-overview page (green
`Success`, red `Failure`, the exit-code annotation, the uploaded artifact)
*is* visible without login, so that's what's in the README, paired with the
actual diff tables pulled from real PR data rather than a screenshot that
would've required faking a login session.

## Where it landed

Four benchmarks (`sysbench cpu`, `sysbench memory`, `stress-ng`, `fio`), each
normalized into one schema by `parse.py`, compared against a committed,
human-reviewed `baseline.json` by `compare.py`'s percentage-tolerance logic,
gating every PR via `.github/workflows/perf-gate.yml` and kept current via a
reviewed `workflow_dispatch` job in `baseline.yml`. Full details, the schema,
and the tolerance-strategy tradeoffs are in
[DESIGN.md](DESIGN.md); usage and the real pass/fail evidence are in the
[README](README.md).

## What I'd do differently with more time

- **Best-of-N or a statistical band** instead of a flat 15% — I picked wide
  and simple deliberately, because a false-alarming gate is worse than no
  gate, but 15% is a starting guess, not a tuned number. It should come down
  once there's a few weeks of real variance data instead of one afternoon's
  worth.
- **Per-runner-class baselines** as a first-class concept rather than an
  implicit assumption — right now there's exactly one `baseline.json` for
  `ubuntu-24.04`. The schema already carries `cpu_model` and `nproc` in its
  metadata; it just isn't keyed on them yet.
- **A pinned SHA instead of a major-version tag** for the one third-party
  action in the pipeline (`peter-evans/create-pull-request`) — everything
  else is first-party GitHub actions, and I'd tighten that one further
  before treating this as production infrastructure rather than a portfolio
  piece.
