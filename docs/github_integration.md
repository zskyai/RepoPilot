# GitHub Integration

RepoPilot can connect to GitHub through either the `gh` CLI or a `GITHUB_TOKEN` in `.env`.

Supported workflow actions:

- create a pull request from the current branch
- fetch PR CI/check-run status
- write a validation comment back to the PR

Recommended local smoke command:

```powershell
.\.venv\Scripts\python.exe run_repo_pilot.py --repo . --issue "GitHub integration smoke" --run-tests --apply-sandbox --create-pr --poll-ci --comment-body "RepoPilot validation passed." --use-llm --require-llm --graph
```
