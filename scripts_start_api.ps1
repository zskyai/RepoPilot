$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = (Get-Location).Path
python -m uvicorn app.api.server:app --reload --port 8000

