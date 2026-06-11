# Real Repository Case Studies

This page highlights representative RepoPilot runs that are useful for interviews, portfolio reviews, and GitHub visitors who want evidence beyond architecture diagrams.

## Case 1: `python-slugify` Contributor README Guidance

- repository: `python-slugify`
- task: improve contributor-facing README guidance around test entrypoints, core implementation location, and regression-case workflow
- run mode: graph workflow, real repository retrieval, patch generation, patch validation, sandbox apply

### Issue

Contributor documentation did not clearly explain:

- how to run tests
- where the core implementation lives
- how to add regression cases safely

### Agent Outcome

RepoPilot localized the task to:

- `README.md`
- `test.py`

It then produced a documentation-oriented patch proposal and reached:

- `patch_apply_check = 1.0`
- `sandbox_apply = 0.667`
- `overall = 0.907`

### Why This Case Matters

This is a good portfolio case because it is not a synthetic toy prompt. The agent had to:

- understand a contributor-experience request instead of a narrow stack trace
- localize the correct repository files
- propose a minimal patch in unified diff format
- survive mixed-EOL repository behavior with a real `git apply` path
- keep the change small and safe

### Representative Command

```powershell
python run_repo_pilot.py --repo ..\open_source_cases\python-slugify --issue "README lacks contributor guidance for running tests, locating the core implementation, and adding regression cases" --graph
```

## Case 2: Self-Repo Documentation Patch Quality

- repository: `RepoPilot`
- tasks: Quick Start clarity, benchmark output explanation, and SQLite run-history inspection
- run mode: graph workflow, repository-local retrieval, patch validation, sandbox apply

### Issue Pattern

The repository already had working features, but GitHub-facing documentation was not explicit enough about:

- how to get started quickly
- how to interpret benchmark outputs
- how to inspect `.repopilot/runs.sqlite3`

### Agent Outcome

RepoPilot now handles these documentation-style tasks as real patching problems instead of generic prose generation. The recent validated self-repo cases reached:

- `schema_stability_self_repo = 0.954`
- `module_path_self_repo = 0.954`
- `readme_quickstart_self_repo = 0.954`
- `benchmark_docs_self_repo = 0.954`
- `sqlite_trace_self_repo = 0.954`

Shared characteristics:

- `patch_apply_check = 1.0`
- `sandbox_apply = 0.667`
- localized support file: `README.md`

### Why This Case Matters

These cases are useful in interviews because they show that the agent can:

- treat documentation tasks as repository changes with diffs, not just explanations
- generate patchable README edits instead of free-form text blobs
- handle patch quality issues such as hunk drift and line-ending mismatches
- convert internal features like SQLite persistence into developer-facing workflows

## Case 3: Stable 8-Case Benchmark Snapshot

RepoPilot also includes a stable self-hosted benchmark for repeated evaluation.

Latest validated snapshot:

- `case_count = 8`
- `pass_rate = 1.0`
- `average_overall = 0.936`
- `average_elapsed_seconds = 70.3`

Coverage includes:

- retrieval and graph localization
- approval gate behavior
- repair signal parsing
- README / contributor experience
- open-source repository patching
- memory and trace store discovery
- dashboard operator controls

For the full table and benchmark commands, see `docs/benchmark.md`.
