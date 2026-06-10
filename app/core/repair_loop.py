from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FailureSignal:
    source: str
    kind: str
    message: str
    family: str = ""
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
        for match in re.finditer(r'File [\"\']([^\"\']+)[\"\'], line (\d+)', text):
            signals.append(
                FailureSignal(
                    source="pytest",
                    kind="traceback",
                    message=self._nearby_line(text, match.start()),
                    family=self._family_from_text(text),
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
                    family="behavior",
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
                    family="import",
                    command=run.get("command", ""),
                    raw=text[-4000:],
                )
            )
        return signals or [
            FailureSignal(
                source="pytest",
                kind="unknown_test_failure",
                message=(text.strip() or "Test command failed without output.")[-1000:],
                family=self._family_from_text(text),
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
                        family="patch_apply",
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
                family="patch_apply",
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
                    family=self._family_from_text((ann.get("message") or ann.get("raw_details") or "")),
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
                    family="ci",
                    raw=str(item)[:4000],
                )
            )
        return signals

    def summarize(self, signals: list[FailureSignal]) -> dict[str, Any]:
        if not signals:
            return {
                "primary_family": "unknown",
                "primary_kind": "unknown",
                "strategy": "narrow_scope_and_preserve_behavior",
                "candidate_limit": 3,
                "target_files": [],
                "summary_lines": [],
            }
        family_counts: dict[str, int] = {}
        target_files: list[str] = []
        for item in signals:
            family = item.family or self._family_from_text(item.message)
            family_counts[family] = family_counts.get(family, 0) + 1
            if item.path and item.path not in target_files:
                target_files.append(item.path)
        primary_family = max(family_counts.items(), key=lambda item: item[1])[0]
        primary = next((item for item in signals if (item.family or self._family_from_text(item.message)) == primary_family), signals[0])
        strategy_map = {
            "patch_apply": ("regenerate_smaller_diff", 2),
            "import": ("fix_module_or_path", 2),
            "syntax": ("repair_syntax_first", 2),
            "contract": ("fix_symbol_or_type_contract", 3),
            "behavior": ("minimize_behavior_change", 3),
            "ci": ("follow_ci_annotations", 2),
            "timeout": ("reduce_runtime_or_scope", 2),
            "unknown": ("narrow_scope_and_preserve_behavior", 3),
        }
        strategy, candidate_limit = strategy_map.get(primary_family, ("narrow_scope_and_preserve_behavior", 3))
        summary_lines = [
            f"primary_family={primary_family}",
            f"primary_kind={primary.kind}",
            f"strategy={strategy}",
        ]
        for item in signals[:6]:
            summary_lines.append(
                f"- {item.source}:{item.kind} {item.path}:{item.line or ''} {item.message[:220]}"
            )
        return {
            "primary_family": primary_family,
            "primary_kind": primary.kind,
            "strategy": strategy,
            "candidate_limit": candidate_limit,
            "target_files": target_files[:6],
            "summary_lines": summary_lines,
        }

    def _family_from_text(self, text: str) -> str:
        text = text or ""
        checks = [
            ("patch_apply", ("patch failed", "git apply", "hunk", "No such file or directory")),
            ("import", ("ModuleNotFoundError", "ImportError", "cannot import", "No module named")),
            ("syntax", ("SyntaxError", "IndentationError", "ParseError")),
            ("contract", ("NameError", "AttributeError", "TypeError", "KeyError", "AssertionError")),
            ("timeout", ("timeout", "timed out")),
        ]
        for family, markers in checks:
            if any(marker in text for marker in markers):
                return family
        if "FAILED" in text or "failed" in text:
            return "behavior"
        return "unknown"

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
    def choose(
        self,
        patch_checks: list[dict[str, Any]],
        sandbox_runs: list[dict[str, Any]],
        failure_signals: list[dict[str, Any]] | list[FailureSignal] | None = None,
    ) -> dict[str, Any]:
        candidates = [self.score(item, sandbox_runs, failure_signals=failure_signals) for item in patch_checks]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return {
            "selected": candidates[0].__dict__ if candidates else None,
            "candidates": [item.__dict__ for item in candidates],
        }

    def rank_patch_checks(
        self,
        patch_checks: list[dict[str, Any]],
        sandbox_runs: list[dict[str, Any]],
        failure_signals: list[dict[str, Any]] | list[FailureSignal] | None = None,
    ) -> list[dict[str, Any]]:
        ranked = self.choose(patch_checks, sandbox_runs, failure_signals=failure_signals)
        by_file = {item.get("patch_file", ""): item for item in patch_checks}
        ordered: list[dict[str, Any]] = []
        for candidate in ranked.get("candidates", []):
            patch_file = candidate.get("patch_file", "")
            if patch_file in by_file:
                enriched = dict(by_file[patch_file])
                enriched["ranking"] = candidate
                ordered.append(enriched)
        return ordered

    def score(
        self,
        patch_check: dict[str, Any],
        sandbox_runs: list[dict[str, Any]],
        failure_signals: list[dict[str, Any]] | list[FailureSignal] | None = None,
    ) -> PatchCandidateScore:
        patch_file = patch_check.get("patch_file", "")
        related_runs = [item for item in sandbox_runs if item.get("patch_file") == patch_file]
        changed_lines = self._changed_lines(patch_file)
        failures = sum(1 for item in related_runs if not item.get("passed"))
        touched_files = patch_check.get("touched_files", [])
        overlap_bonus = self._failure_overlap_bonus(touched_files, failure_signals)
        touched_penalty = max(0.0, (len(touched_files) - 2) * 1.5)
        hunk_penalty = max(0.0, (self._hunk_count(patch_file) - 1) * 1.25)
        passed = bool(patch_check.get("passed")) and (not related_runs or all(item.get("passed") for item in related_runs))
        score = 0.0
        score += 10.0 if patch_check.get("passed") else -5.0
        score += 20.0 if passed else 0.0
        score -= min(10.0, changed_lines * 0.05)
        score -= failures * 3.0
        score += overlap_bonus
        score -= touched_penalty
        score -= hunk_penalty
        return PatchCandidateScore(
            title=patch_check.get("title", ""),
            patch_file=patch_file,
            passed=passed,
            touched_files=touched_files,
            changed_lines=changed_lines,
            failure_penalty=failures,
            score=round(score, 3),
            reason="prefer verified patches that stay small and overlap with failure locations",
        )

    def _changed_lines(self, patch_file: str) -> int:
        try:
            lines = open(patch_file, encoding="utf-8").read().splitlines()
        except OSError:
            return 0
        return sum(1 for line in lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))

    def _failure_overlap_bonus(
        self,
        touched_files: list[str],
        failure_signals: list[dict[str, Any]] | list[FailureSignal] | None,
    ) -> float:
        if not touched_files or not failure_signals:
            return 0.0
        signal_paths = set()
        for item in failure_signals:
            path = item.path if isinstance(item, FailureSignal) else item.get("path", "")
            if path:
                signal_paths.add(path.replace("\\", "/"))
        if not signal_paths:
            return 0.0
        overlaps = sum(1 for path in touched_files if path.replace("\\", "/") in signal_paths)
        return min(6.0, overlaps * 3.0)

    def _hunk_count(self, patch_file: str) -> int:
        try:
            lines = open(patch_file, encoding="utf-8").read().splitlines()
        except OSError:
            return 0
        return sum(1 for line in lines if line.startswith("@@"))
