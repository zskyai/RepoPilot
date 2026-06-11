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

To compare single-candidate patch generation against the new multi-candidate portfolio mode:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --run-tests --apply-sandbox --compare-multi-candidate
```

To compare no-graph retrieval against the new graph-enhanced rerank and impact prediction mode:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --run-tests --apply-sandbox --compare-graph-ablation
```

To run the SWE-bench style evaluator:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --work-dir .repopilot\swe_runs --max-cases 8
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
- a markdown summary table for README / report reuse

## Public Snapshot

Current public self-hosted SWE-style snapshot:

- `case_count = 8`
- `pass_at_1 = 1.0`
- `pass_rate = 1.0`
- `average_overall = 0.936`
- `average_elapsed_seconds = 70.3`

This is a self-hosted stable suite, not an official SWE-bench leaderboard claim. Its purpose is to show repeatable end-to-end agent behavior on controlled repository tasks.

Recent validated documentation-oriented benchmark gains:

- `schema_stability_self_repo = 0.954`
- `module_path_self_repo = 0.954`
- `readme_quickstart_self_repo = 0.954`
- `benchmark_docs_self_repo = 0.954`
- `sqlite_trace_self_repo = 0.954`
- `slugify_contributor_docs = 0.907`
- `slugify_test_entrypoint = 0.907`
- `slugify_release_docs = 0.907`

These gains came from real patch-quality improvements, especially better README-targeted patch generation, whitespace-tolerant `git apply` fallback on mixed-EOL repositories, and automatic unified-diff hunk recounting before patch validation.

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
- memory store discovery
- persistent trace and checkpoint discovery
- dashboard operator controls

## Latest SWE-Style Results

Validated on the local self-hosted 8-case suite:

- `case_count = 8`
- `pass_at_1 = 1.0`
- `average_elapsed_seconds = 40.9`

```markdown
| case | passed | overall | elapsed_s | trace_db |
|---|---:|---:|---:|---|
| repopilot_self_retrieval_smoke | yes | 0.967 | 77.19 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_retrieval_smoke\.repopilot\traces.sqlite3` |
| repopilot_self_approval_gate | yes | 0.967 | 63.45 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_approval_gate\.repopilot\traces.sqlite3` |
| repopilot_self_repair_signals | yes | 0.967 | 46.31 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_repair_signals\.repopilot\traces.sqlite3` |
| repopilot_self_swe_runner | yes | 0.967 | 24.64 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_swe_runner\.repopilot\traces.sqlite3` |
| repopilot_self_github_workflow | yes | 0.967 | 27.66 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_github_workflow\.repopilot\traces.sqlite3` |
| repopilot_self_memory_store | yes | 0.967 | 28.29 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_memory_store\.repopilot\traces.sqlite3` |
| repopilot_self_trace_store | yes | 0.967 | 31.91 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_trace_store\.repopilot\traces.sqlite3` |
| repopilot_self_dashboard | yes | 0.967 | 27.76 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_full\repopilot_self_dashboard\.repopilot\traces.sqlite3` |
```
