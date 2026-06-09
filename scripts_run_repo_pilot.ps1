$env:PYTHONIOENCODING = "utf-8"
python run_repo_pilot.py --repo . --issue "API 返回 JSON schema 字段不稳定，需要定位接口和模型定义" --run-tests --apply-sandbox --save-run --use-llm --require-llm --graph
