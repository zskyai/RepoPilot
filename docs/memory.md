# Long-Term Memory

RepoPilot includes persistent repair memory for repeated repository work.

The goal is not to store chat history. The goal is to reuse verified engineering evidence:

- what issue was investigated
- which files were suspected
- what root cause was found
- which patches were proposed
- whether validation passed
- what GitHub CI reported
- what repair context should be reused next time

## Storage

Memories are stored locally in:

```text
.repopilot/memory.sqlite3
```

The database is created automatically and should not be committed. Each row contains a compact JSON payload and an embedding vector.

## Recall Flow

At the beginning of a run, RepoPilot embeds the current issue and searches recent memories. The top matches are injected into the root-cause stage as additional evidence.

```text
current issue -> embedding -> memory search -> top matches -> root-cause prompt
```

Repo-specific matches receive a small score boost, so repeated work in the same repository is preferred.

## Save Flow

At the end of a run, RepoPilot saves a compact memory containing:

- task id
- repository path
- issue
- evaluation result
- root-cause hypothesis
- suspected files
- change plan
- patch suggestions
- patch checks
- GitHub and CI feedback

This makes successful and failed attempts useful. Failed attempts are especially valuable because they help the next run avoid repeating the same invalid patch.

## CLI Flags

Memory is enabled by default.

Disable recall:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --repo . --issue "..." --no-memory
```

Disable saving:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --repo . --issue "..." --no-save-memory
```

## API Fields

The FastAPI request model supports:

```json
{
  "use_memory": true,
  "save_memory": true
}
```

The response includes:

```json
{
  "analysis": {
    "memory_hits": [],
    "saved_memory_id": 1
  }
}
```

## Current Limits

- Memory is local SQLite, not a shared vector database.
- The fallback embedding is deterministic hash embedding when remote embedding is unavailable.
- Memory recall is used as evidence, not as an automatic truth source.

These choices keep the feature reliable on a local developer machine while leaving a clear upgrade path to pgvector, Milvus, Qdrant, or Elasticsearch/OpenSearch hybrid search.
