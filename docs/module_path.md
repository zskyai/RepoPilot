# Module Path Troubleshooting

- Run commands from the repository root.
- Prefer `python -m uvicorn app.api.server:app --reload --port 8000`.
- On Windows PowerShell, set `PYTHONPATH` to the current directory before startup.
- Add a smoke test that imports `app` to catch regressions early.
