from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.workflow import EnterpriseAgentWorkflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run enterprise multi-agent research workflow.")
    parser.add_argument("query", help="User question or business research task.")
    parser.add_argument("--user-type", default="enterprise_user")
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    workflow = EnterpriseAgentWorkflow(root / "data" / "knowledge_base")
    task = workflow.run(args.query, args.user_type)
    if args.json:
        print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(task.report)
        print("\n## 自动评测")
        print(json.dumps(task.evaluation, ensure_ascii=False, indent=2))
        print("\n## 优化建议")
        print(json.dumps(task.optimization, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

