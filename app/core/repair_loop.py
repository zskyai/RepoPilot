from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FailureSignal:
    source: str
    kind: str
    message: str
    path: str = ""
    line: int | None = None
    command: str = ""
    raw: str = ""


@dataclass
class PatchCandidateScore:
    title: str
    patch_file: str
    passed: bool
    touched_files: list[str] = field(default_factory=list)
    changed_lines: int = 0
    failure_penalty: int = 0
    score: float = 0.0
    reason: str = ""


class FailureParser:
    def parse_test_run(self, run: dict[str, Any]) -> list[FailureSignal]:
        text = "\n".join([run.get("stdout", ""), run.get("stderr", "")])
        signals: list[FailureSignal] = []
        for match in re.finditer(r'File "([^"]+)", line (\d+)', text):
            signals.append(
                FailureSignal(
                    source="pytest",
                    kind="traceback",
                    message=self._nearby_line(text, match.start()),
                    path=match.group(1),
                    line=int(match.group(2)),
                    command=run.get("command", ""),
                    raw=text[-4000:],
                )
            )
        failed = re.findall(r"FAILED\s+([^\s]+)", text)
        for item in failed:
            path, _, line = item.partition("::")
            signals.append(
                FailureSignal(
                    source="pytest",
                    kind="failed_test",
                    message=item,
                    path=path,
                    command=run.get("command", ""),
                    raw=text[-4000:],
                )
            )
        if "ModuleNotFoundError" in text:
            signals.append(
                FailureSignal(
                    source="pytest",
                    kind="module_not_found",
                    message=self._extract_line(text, "ModuleNotFoundError"),
                    command=run.get("command", ""),
                    raw=text[-4000:],
                )
            )
        return signals or [
            FailureSignal(
                source="pytest",
                kind="unknown_test_failure",
                message=(text.strip() or "Test command failed without output.")[-1000:],
                command=run.get("command", ""),
                raw=text[-4000:],
            )
        ]

    def parse_git_apply(self, check: dict[str, Any]) -> list[FailureSignal]:
        text = check.get("stderr", "") or check.get("stdout", "")
        signals: list[FailureSignal] = []
        for pattern in [
            r"error: patch failed: ([^:]+):(\d+)",
            r"error: ([^:]+): already exists in working directory",
            r"error: ([^:]+): No such file or directory",
        ]:
            for match in re.finditer(pattern, text):
                line = int(match.group(2)) if len(match.groups()) > 1 and match.group(2).isdigit() else None
                signals.append(
                    FailureSignal(
                        source="git_apply",
                        kind="hunk_failure",
                        message=match.group(0),
                        path=match.group(1),
                        line=line,
                        command="git apply --check",
                        raw=text[-4000:],
                    )
                )
        return signals or [
            FailureSignal(
                source="git_apply",
                kind="patch_apply_failed",
                message=(text.strip() or "git apply failed without stderr.")[-1000:],
                command="git apply --check",
                raw=text[-4000:],
            )
        ]

    def parse_ci_feedback(self, feedback: dict[str, Any]) -> list[FailureSignal]:
        signals: list[FailureSignal] = []
        for ann in feedback.get("annotations", []) or []:
            signals.append(
                FailureSignal(
                    source="github_ci",
                    kind=ann.get("annotation_level") or "annotation",
                    message=ann.get("message") or ann.get("raw_details") or "",
                    path=ann.get("path") or "",
                    line=ann.get("start_line"),
                    raw=str(ann)[:4000],
                )
            )
        for item in feedback.get("failed", []) or []:
            signals.append(
                FailureSignal(
                    source="github_ci",
                    kind="failed_check",
                    message=f"{item.get('name')} conclusion={item.get('conclusion')}",
                    raw=str(item)[:4000],
                )
            )
        return signals

    def _extract_line(self, text: str, marker: str) -> str:
        for line in text.splitlines():
            if marker in line:
                return line.strip()
        return marker

    def _nearby_line(self, text: str, offset: int) -> str:
        start = max(0, text.rfind("\n", 0, offset - 1))
        end = text.find("\n", offset)
        return text[start:end if end >= 0 else len(text)].strip()


class PatchSelector:
    def choose(self, patch_checks: list[dict[str, Any]], sandbox_runs: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = [self.score(item, sandbox_runs) for item in patch_checks]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return {
            "selected": candidates[0].__dict__ if candidates else None,
            "candidates": [item.__dict__ for item in candidates],
        }

    def score(self, patch_check: dict[str, Any], sandbox_runs: list[dict[str, Any]]) -> PatchCandidateScore:
        patch_file = patch_check.get("patch_file", "")
        related_runs = [item for item in sandbox_runs if item.get("patch_file") == patch_file]
        changed_lines = self._changed_lines(patch_file)
        failures = sum(1 for item in related_runs if not item.get("passed"))
        passed = bool(patch_check.get("passed")) and (not related_runs or all(item.get("passed") for item in related_runs))
        score = 0.0
        score += 10.0 if patch_check.get("passed") else -5.0
        score += 20.0 if passed else 0.0
        score -= min(10.0, changed_lines * 0.05)
        score -= failures * 3.0
        return PatchCandidateScore(
            title=patch_check.get("title", ""),
            patch_file=patch_file,
            passed=passed,
            touched_files=patch_check.get("touched_files", []),
            changed_lines=changed_lines,
            failure_penalty=failures,
            score=round(score, 3),
            reason="prefer passing patch with the smallest verified diff",
        )

    def _changed_lines(self, patch_file: str) -> int:
        try:
            lines = open(patch_file, encoding="utf-8").read().splitlines()
        except OSError:
            return 0
        return sum(1 for line in lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
