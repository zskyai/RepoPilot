# Architecture

## Overview

RepoPilot is a Coding Agent that combines:

- code retrieval
- hybrid embedding + rerank retrieval
- real OpenAI-compatible LLM agents
- patch generation
- patch validation
- sandbox apply
- test execution
- repair loop
- GitHub PR / CI integration
- evaluation and PR readiness

## Agent Roles

Tool agents:

- RepoIndexer
- CodeRetriever
- TestRunner

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

## Repair Loop

RepoPilot now performs a real patch repair cycle in sandbox:

1. generate candidate patch
2. run `git apply --check`
3. apply patch in sandbox copy
4. run sandbox validation
5. feed failure logs into the next patch round

This keeps the original repository clean while producing evidence-backed repair attempts.

## Verification Layers

RepoPilot uses multiple verification layers:

1. `git apply --check`
2. sandbox `git apply`
3. `pytest`
4. smoke check
5. rubric score
6. LLM Judge score

The design principle is:

> tool facts first, LLM judgment second

That means passing `git apply --check` and test execution are treated as hard evidence.
