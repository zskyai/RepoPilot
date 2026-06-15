# RepoPilot

RepoPilot is a production-shaped coding agent for real repositories.

It is built for the part that matters in practice: take a repository issue, localize the relevant code, generate and validate patch candidates, challenge weak fixes, run sandbox verification, collect durable memory, and expose the reasoning path in a way an engineer can inspect.

This is not a toy prompt wrapper. RepoPilot is meant to look and behave like a serious software engineering agent.

## What RepoPilot Does

RepoPilot turns a repository issue into an end-to-end repair workflow:

1. retrieve relevant code with lexical, embedding, symbol, call, import, and graph signals
2. localize likely files, functions, and propagation paths
3. generate multiple patch candidates
4. validate unified diffs with `git apply --check`
5. run candidate patches in isolated sandboxes
6. score and rank candidates with graph, policy, and adversarial signals
7. replay repair context across rounds
8. persist repair memory, user preferences, and thread-level context
9. expose compressed context and a decision tree for operator inspection

## Why It Is Different

Most repo agents stop at "LLM + retrieval + diff text."

RepoPilot pushes deeper on the parts that decide whether a coding agent is actually useful:

- semantic AST rewrite planning for Python targets
- graph-aware file ranking and patch selection
- parallel patch tournament execution in sandbox copies
- adversarial review that challenges weak or superficial patches
- counterexample-driven regeneration when the first patch is not robust
- persistent repair memory plus repo-level preference learning
- thread-aware memory hooks for multi-round workflows
- compressed context packets for large-repo and long-run stability
- decision-tree output for explainability

## Core Architecture

### Retrieval

- Tree-sitter code graph for Python, JavaScript, TypeScript, and TSX
- dense + sparse hybrid retrieval with rerank
- symbol / call / import / graph propagation signals
- impacted-file prediction from local code graph structure

### Planning

- structured root-cause hypothesis
- implementation blueprint
- execution-unit decomposition
- acceptance-bundle generation

### Patch Generation

- rule-based and LLM-assisted patch generation
- AST-aware function-scoped patch candidates
- semantic AST rewrite-plan candidates
- execution-unit-driven multi-candidate patch generation

### Patch Selection

- patch portfolio ranking
- graph-priority bonus
- policy priors learned from past repairs
- adversarial penalty for weak patch archetypes
- dynamic candidate budget for sandbox evaluation

### Repair Loop

- failure parsing from `pytest`, `git apply`, and CI feedback
- repair-context replay across rounds
- counterexample-driven patch regeneration
- sandbox-first validation before worktree mutation

### Memory

- long-term repair memory in `.repopilot/memory.sqlite3`
- repo-level preference persistence
- thread-level profile persistence
- user-style inference from issue text and successful repair history

### Explainability

- compressed context packet
- decision tree with Mermaid-ready structure
- persistent trace and checkpoint artifacts

## Current Capabilities

- multi-agent repo diagnosis and repair workflow
- real OpenAI-compatible LLM integration
- graph-based retrieval and rerank
- semantic AST rewrite candidate generation
- parallel patch sandbox execution
- adversarial patch review
- counterexample-driven regeneration
- worktree patch apply with guardrails
- GitHub PR / CI / comment integration
- interactive CLI mode with guided prompts
- FastAPI dashboard for operator workflows
- SWE-bench-style evaluation runner
- public-eval JSON / Markdown export

## Validated State

Recent verified local state for this repository:

- `22 passed` test suite
- interactive CLI available through `run_repo_pilot.py --interactive`
- compressed context and decision tree emitted in real runs
- repo-level preference persistence loaded in real smoke runs
- semantic AST rewrite candidates integrated into the patch pipeline
- graph-aware and policy-aware patch selection active

Representative real smoke signals observed during recent runs:

- real repo smoke overall around `0.838`
- semantic-AST-oriented smoke overall around `0.863`
- thread memory storage verified
- repo preference loading verified

These are project-internal validation signals, not external leaderboard claims.

## Public Benchmark Position

RepoPilot supports two benchmark layers:

### 1. Stable local SWE-style suite

Used to validate repeatable end-to-end agent behavior on controlled tasks:

- retrieval
- graph localization
- repair context replay
- memory
- dashboard / operator path
- benchmark reporting

### 2. Official/public SWE-bench pathway

