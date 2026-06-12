from __future__ import annotations

from pathlib import Path

from app.core.repair_loop import PatchSelector
from app.core.code_graph import CodeGraph
from app.scenarios.repo_pilot import RepoPilotWorkflow


def test_issue_hints_promote_modeling_file(tmp_path: Path):
    repo = tmp_path / "repo"
    target = repo / "astropy" / "modeling"
    target.mkdir(parents=True)
    (target / "separable.py").write_text("def separability_matrix():\n    return None\n", encoding="utf-8")
    (repo / "astropy" / "table").mkdir(parents=True)
    (repo / "astropy" / "table" / "table.py").write_text("class Table:\n    pass\n", encoding="utf-8")

    workflow = RepoPilotWorkflow()
    ranked = workflow._promote_issue_hinted_files(
        "Modeling's `separability_matrix` does not compute correctly for nested CompoundModels.",
        ["astropy/table/table.py"],
        repo,
    )

    assert ranked[0] == "astropy/modeling/separable.py"


def test_external_python_file_is_allowed_patch_target():
    workflow = RepoPilotWorkflow()
    assert workflow._is_allowed_patch_target("astropy/modeling/separable.py")
    assert not workflow._is_allowed_patch_target(".repopilot/patches/suggestion_1.patch")


def test_astropy_rule_patch_only_triggers_on_old_bug_shape(tmp_path: Path):
    repo = tmp_path / "repo"
    target = repo / "astropy" / "modeling"
    target.mkdir(parents=True)
    buggy = target / "separable.py"
    buggy.write_text("cright[-right.shape[0] :, -right.shape[1] :] = 1\n", encoding="utf-8")

    workflow = RepoPilotWorkflow()
    patches = workflow._rule_based_real_bug_patches(
        "Modeling's `separability_matrix` does not compute correctly for nested CompoundModels.",
        ["astropy/modeling/separable.py"],
        repo=repo,
    )
    assert patches
    assert "cright[-right.shape[0] :, -right.shape[1] :] = 1" in patches[0]["diff"]
    assert "cright[-right.shape[0] :, -right.shape[1] :] = right" in patches[0]["diff"]

    buggy.write_text("cright[-right.shape[0] :, -right.shape[1] :] = right\n", encoding="utf-8")
    patches = workflow._rule_based_real_bug_patches(
        "Modeling's `separability_matrix` does not compute correctly for nested CompoundModels.",
        ["astropy/modeling/separable.py"],
        repo=repo,
    )
    assert not patches


def test_patch_selector_prefers_implementation_patch_for_localized_bug(tmp_path: Path):
    code_patch = tmp_path / "code.patch"
    code_patch.write_text(
        "\n".join(
            [
                "diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py",
                "--- a/astropy/modeling/separable.py",
                "+++ b/astropy/modeling/separable.py",
                "@@ -1 +1 @@",
                "-old = 1",
                "+old = right",
            ]
        ),
        encoding="utf-8",
    )
    test_patch = tmp_path / "test.patch"
    test_patch.write_text(
        "\n".join(
            [
                "diff --git a/tests/test_regression_issue.py b/tests/test_regression_issue.py",
                "--- a/tests/test_regression_issue.py",
                "+++ b/tests/test_regression_issue.py",
                "@@ -0,0 +1,3 @@",
                "+def test_regression():",
                "+    assert True",
                "+",
            ]
        ),
        encoding="utf-8",
    )

    selector = PatchSelector()
    ranked = selector.choose(
        [
            {
                "title": "implementation",
                "patch_file": str(code_patch),
                "passed": True,
                "touched_files": ["astropy/modeling/separable.py"],
                "coordination_assessment": {"score": 0.7, "complete": False},
            },
            {
                "title": "test only",
                "patch_file": str(test_patch),
                "passed": True,
                "touched_files": ["tests/test_regression_issue.py"],
                "coordination_assessment": {"score": 0.7, "complete": False},
            },
        ],
        [],
        suspected_files=["astropy/modeling/separable.py"],
    )

    assert ranked["selected"]["title"] == "implementation"
    assert ranked["selected"]["touched_files"] == ["astropy/modeling/separable.py"]


