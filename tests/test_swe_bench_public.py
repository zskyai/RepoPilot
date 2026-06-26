from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval.swe_bench_public import (
    build_official_eval_instructions,
    load_official_swe_bench_cases,
    write_official_predictions,
)
from app.eval.swe_bench_runner import SWEBenchStyleRunner


def test_load_official_swe_bench_cases_from_jsonl(tmp_path: Path):
    dataset = tmp_path / "official_cases.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "django__django-10001",
                        "repo": "django/django",
                        "problem_statement": "Fix queryset regression in admin changelist rendering.",
                        "base_commit": "abc123",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "psf__requests-20002",
                        "repo": "psf/requests",
                        "problem_statement": "Repair timeout propagation bug.",
                        "base_commit": "def456",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    cases = load_official_swe_bench_cases(
        dataset_path=str(dataset),
        dataset_name="princeton-nlp/SWE-bench_Verified",
        split="test",
        instance_ids=["django__django-10001"],
    )

    assert len(cases) == 1
    assert cases[0].instance_id == "django__django-10001"
    assert cases[0].repo == "https://github.com/django/django.git"
    assert cases[0].base_commit == "abc123"
    assert "official_public_eval" in cases[0].tags


def test_write_official_predictions_reads_patch_file(tmp_path: Path):
    patch_file = tmp_path / "candidate.patch"
    patch_file.write_text(
        "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-print('old')\n+print('new')\n",
        encoding="utf-8",
    )
    target = tmp_path / "all_preds.jsonl"
    write_official_predictions(
        [
            {
                "instance_id": "demo__repo-1",
                "selected_patch_file": str(patch_file),
            }
        ],
        target,
        model_name_or_path="RepoPilot",
    )

    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[0]["instance_id"] == "demo__repo-1"
    assert lines[0]["model_name_or_path"] == "RepoPilot"
    assert "print('new')" in lines[0]["model_patch"]


def test_load_official_swe_bench_cases_from_parquet(tmp_path: Path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    dataset = tmp_path / "official_cases.parquet"
    table = pa.table(
        {
            "instance_id": ["pallets__flask-1"],
            "repo": ["pallets/flask"],
            "problem_statement": ["Fix CLI context regression."],
            "base_commit": ["123abc"],
        }
    )
    pq.write_table(table, dataset)

    cases = load_official_swe_bench_cases(dataset_path=str(dataset))
    assert len(cases) == 1
    assert cases[0].instance_id == "pallets__flask-1"
    assert cases[0].repo == "https://github.com/pallets/flask.git"


def test_load_official_swe_bench_cases_keeps_local_repo_path(tmp_path: Path):
    local_repo = tmp_path / "repo"
    local_repo.mkdir()
    dataset = tmp_path / "official_cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "instance_id": "local__repo-1",
                "repo": str(local_repo),
                "problem_statement": "Inspect local repository behavior.",
                "base_commit": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cases = load_official_swe_bench_cases(dataset_path=str(dataset))
    assert cases[0].repo == str(local_repo)


def test_build_official_eval_instructions_mentions_harness(tmp_path: Path):
    text = build_official_eval_instructions(
        predictions_path=tmp_path / "all_preds.jsonl",
        dataset_name="princeton-nlp/SWE-bench_Verified",
        split="test",
    )
    assert "swebench.harness.run_evaluation" in text
    assert "SWE-bench" in text


def test_load_official_cases_extracts_expected_paths(tmp_path: Path):
    dataset = tmp_path / "official_cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "instance_id": "astropy__astropy-12907",
                "repo": "astropy/astropy",
                "problem_statement": "Fix separability_matrix bug.",
                "base_commit": "abc123",
                "patch": "diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py\n--- a/astropy/modeling/separable.py\n+++ b/astropy/modeling/separable.py\n@@ -1 +1 @@\n-a\n+b\n",
                "test_patch": "diff --git a/astropy/modeling/tests/test_separable.py b/astropy/modeling/tests/test_separable.py\n--- a/astropy/modeling/tests/test_separable.py\n+++ b/astropy/modeling/tests/test_separable.py\n@@ -1 +1 @@\n-a\n+b\n",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cases = load_official_swe_bench_cases(dataset_path=str(dataset))
    assert cases[0].expected_paths == [
        "astropy/modeling/separable.py",
        "astropy/modeling/tests/test_separable.py",
    ]
    assert cases[0].expected_multi_file is True


def test_public_markdown_warns_for_approximate_repo_snapshots(tmp_path: Path):
    runner = SWEBenchStyleRunner(tmp_path / "work")
    summary = runner._public_eval_summary(
        [
            {
                "instance_id": "astropy__astropy-12907",
                "base_commit": "abc123",
                "repo_snapshot_exact": False,
                "passed": False,
                "adjusted_passed": False,
                "overall": 0.7,
                "elapsed_seconds": 10.0,
                "expected_paths": ["astropy/modeling/separable.py"],
                "cross_file_localized": True,
                "expected_path_recall": 1.0,
                "repair_context_used": True,
                "repair_rounds": 1,
                "selected_patch_multi_file": False,
                "environment_limited": False,
                "tags": ["official_public_eval"],
            }
        ]
    )
    markdown = runner._public_markdown(
        [
            {
                "instance_id": "astropy__astropy-12907",
                "base_commit": "abc123",
                "repo_snapshot_exact": False,
                "passed": False,
                "adjusted_passed": False,
                "overall": 0.7,
                "repair_rounds": 1,
                "expected_path_recall": 1.0,
                "tags": ["official_public_eval"],
            }
        ],
        summary,
    )

    assert summary["approximate_repo_case_count"] == 1
    assert summary["official_reproducibility"] == "approximate"
    assert "approximate public-eval signals" in markdown
