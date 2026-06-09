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

SWE-bench style cases are stored in:

```text
benchmarks/swe_style_cases.json
```

## Run

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --save-run
```

To compare the current LLM workflow against the deterministic baseline:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --compare-baseline
```

To run the SWE-bench style evaluator:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --work-dir .repopilot\swe_runs --max-cases 5
```

## Output

The benchmark outputs:

- `case_count`
- `pass_rate`
- `average_overall`
- per-case `scores`
- optional baseline-vs-candidate deltas
- `pass_at_1` for SWE-style runs
- external repo test results
- `graph_run_id` and `trace_db_path`

## Current State

Current benchmark contains 8 stable cases covering:

- API schema issues
- module path issues
- README / contributor experience
- test entrypoint issues
- open source repos

The important point is that failed cases are preserved instead of hidden.

The runner now prints per-case progress and elapsed time before the final JSON summary, which makes long LLM-backed benchmark runs observable in real time.

## SWE-Style Coverage

The SWE-style suite is intentionally smaller than full SWE-bench, but it uses the same idea:

- one issue description per case
- repository checkout into an isolated workspace
- optional setup commands
- optional external test command
- pass/fail determined by both RepoPilot output and external test status

The current local cases focus on:

- retrieval and graph localization
- approval gate behavior
- structured repair signal generation
- benchmark runner usability
- GitHub/PR workflow documentation and CLI ergonomics