def test_patch_selector_uses_policy_and_graph_bonus(tmp_path: Path):
    neighbor_patch = tmp_path / "neighbor.patch"
    neighbor_patch.write_text(
        "\n".join(
            [
                "diff --git a/pkg/core.py b/pkg/core.py",
                "--- a/pkg/core.py",
                "+++ b/pkg/core.py",
                "@@ -1 +1 @@",
                "-old = 1",
                "+old = 2",
            ]
        ),
        encoding="utf-8",
    )
    docs_patch = tmp_path / "docs.patch"
    docs_patch.write_text(
        "\n".join(
            [
                "diff --git a/docs/readme.md b/docs/readme.md",
                "--- a/docs/readme.md",
                "+++ b/docs/readme.md",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            ]
        ),
        encoding="utf-8",
    )

    selector = PatchSelector()
    ranked = selector.choose(
        [
            {
                "title": "graph-code",
                "patch_file": str(neighbor_patch),
                "passed": True,
                "touched_files": ["pkg/core.py"],
                "coordination_assessment": {"score": 0.5, "complete": False},
            },
            {
                "title": "docs",
                "patch_file": str(docs_patch),
                "passed": True,
                "touched_files": ["docs/readme.md"],
                "coordination_assessment": {"score": 0.5, "complete": False},
            },
        ],
        [],
        suspected_files=["pkg/core.py"],
        graph_priority={"pkg/core.py": 1.1, "docs/readme.md": 0.1},
        policy_priors={
            "single_file_code": {"ucb_score": 0.9},
            "docs_only": {"ucb_score": 0.0},
        },
    )

    assert ranked["selected"]["title"] == "graph-code"
    assert ranked["selected"]["graph_bonus"] > ranked["candidates"][1]["graph_bonus"]
    assert ranked["selected"]["policy_bonus"] > ranked["candidates"][1]["policy_bonus"]


def test_code_graph_file_rank_scores_prefers_seed_neighbors():
    graph = CodeGraph(parser_backend="test")
    graph.files = {
        "pkg/a.py": {"imports": ["from pkg import b"]},
        "pkg/b.py": {"imports": ["from pkg import c"]},
        "pkg/c.py": {"imports": []},
        "docs/readme.md": {"imports": []},
    }
    scores = graph.file_rank_scores(["pkg/a.py"], ["pkg/a.py", "pkg/b.py", "pkg/c.py", "docs/readme.md"])

    assert scores["pkg/a.py"] > scores["pkg/b.py"] > scores["docs/readme.md"]
    assert scores["pkg/b.py"] >= scores["pkg/c.py"]


def test_adversarial_review_flags_test_only_patch():
    workflow = RepoPilotWorkflow()
    review = workflow._adversarial_review(
        issue="Fix runtime behavior regression in core patch selection.",
        suspected_files=["pkg/core.py", "tests/test_core.py"],
        coordination_plan=[
            {"path": "pkg/core.py", "role": "primary"},
            {"path": "tests/test_core.py", "role": "test"},
        ],
        test_plan=["python -m pytest -q tests/test_core.py"],
        selected_patch={"selected": {"touched_files": ["tests/test_regression_issue.py"]}},
        graph_priority={"pkg/core.py": 1.0, "tests/test_regression_issue.py": 0.1},
        failure_signals=[{"path": "pkg/core.py"}],
    )

    assert review["patch_archetype"] == "test_only"
    assert review["robustness_score"] < 0.5
    assert review["recommendation"] == "generate_counterexample_driven_patch"
    assert review["warnings"]


