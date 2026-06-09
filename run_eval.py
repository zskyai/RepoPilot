from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.workflow import EnterpriseAgentWorkflow
from app.eval.virtual_user import DEFAULT_VIRTUAL_USERS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run virtual-user regression evaluation.")
    parser.add_argument(
        "--topic",
        default="企业知识库 RAG Agent 和自动化评测平台",
        help="Evaluation topic.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    workflow = EnterpriseAgentWorkflow(root / "data" / "knowledge_base")
    results = []
    for user in DEFAULT_VIRTUAL_USERS:
        task = workflow.run(user.build_query(args.topic), user_type=user.name)
        results.append(
            {
                "virtual_user": user.name,
                "overall": task.evaluation["overall"],
                "passed": task.evaluation["passed"],
                "badcase_type": task.optimization["badcase_type"],
                "suggestions": task.optimization["suggestions"],
                "trace_events": len(task.trace),
            }
        )

    summary = {
        "topic": args.topic,
        "case_count": len(results),
        "average_score": round(
            sum(item["overall"] for item in results) / max(1, len(results)), 3
        ),
        "pass_rate": round(
            sum(1 for item in results if item["passed"]) / max(1, len(results)), 3
        ),
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("# 虚拟用户回归评测")
        print(f"主题：{summary['topic']}")
        print(f"用例数：{summary['case_count']}")
        print(f"平均分：{summary['average_score']}")
        print(f"通过率：{summary['pass_rate']}")
        for item in results:
            print(
                f"- {item['virtual_user']}: score={item['overall']}, "
                f"passed={item['passed']}, badcase={item['badcase_type']}"
            )


if __name__ == "__main__":
    main()

