from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.approval import ApprovalStore


def main() -> None:
    parser = argparse.ArgumentParser(description="List or decide RepoPilot approval gates.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--approve", default="")
    parser.add_argument("--reject", default="")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    store = ApprovalStore(Path(args.repo) / ".repopilot" / "approvals.sqlite3")
    if args.approve:
        store.decide(args.approve, True, args.reason or "approved by operator")
    if args.reject:
        store.decide(args.reject, False, args.reason or "rejected by operator")
    print(json.dumps({"pending": store.list_pending()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