def test_ast_aware_python_patch_candidate_targets_symbol(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "pkg.py"
    target.write_text(
        "\n".join(
            [
                "def helper():",
                "    return 1",
                "",
                "def target_func():",
                "    return 2",
            ]
        ),
        encoding="utf-8",
    )
    workflow = RepoPilotWorkflow()
    candidate = workflow._ast_aware_python_patch_candidate(
        repo,
        "pkg.py",
        "Fix target_func behavior regression",
        "root cause likely inside target_func",
    )

    assert candidate is not None
    assert "AST-aware function-scoped candidate" in candidate["title"]
    assert "target_func" in candidate["title"]
    assert "RepoPilot AST-focused patch candidate" in candidate["diff"]


def test_ast_semantic_bundle_candidates_include_acceptance_context(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "pkg.py"
    target.write_text(
        "\n".join(
            [
                "def alpha():",
                "    return 1",
                "",
                "def beta_target():",
                "    return 2",
            ]
        ),
        encoding="utf-8",
    )
    workflow = RepoPilotWorkflow()
    candidates = workflow._ast_semantic_bundle_candidates(
        repo,
        "pkg.py",
        "Fix beta_target output regression",
        "beta_target likely returns wrong value",
        {"acceptance_criteria": ["return value is stable", "behavior regression is covered"]},
    )

    assert candidates
    assert any("AST-semantic candidate" in item["title"] for item in candidates)
    assert any("acceptance:" in item["diff"] for item in candidates)


def test_dynamic_candidate_budget_expands_on_strong_signals():
    workflow = RepoPilotWorkflow()
    budget = workflow._dynamic_candidate_budget(
        [
            {"passed": True, "target_file": "pkg/a.py", "touched_files": ["pkg/a.py"]},
            {"passed": True, "target_file": "pkg/b.py", "touched_files": ["pkg/b.py"]},
            {"passed": True, "target_file": "pkg/c.py", "touched_files": ["pkg/c.py"]},
            {"passed": True, "target_file": "pkg/d.py", "touched_files": ["pkg/d.py"]},
        ],
        graph_priority={"pkg/a.py": 1.1, "pkg/b.py": 0.9},
        policy_priors={"single_file_code": {"ucb_score": 1.0}},
    )

    assert budget >= 3


def test_infer_user_profile_prefers_implementation_from_issue_and_memory():
    workflow = RepoPilotWorkflow()
    profile = workflow._infer_user_profile(
        "Need a real implementation fix with minimal safe code changes",
        [
            {
                "payload": {
                    "selected_patch": {
                        "selected": {
                            "touched_files": ["pkg/core.py", "tests/test_core.py"],
                        }
                    },
                    "evaluation": {"passed": True},
                }
            }
        ],
    )

    assert profile["dominant_preference"] in {"implementation_first", "minimal_diff"}
    assert profile["preferences"]["implementation_first"] > 0
    assert profile["summary_lines"]


def test_preference_ordered_suggestions_prioritize_ast_code_candidates():
    workflow = RepoPilotWorkflow()
    ordered = workflow._preference_ordered_suggestions(
        [
            {"title": "Create a minimal regression test before patching", "target_file": "tests/test_regression_issue.py"},
            {"title": "AST-aware function-scoped candidate for pkg.py:target", "target_file": "pkg.py"},
            {"title": "README candidate", "target_file": "README.md"},
        ],
        "Need a real implementation fix",
    )

    assert ordered[0]["target_file"] == "pkg.py"


def test_semantic_ast_rewrite_plan_targets_best_function():
    workflow = RepoPilotWorkflow()
    tree = __import__("ast").parse(
        "\n".join(
            [
                "def alpha():",
                "    return 1",
                "",
                "def beta_target():",
                "    if True:",
                "        return 2",
                "    return 3",
            ]
        )
    )
    plan = workflow._semantic_ast_rewrite_plan(
        tree,
        "Fix beta_target JSON schema regression",
        "beta_target returns unstable schema",
        {"acceptance_criteria": ["schema is stable", "behavior is regression-safe"]},
    )

    assert plan is not None
    assert plan["target_symbol"] == "beta_target"
    assert plan["rewrite_kind"] in {"annotate_output_contract", "annotate_branch_logic", "annotate_return_path"}


def test_semantic_ast_rewrite_candidate_produces_diff(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "pkg.py"
    target.write_text(
        "\n".join(
            [
                "def beta_target():",
                "    return {'x': 1}",
            ]
        ),
        encoding="utf-8",
    )
    workflow = RepoPilotWorkflow()
    candidate = workflow._semantic_ast_rewrite_candidate(
        repo,
        "pkg.py",
        "Fix beta_target JSON schema regression",
        "beta_target returns unstable schema",
        {"acceptance_criteria": ["schema is stable"]},
    )

    assert candidate is not None
    assert "Semantic AST rewrite candidate" in candidate["title"]
    assert "rewrite_kind" in candidate["diff"]
