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
    coordination_score: float = 0.0
    sandbox_pass_count: int = 0
    score: float = 0.0
    reason: str = ""
    target_fit: float = 0.0
    implementation_bias: float = 0.0
    graph_bonus: float = 0.0
    policy_bonus: float = 0.0
    archetype: str = ""
    adversarial_penalty: float = 0.0


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
        suspected_files: list[str] | None = None,
        graph_priority: dict[str, float] | None = None,
        policy_priors: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        candidates = [
            self.score(
                item,
                sandbox_runs,
                failure_signals=failure_signals,
                suspected_files=suspected_files,
                graph_priority=graph_priority,
                policy_priors=policy_priors,
            )
            for item in patch_checks
        ]
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
        suspected_files: list[str] | None = None,
        graph_priority: dict[str, float] | None = None,
        policy_priors: dict[str, dict[str, float]] | None = None,
    ) -> list[dict[str, Any]]:
        ranked = self.choose(
            patch_checks,
            sandbox_runs,
            failure_signals=failure_signals,
            suspected_files=suspected_files,
            graph_priority=graph_priority,
            policy_priors=policy_priors,
        )
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
        suspected_files: list[str] | None = None,
        graph_priority: dict[str, float] | None = None,
        policy_priors: dict[str, dict[str, float]] | None = None,
    ) -> PatchCandidateScore:
        patch_file = patch_check.get("patch_file", "")
        related_runs = [item for item in sandbox_runs if item.get("patch_file") == patch_file]
        changed_lines = self._changed_lines(patch_file)
        failures = sum(1 for item in related_runs if not item.get("passed"))
        sandbox_pass_count = sum(1 for item in related_runs if item.get("passed"))
        touched_files = patch_check.get("touched_files", [])
        coordination = patch_check.get("coordination_assessment") or {}
        coordination_score = float(coordination.get("score", 0.0) or 0.0)
        overlap_bonus = self._failure_overlap_bonus(touched_files, failure_signals)
        target_fit = self._target_fit_bonus(touched_files, suspected_files)
        implementation_bias = self._implementation_bias(touched_files)
        archetype = self._patch_archetype(touched_files)
        graph_bonus = self._graph_bonus(touched_files, graph_priority)
        policy_bonus = self._policy_bonus(archetype, policy_priors)
        adversarial_penalty = self._adversarial_penalty(touched_files, coordination)
        touched_penalty = max(0.0, (len(touched_files) - 2) * 1.5)
        hunk_penalty = max(0.0, (self._hunk_count(patch_file) - 1) * 1.25)
        missing_primary_penalty = len(coordination.get("missing_primary_files", []) or []) * 2.5
        missing_test_penalty = len(coordination.get("missing_test_files", []) or []) * 1.5
        closed_loop_bonus = 4.0 if coordination.get("complete") else 0.0
        passed = bool(patch_check.get("passed")) and (not related_runs or all(item.get("passed") for item in related_runs))
        score = 0.0
        score += 10.0 if patch_check.get("passed") else -5.0
        score += 20.0 if passed else 0.0
        score += min(8.0, coordination_score * 8.0)
        score += sandbox_pass_count * 1.5
        score += closed_loop_bonus
        score += target_fit
        score += implementation_bias
        score += graph_bonus
        score += policy_bonus
        score -= adversarial_penalty
        score -= min(10.0, changed_lines * 0.05)
        score -= failures * 3.0
        score += overlap_bonus
        score -= touched_penalty
        score -= hunk_penalty
        score -= missing_primary_penalty
        score -= missing_test_penalty
        return PatchCandidateScore(
            title=patch_check.get("title", ""),
            patch_file=patch_file,
            passed=passed,
            touched_files=touched_files,
            changed_lines=changed_lines,
            failure_penalty=failures,
            coordination_score=coordination_score,
            sandbox_pass_count=sandbox_pass_count,
            score=round(score, 3),
            reason="prefer verified implementation patches that align with localized files, stay small, close the loop, and overlap with failure locations",
            target_fit=round(target_fit, 3),
            implementation_bias=round(implementation_bias, 3),
            graph_bonus=round(graph_bonus, 3),
            policy_bonus=round(policy_bonus, 3),
            archetype=archetype,
            adversarial_penalty=round(adversarial_penalty, 3),
        )

    def _target_fit_bonus(self, touched_files: list[str], suspected_files: list[str] | None) -> float:
        if not touched_files or not suspected_files:
            return 0.0
        normalized_touched = {path.replace("\\", "/") for path in touched_files}
        normalized_suspected = [path.replace("\\", "/") for path in suspected_files if path]
        if not normalized_suspected:
            return 0.0
        direct_hits = sum(1 for path in normalized_suspected[:3] if path in normalized_touched)
        family_hits = sum(
            1
            for path in normalized_suspected[:3]
            if any(touched.startswith(path.rsplit("/", 1)[0] + "/") for touched in normalized_touched if "/" in path)
        )
        return min(8.0, direct_hits * 3.0 + family_hits * 1.0)

    def _implementation_bias(self, touched_files: list[str]) -> float:
        if not touched_files:
            return 0.0
        normalized = [path.replace("\\", "/").lower() for path in touched_files]
        code_files = [path for path in normalized if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"))]
        implementation_files = [
            path
            for path in code_files
            if "/test" not in path and not path.startswith("tests/") and "/docs/" not in path and not path.endswith(".md")
        ]
        test_files = [path for path in normalized if path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py")]
        docs_files = [path for path in normalized if path.endswith(".md") or path.startswith("docs/") or "/docs/" in path]
        bonus = 0.0
        if implementation_files:
            bonus += min(6.0, 4.0 + max(0, len(implementation_files) - 1))
        if test_files and not implementation_files:
            bonus -= 5.0
        if docs_files and not implementation_files:
            bonus -= 4.0
        if not code_files and docs_files:
            bonus -= 2.0
        return bonus

    def _graph_bonus(self, touched_files: list[str], graph_priority: dict[str, float] | None) -> float:
        if not touched_files or not graph_priority:
            return 0.0
        values = [float(graph_priority.get(path.replace("\\", "/"), 0.0)) for path in touched_files]
        if not values:
            return 0.0
        return min(4.0, max(values) * 3.0)

    def _policy_bonus(self, archetype: str, policy_priors: dict[str, dict[str, float]] | None) -> float:
        if not archetype or not policy_priors:
            return 0.0
        row = policy_priors.get(archetype) or {}
        return min(4.0, max(-2.0, float(row.get("ucb_score", 0.0)) * 2.5))

    def _patch_archetype(self, touched_files: list[str]) -> str:
        if not touched_files:
            return "unknown"
        normalized = [path.replace("\\", "/").lower() for path in touched_files]
        implementation = [
            path for path in normalized
            if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"))
            and "/test" not in path and not path.startswith("tests/")
        ]
        tests = [path for path in normalized if path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py")]
        docs = [path for path in normalized if path.endswith(".md") or path.startswith("docs/") or "/docs/" in path]
        if implementation and tests:
            return "code_and_test"
        if len(implementation) > 1:
            return "multi_file_code"
        if implementation:
            return "single_file_code"
        if tests:
            return "test_only"
        if docs:
            return "docs_only"
        return "support_only"

    def _adversarial_penalty(self, touched_files: list[str], coordination: dict[str, Any]) -> float:
        archetype = self._patch_archetype(touched_files)
        penalty = 0.0
        if archetype == "test_only":
            penalty += 3.0
        elif archetype == "docs_only":
            penalty += 2.0
        elif archetype == "support_only":
            penalty += 1.5
        missing_primary = coordination.get("missing_primary_files", []) or []
        missing_test = coordination.get("missing_test_files", []) or []
        if missing_primary:
            penalty += min(3.0, 1.2 * len(missing_primary))
        if missing_test and archetype in {"single_file_code", "multi_file_code"}:
            penalty += 0.8
        return penalty

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
