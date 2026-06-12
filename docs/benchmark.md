# Benchmark

RepoPilot benchmark is designed to measure whether the agent can move from issue text to a repair outcome that is inspectable, reproducible, and realistic enough for real repository work.

## What The Benchmark Measures

The benchmark is not only asking whether a patch exists. It is meant to stress the full coding-agent loop:

- issue understanding and localization
- retrieval quality across files and graph neighbors
- patch generation quality
- unified diff validity
- sandbox execution and test behavior
- repair-context replay across rounds
- memory and trace persistence
- reporting quality for operator review

## Benchmark Layers

RepoPilot uses two benchmark layers on purpose.

### 1. Stable local SWE-style suite

This is the repeatable internal suite used for day-to-day regression tracking.

Cases live in:

```text
benchmarks/repo_pilot_cases.json
benchmarks/swe_style_cases.json
```

It is designed to verify real agent behavior such as:

- graph-aware localization
- multi-candidate patch selection
- semantic AST rewrite candidate generation
- repair-context replay
- thread and repo preference persistence
- dashboard and reporting artifacts

### 2. Official/public SWE-bench pathway

RepoPilot can also load local exports of public SWE-bench data and emit harness-compatible predictions.

Supported dataset inputs:

- `json`
- `jsonl`
- `parquet`

This path is for recognized public evaluation workflow, but claims should remain conservative:

- approximate runs are approximate if the checked-out repository snapshot is not the exact official base commit
- authoritative pass rates must come from the official harness environment

## Run Commands

Standard benchmark run:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --save-run
```

Baseline comparison:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --compare-baseline
```

Single-candidate vs multi-candidate comparison:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --run-tests --apply-sandbox --compare-multi-candidate
```

Graph ablation:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --run-tests --apply-sandbox --compare-graph-ablation
```

Local SWE-style evaluation:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --work-dir .repopilot\swe_runs --max-cases 11 --write-json .repopilot\reports\public_eval_latest.json --write-markdown .repopilot\reports\public_eval_latest.md
```

Public SWE-bench export path:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --dataset-path path\to\official_swe_bench.jsonl --dataset-name princeton-nlp/SWE-bench_Verified --dataset-split test --instance-id django__django-16527 --write-preds .repopilot\reports\all_preds.jsonl --write-json .repopilot\reports\official_eval_summary.json
```

Official harness scoring example:

```powershell
python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path .repopilot\reports\all_preds.jsonl
```

## What The Runner Exports

The benchmark output includes:

- `case_count`
- `pass_rate`
- `average_overall`
- per-case `scores`
- baseline and ablation deltas when requested
- `pass_at_1` for SWE-style runs
- `adjusted_pass_at_1` for environment-limited runs
- external repo test results
- cross-file recall and expected-path metrics
- repair-context usage metrics
- trace database references
- Markdown summary artifacts
- `all_preds.jsonl` for public SWE-bench harness evaluation

## Current Public Snapshot

Current self-hosted stable snapshot:

- `case_count = 8`
- `pass_at_1 = 1.0`
- `pass_rate = 1.0`
- `average_overall = 0.936`
- `average_elapsed_seconds = 21.0`

This is a local repeatability signal, not a public leaderboard claim.

## Latest Stable SWE-Style Validation

Validated on the local 11-case SWE-style suite:

- `case_count = 11`
- `strict_pass_at_1 = 0.0`
- `env_adjusted_pass_at_1 = 1.0`
- `average_overall = 0.954`
- `average_elapsed_seconds = 27.76`
- `cross_file_case_count = 3`
- `cross_file_pass_rate = 1.0`
- `expected_path_hit_rate = 0.0`
- `average_expected_path_recall = 0.5`
- `repair_context_usage_rate = 1.0`
- `environment_limited_case_count = 11`

Why strict pass is currently `0.0` on this machine:

- copied SWE-style sandboxes do not yet include `pytest`
- RepoPilot now reports that limitation explicitly
- the runner also exposes an environment-adjusted view so the agent-quality signal is still visible instead of being hidden by infra mismatch

## Case Mix

The stable suite currently covers:

- API schema issues
- module path issues
- README and contributor-experience fixes
- test entrypoint issues
- open-source repository repair tasks
- cross-file repair-context replay
- cross-file patch portfolio coordination
- public-eval reporting

The benchmark intentionally preserves failed or infra-limited cases instead of silently filtering them out.

## What Improved Recently

Recent benchmark gains came from real agent changes rather than score-only tuning:

- better README- and docs-targeted patch generation
- whitespace-tolerant `git apply` fallback on mixed-EOL repositories
- unified-diff hunk recounting before patch validation
- graph-level repair-context replay
- stronger patch ranking with graph, policy, and adversarial signals
- semantic AST rewrite candidate generation

Recent validated documentation-oriented cases:

- `schema_stability_self_repo = 0.954`
- `module_path_self_repo = 0.954`
- `readme_quickstart_self_repo = 0.954`
- `benchmark_docs_self_repo = 0.954`
- `sqlite_trace_self_repo = 0.954`
- `slugify_contributor_docs = 0.907`
- `slugify_test_entrypoint = 0.907`
- `slugify_release_docs = 0.907`

## Reading The Numbers Correctly

The right way to interpret RepoPilot benchmark output is:

- local stable suite tells you whether the engineering loop is regressing
- public SWE-bench export path tells you whether the project can participate in recognized external evaluation
- exact public benchmark claims should only be made when the repository snapshot, environment, and harness all match official conditions

That distinction is important, and the project keeps it explicit on purpose.
