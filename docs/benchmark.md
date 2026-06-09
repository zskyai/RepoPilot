# Benchmark

## Goal

RepoPilot benchmark is designed to answer:

- can the agent localize relevant files?
- can it generate patch suggestions?
- can patches pass `git apply --check`?
- can patches be applied in sandbox?
- do tests pass?

## Current Cases

Cases are stored in:

```text
benchmarks/repo_pilot_cases.json
```

## Run

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --save-run
```

To compare the current LLM workflow against the deterministic baseline:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --compare-baseline
```

## Output

The benchmark outputs:

- `case_count`
- `pass_rate`
- `average_overall`
- per-case `scores`
- optional baseline-vs-candidate deltas

## Current State

Current benchmark contains 8 stable cases covering:

- API schema issues
- module path issues
- README / contributor experience
- test entrypoint issues
- open source repos

The important point is that failed cases are preserved instead of hidden.

The runner now prints per-case progress and elapsed time before the final JSON summary, which makes long LLM-backed benchmark runs observable in real time.
