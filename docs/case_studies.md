# Real Repository Case Studies

This page highlights representative RepoPilot runs that are useful for interviews, portfolio reviews, and GitHub visitors who want evidence beyond architecture diagrams.

## Case 1: `python-slugify` Contributor README Guidance

- repository: `python-slugify`
- task: improve contributor-facing README guidance around test entrypoints, core implementation location, and regression-case workflow
- run mode: graph workflow, real repository retrieval, patch generation, patch validation

### Issue

Contributor documentation did not clearly explain:

- how to run tests
- where the core implementation lives
- how to add regression cases safely

### Agent Outcome

RepoPilot localized the task to:

- `README.md`
- `CHANGELOG.md`
- `setup.py`

It then produced a documentation-oriented patch proposal and passed:

- `patch_apply_check = 1.0`
- `overall = 0.922`

### Why This Case Matters

This is a good portfolio case because it is not a synthetic toy prompt. The agent had to:

- understand a contributor-experience request instead of a narrow stack trace
- localize the correct repository files
- propose a minimal patch in unified diff format
- keep the change small and safe

### Representative Command

```powershell
python run_repo_pilot.py --repo ..\open_source_cases\python-slugify --issue "README lacks contributor guidance for running tests, locating the core implementation, and adding regression cases" --graph
```

## Case 2: Self-Hosted SWE-Style Evaluation Snapshot

RepoPilot also includes a self-hosted SWE-style suite for stable repeated evaluation.

Latest documented snapshot:

- `case_count = 8`
- `pass_at_1 = 1.0`
- `average_elapsed_seconds = 40.9`

Coverage includes:

- retrieval and graph localization
- approval gate behavior
- repair signal parsing
- GitHub workflow discovery
- memory and trace store discovery
- dashboard operator controls

For the full table, see `docs/benchmark.md`.