RepoPilot can load official/public instances from local `json`, `jsonl`, or `parquet`, run the agent, and export harness-compatible `all_preds.jsonl`.

Important: local approximate runs are clearly labeled as approximate when the repository snapshot is not the exact official base commit.

## Quick Start

### 1. Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

### 2. Configure

Copy `.env.example` to `.env`.

DashScope / Qwen example:

```env
DASHSCOPE_API_KEY=your-key
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Embedding example:

```env
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your-key
EMBEDDING_MODEL=text-embedding-v4
```

Generic OpenAI-compatible example:

```env
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=your-key
LLM_MODEL=gpt-4o-mini
```

GitHub integration:

```env
GITHUB_TOKEN=github_pat_or_classic_token
```

## Run Modes

### Interactive CLI

For guided usage without memorizing flags:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --interactive
```

### Graph Workflow

Main production path:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --repo . --issue "API returns an unstable JSON schema; locate the endpoint and stabilize the contract." --run-tests --apply-sandbox --save-run --use-llm --graph
```

### Worktree Apply

Apply a validated patch back to the repository:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --repo . --issue "Fix a failing package import at startup." --run-tests --apply-sandbox --apply-worktree --save-run --use-llm --graph
```

### GitHub Workflow

Create a PR and inspect CI:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --repo . --issue "GitHub integration smoke" --run-tests --apply-sandbox --apply-worktree --create-pr --poll-ci --comment-body "RepoPilot validation passed." --save-run --use-llm --graph
```

## Dashboard

Start the local dashboard:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api.server:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000/repo-pilot/ui
```

The dashboard exposes:

- run configuration
- selected patch
- failure signals
- compressed context
- decision tree
- full JSON payload

## Memory and Persistence

RepoPilot persists:

- repair memories
- selected patch evidence
- repair journals
- repo-level preference profiles
- thread-level profiles

Primary local stores:

```text
.repopilot/memory.sqlite3
.repopilot/traces.sqlite3
.repopilot/approvals.sqlite3
```

## Benchmark Commands

Local benchmark:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --run-tests --apply-sandbox --save-run
```

SWE-style evaluation:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --work-dir .repopilot\swe_runs --max-cases 11 --write-json .repopilot\reports\public_eval_latest.json --write-markdown .repopilot\reports\public_eval_latest.md
```

Official/public instance pathway:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --dataset-path path\to\official_swe_bench.jsonl --dataset-name princeton-nlp/SWE-bench_Verified --dataset-split test --instance-id django__django-16527 --write-preds .repopilot\reports\all_preds.jsonl --write-json .repopilot\reports\official_eval_summary.json
```

Official dataset download/export example:

```powershell
.\.venv\Scripts\python.exe -c "from datasets import load_dataset; import json, pathlib; ds=load_dataset('princeton-nlp/SWE-bench_Verified', split='test'); target=pathlib.Path('.repopilot/official_datasets/swe_bench_verified_test_500.jsonl'); target.parent.mkdir(parents=True, exist_ok=True); f=target.open('w', encoding='utf-8', newline=''); [f.write(json.dumps({k: ds[i][k] for k in ds.column_names}, ensure_ascii=False) + chr(10)) for i in range(len(ds))]; f.close(); print(target)"
```

Network note:

- downloading `SWE-bench_Verified` from Hugging Face requires outbound access to Hugging Face
- running official/public cases against remote repositories also requires outbound access to GitHub for `git clone`
- if GitHub is blocked, RepoPilot can still export predictions and parse official dataset rows locally, but end-to-end public-case execution will stop at repository preparation

## Current Limits

RepoPilot is already a strong engineering agent prototype, but it is still short of the best frontier coding agents in a few places:

- semantic AST rewrite is still candidate-oriented, not yet a full executable rewrite operator
- thread memory exists and persists, but long multi-session planning can still go deeper
- patch synthesis quality is stronger than before, but still not at the level of the best closed commercial agents
- official SWE-bench claims still depend on exact base-commit reproduction

These are active design targets, not hidden weaknesses.

## Repository Goals

RepoPilot is being developed as:

- a serious GitHub-visible coding-agent project
- a strong interview project for AI agent / coding-agent roles
- a testbed for graph retrieval, semantic patching, and continual repair learning

## Related Docs

- [docs/benchmark.md](docs/benchmark.md)

