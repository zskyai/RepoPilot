from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
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

    def pr_info(self, pr_number: int) -> dict[str, Any]:
        if not self.is_authenticated():
            return {"ok": False, "error": "gh is unavailable or not authenticated."}
        slug = self.repo_slug()
        if not slug:
            return {"ok": False, "error": "Could not infer GitHub repo slug from origin remote."}
        if self.command_exists("gh") and not self.github_token:
            completed = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--json", "number,headRefName,headRefOid,baseRefName,url,state"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            if completed.returncode == 0:
                try:
                    data = json.loads(completed.stdout or "{}")
                except json.JSONDecodeError:
                    data = {}
                return {
                    "ok": True,
                    "number": data.get("number"),
                    "head_ref": data.get("headRefName"),
                    "head_sha": data.get("headRefOid"),
                    "base_ref": data.get("baseRefName"),
                    "url": data.get("url"),
                    "state": data.get("state"),
                }
        response = self._api_request("GET", f"/repos/{slug}/pulls/{pr_number}")
        if not response.get("ok"):
            return response
        data = response["data"]
        head = data.get("head") or {}
        base = data.get("base") or {}
        return {
            "ok": True,
            "number": data.get("number"),
            "head_ref": head.get("ref"),
            "head_sha": head.get("sha"),
            "base_ref": base.get("ref"),
            "url": data.get("html_url"),
            "state": data.get("state"),
        }

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

    def sync_patch_to_branch(self, branch: str, patch_file: str | Path, commit_message: str) -> dict[str, Any]:
        slug = self.repo_slug()
        if not self.github_token:
            return {"ok": False, "error": "GITHUB_TOKEN is required for patch sync."}
        if not slug:
            return {"ok": False, "error": "Could not infer GitHub repo slug from origin remote."}
        patch_path = Path(patch_file)
        if not patch_path.is_absolute():
            patch_path = (self.repo / patch_path).resolve()
        if not patch_path.exists():
            return {"ok": False, "error": f"Patch file not found: {patch_path}"}
        targets = self._patch_targets(patch_path.read_text(encoding="utf-8", errors="ignore"))
        if not targets:
            return {"ok": False, "error": "No file targets found in patch."}

        with tempfile.TemporaryDirectory(prefix="repopilot_sync_") as temp_dir:
            temp_repo = Path(temp_dir) / self.repo.name
            shutil.copytree(
                self.repo,
                temp_repo,
                ignore=shutil.ignore_patterns(".git", ".venv", ".repopilot", "__pycache__", ".pytest_cache", "node_modules"),
            )
            completed = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=temp_repo,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            if completed.returncode != 0:
                return {"ok": False, "error": f"git apply failed in temp repo: {completed.stderr[-1000:]}"}

            uploaded: list[str] = []
            for relative_path in targets:
                source = temp_repo / relative_path
                if not source.exists():
                    return {"ok": False, "error": f"Patched file missing after apply: {relative_path}"}
                upload = self._api_put_file(
                    slug=slug,
                    branch=branch,
                    path=relative_path.as_posix(),
                    content_bytes=source.read_bytes(),
                    message=commit_message,
                )
                if not upload.get("ok"):
                    return upload
                uploaded.append(relative_path.as_posix())
        return {"ok": True, "branch": branch, "files": uploaded, "count": len(uploaded)}

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

    def _api_put_file(
        self,
        *,
        slug: str,
        branch: str,
        path: str,
        content_bytes: bytes,
        message: str,
    ) -> dict[str, Any]:
        existing = self._api_request("GET", f"/repos/{slug}/contents/{path}?ref={branch}")
        payload = {
            "message": message,
            "content": base64.b64encode(content_bytes).decode("ascii"),
            "branch": branch,
        }
        if existing.get("ok"):
            sha = (existing.get("data") or {}).get("sha")
            if sha:
                payload["sha"] = sha
        response = self._api_request("PUT", f"/repos/{slug}/contents/{path}", payload)
        if not response.get("ok"):
            return {
                "ok": False,
                "error": f"Failed to upload {path} to {branch}: {response.get('error', '')}",
            }
        return {"ok": True, "path": path, "branch": branch}

    def _patch_targets(self, diff_text: str) -> list[Path]:
        targets: list[Path] = []
        seen: set[str] = set()
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                raw = line[6:].strip()
            elif line.startswith("+++ "):
                raw = line[4:].strip()
            else:
                continue
            if raw == "/dev/null":
                continue
            normalized = raw[2:] if raw.startswith("b/") else raw
            normalized = normalized.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            targets.append(Path(normalized))
        return targets

    def build_repair_comment(
        self,
        *,
        ci_feedback: dict[str, Any] | None,
        failure_signals: list[dict[str, Any]] | None,
        selected_patch: dict[str, Any] | None,
    ) -> str:
        lines = ["RepoPilot repair update", ""]
        if ci_feedback:
            lines.append(f"- ci_passed: {ci_feedback.get('passed')}")
            lines.append(f"- ci_total_checks: {ci_feedback.get('total')}")
            for item in (ci_feedback.get("failed") or [])[:5]:
                lines.append(
                    f"- failed_check: {item.get('name')} conclusion={item.get('conclusion')} url={item.get('details_url')}"
                )
        if selected_patch and selected_patch.get("selected"):
            chosen = selected_patch["selected"]
            lines.extend(
                [
                    "",
                    "Selected patch candidate:",
                    f"- title: {chosen.get('title')}",
                    f"- score: {chosen.get('score')}",
                    f"- changed_lines: {chosen.get('changed_lines')}",
                    f"- touched_files: {', '.join(chosen.get('touched_files', []))}",
                ]
            )
        if failure_signals:
            lines.append("")
            lines.append("Failure signals:")
            for item in failure_signals[:8]:
                lines.append(
                    f"- {item.get('source')}:{item.get('kind')} {item.get('path','')}:{item.get('line') or ''} {str(item.get('message') or '')[:240]}"
                )
        return "\n".join(lines)
