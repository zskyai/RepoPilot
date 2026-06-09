from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.core.llm import load_dotenv


class GitHubOps:
    def __init__(self, repo: str | Path) -> None:
        self.repo = Path(repo).resolve()
        load_dotenv()
        self.github_token = os.getenv("GITHUB_TOKEN", "")

    def command_exists(self, command: str) -> bool:
        try:
            completed = subprocess.run(
                [command, "--version"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            return completed.returncode == 0
        except Exception:
            return False

    def is_authenticated(self) -> bool:
        if self.command_exists("gh"):
            try:
                completed = subprocess.run(
                    ["gh", "auth", "status"],
                    cwd=self.repo,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    shell=False,
                )
                if completed.returncode == 0:
                    return True
            except Exception:
                pass
        return bool(self.github_token and self.repo_slug())

    def current_branch(self) -> str:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except Exception:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    def current_commit(self) -> str:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except Exception:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    def create_pr(self, title: str, body: str, base: str = "main", head: str | None = None) -> dict[str, Any]:
        if not self.is_authenticated():
            return {"ok": False, "error": "gh is unavailable or not authenticated."}
        branch = head or self.current_branch()
        if not self.command_exists("gh") and self.github_token:
            return self._api_create_pr(title=title, body=body, base=base, head=branch)
        completed = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base,
                "--head",
                branch,
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=90,
            shell=False,
        )
        if completed.returncode != 0:
            return {"ok": False, "error": completed.stderr[-1000:]}
        view = subprocess.run(
            ["gh", "pr", "view", "--head", branch, "--json", "number,url,state"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        if view.returncode != 0:
            return {"ok": True, "stdout": completed.stdout.strip()}
        try:
            payload = json.loads(view.stdout or "{}")
        except json.JSONDecodeError:
            payload = {"raw": view.stdout.strip()}
        payload["ok"] = True
        return payload

    def pr_checks(self, pr_number: int) -> dict[str, Any]:
        if not self.is_authenticated():
            return {"ok": False, "error": "gh is unavailable or not authenticated."}
        if not self.command_exists("gh") and self.github_token:
            return self._api_pr_checks(pr_number)
        completed = subprocess.run(
            ["gh", "pr", "checks", str(pr_number), "--json", "name,state,link,bucket"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
        if completed.returncode != 0:
            return {"ok": False, "error": completed.stderr[-1000:]}
        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError:
            payload = {"raw": completed.stdout.strip()}
        return {"ok": True, "checks": payload}

    def ci_feedback(self, pr_number: int) -> dict[str, Any]:
        checks = self.pr_checks(pr_number)
        if not checks.get("ok"):
            return checks
        check_runs = checks.get("checks") or []
        failed = [
            item
            for item in check_runs
            if item.get("conclusion") not in (None, "success", "skipped", "neutral")
        ]
        pending = [item for item in check_runs if item.get("status") != "completed"]
        annotations: list[dict[str, Any]] = []
        for item in failed[:5]:
            annotations.extend(self.check_annotations(int(item.get("id") or 0)).get("annotations", [])[:10])
        summary = {
            "ok": True,
            "passed": bool(check_runs) and not failed and not pending,
            "total": len(check_runs),
            "failed": [
                {
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "conclusion": item.get("conclusion"),
                    "details_url": item.get("details_url") or item.get("html_url"),
                    "started_at": item.get("started_at"),
                    "completed_at": item.get("completed_at"),
                }
                for item in failed
            ],
            "pending": [
                {
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "details_url": item.get("details_url") or item.get("html_url"),
                }
                for item in pending
            ],
            "annotations": annotations,
        }
        summary["repair_context"] = self.format_repair_context(summary)
        return summary

    def check_annotations(self, check_run_id: int) -> dict[str, Any]:
        if not check_run_id:
            return {"ok": False, "annotations": [], "error": "missing check_run_id"}
        slug = self.repo_slug()
        if not slug:
            return {"ok": False, "annotations": [], "error": "Could not infer GitHub repo slug from origin remote."}
        if self.command_exists("gh") and self.is_authenticated():
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"/repos/{slug}/check-runs/{check_run_id}/annotations",
                ],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            if completed.returncode != 0:
                return {"ok": False, "annotations": [], "error": completed.stderr[-1000:]}
            try:
                return {"ok": True, "annotations": json.loads(completed.stdout or "[]")}
            except json.JSONDecodeError:
                return {"ok": False, "annotations": [], "error": completed.stdout[-1000:]}
        response = self._api_request("GET", f"/repos/{slug}/check-runs/{check_run_id}/annotations")
        if not response.get("ok"):
            return {"ok": False, "annotations": [], "error": response.get("error", "")}
        return {"ok": True, "annotations": response.get("data") or []}

    def format_repair_context(self, feedback: dict[str, Any]) -> str:
        if feedback.get("passed"):
            return "CI passed. No repair needed."
        lines = ["CI feedback for repair:"]
        for item in feedback.get("failed", []):
            lines.append(
                f"- FAILED {item.get('name')} conclusion={item.get('conclusion')} url={item.get('details_url')}"
            )
        for item in feedback.get("pending", []):
            lines.append(f"- PENDING {item.get('name')} status={item.get('status')}")
        for ann in feedback.get("annotations", [])[:20]:
            path = ann.get("path") or ann.get("annotation_level") or "unknown"
            message = ann.get("message") or ann.get("raw_details") or ""
            lines.append(f"- ANNOTATION {path}:{ann.get('start_line')} {message[:500]}")
        return "\n".join(lines)

    def comment_on_pr(self, pr_number: int, body: str) -> dict[str, Any]:
        if not self.is_authenticated():
            return {"ok": False, "error": "gh is unavailable or not authenticated."}
        if not self.command_exists("gh") and self.github_token:
            return self._api_comment_on_pr(pr_number, body)
        completed = subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
        if completed.returncode != 0:
            return {"ok": False, "error": completed.stderr[-1000:]}
        return {"ok": True, "stdout": completed.stdout.strip()}

    def repo_slug(self) -> str:
        try:
            completed = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except Exception:
            return ""
        if completed.returncode != 0:
            return ""
        remote = completed.stdout.strip()
        match = re.search(r"github\.com[:/](?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?$", remote)
        return match.group("slug") if match else ""

    def _api_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

    def _api_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            data=data,
            headers=self._api_headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return {"ok": True, "data": json.loads(response.read().decode("utf-8"))}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": exc.read().decode("utf-8", errors="ignore")[-1000:]}
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}

    def _api_create_pr(self, title: str, body: str, base: str, head: str) -> dict[str, Any]:
        slug = self.repo_slug()
        if not slug:
            return {"ok": False, "error": "Could not infer GitHub repo slug from origin remote."}
        response = self._api_request(
            "POST",
            f"/repos/{slug}/pulls",
            {"title": title, "body": body, "base": base, "head": head},
        )
        if not response.get("ok"):
            return response
        data = response["data"]
        return {"ok": True, "number": data.get("number"), "url": data.get("html_url"), "state": data.get("state")}

    def _api_pr_checks(self, pr_number: int) -> dict[str, Any]:
        slug = self.repo_slug()
        if not slug:
            return {"ok": False, "error": "Could not infer GitHub repo slug from origin remote."}
        pr = self._api_request("GET", f"/repos/{slug}/pulls/{pr_number}")
        if not pr.get("ok"):
            return pr
        sha = (pr["data"].get("head") or {}).get("sha")
        if not sha:
            return {"ok": False, "error": "Could not resolve PR head SHA."}
        checks = self._api_request("GET", f"/repos/{slug}/commits/{sha}/check-runs")
        if not checks.get("ok"):
            return checks
        return {"ok": True, "checks": checks["data"].get("check_runs", [])}

    def _api_comment_on_pr(self, pr_number: int, body: str) -> dict[str, Any]:
        slug = self.repo_slug()
        if not slug:
            return {"ok": False, "error": "Could not infer GitHub repo slug from origin remote."}
        response = self._api_request(
            "POST",
            f"/repos/{slug}/issues/{pr_number}/comments",
            {"body": body},
        )
        if not response.get("ok"):
            return response
        data = response["data"]
        return {"ok": True, "url": data.get("html_url"), "id": data.get("id")}
