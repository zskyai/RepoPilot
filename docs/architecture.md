# Architecture

## Overview

RepoPilot is a Coding Agent that combines:

- code retrieval
- Tree-sitter code graph parsing
- Qdrant-backed hybrid embedding + rerank retrieval
- real OpenAI-compatible LLM agents
- patch generation
- patch validation
- sandbox apply
- test execution
- repair loop
- GitHub PR / CI integration
- CI feedback repair context
- long-term repair memory
- OpenTelemetry-compatible tracing
- evaluation and PR readiness

## Agent Roles

Tool agents:

- RepoIndexer
- CodeRetriever
- CodeGraphBuilder
- QdrantVectorStore
- TestRunner
- MemoryStore
- GitHubOps

LLM agents:

- RootCauseAgent
- PatchPlannerAgent
- PatchSuggestionAgent
- RepairAdvisorAgent
- RepoJudgeAgent

## Runtime

Current runtime prefers official LangGraph when available and falls back to the local StateGraph runtime otherwise:

```text
plan -> act -> verify -> repair -> judge -> pr_ready
```

The graph is no longer just a migration placeholder. It is the production execution path used by `run_repo_pilot.py --graph` and `run_benchmark.py`.

## Code Knowledge Graph

RepoPilot builds a source-code graph with real Tree-sitter parsers from grammar wheels:

- `tree-sitter-python`
- `tree-sitter-javascript`
- `tree-sitter-typescript`

The graph extracts symbols, calls, imports, language metadata, and file hashes. Retrieval uses this graph for structural reranking, so the agent can prefer chunks that match function/class names, call targets, imports, and likely impact paths instead of only matching keywords.

## Vector Retrieval

RepoPilot now uses local Qdrant as the dense vector backend when available:

```text
.repopilot/qdrant/<collection>
```

The retrieval score combines:

- lexical overlap
- dense vector similarity
- Tree-sitter symbol/call/import signals
- path and IDF-style bonuses

If Qdrant cannot be opened because of a local file lock or permission issue, the run falls back to an in-memory dense index and records the fallback reason in evidence metadata.

## Observability

Graph node execution is written to:

```text
.repopilot/traces.sqlite3
```

Each node also emits OpenTelemetry spans through the installed OpenTelemetry API. The API response includes `graph_run_id`, `trace_db_path`, and `persistent_trace` so a run can be audited after execution.

## Long-Term Memory

RepoPilot stores compact repair memories in `.repopilot/memory.sqlite3`.

On each run it can recall semantically similar previous issues and feed them into root-cause analysis. At the end of the run it saves the issue, suspected files, patch checks, evaluation, and GitHub CI feedback. This turns repeated repository work into accumulated repair evidence instead of isolated one-off prompts.

## Repair Loop

RepoPilot now performs a real patch repair cycle in sandbox:

1. generate candidate patch
2. run `git apply --check`
3. apply patch in sandbox copy
4. run sandbox validation
5. feed failure logs into the next patch round

This keeps the original repository clean while producing evidence-backed repair attempts.

## GitHub CI Feedback

When a PR number is available, RepoPilot can read GitHub check runs, summarize failed/pending checks, collect annotations, and produce repair context for the next agent iteration. It can also write validation comments back to the PR.

## Verification Layers

RepoPilot uses multiple verification layers:

1. `git apply --check`
2. sandbox `git apply`
3. `pytest`
4. smoke check
5. rubric score
6. LLM Judge score
7. GitHub CI checks

The design principle is:

> tool facts first, LLM judgment second

That means passing `git apply --check` and test execution are treated as hard evidence.
