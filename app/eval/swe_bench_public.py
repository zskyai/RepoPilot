from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.eval.swe_bench_runner import SWEBenchCase


def load_official_swe_bench_cases(
    *,
    dataset_path: str = "",
    dataset_name: str = "",
    split: str = "test",
    instance_ids: list[str] | None = None,
    max_cases: int | None = None,
) -> list[SWEBenchCase]:
    rows = _load_rows(dataset_path=dataset_path, dataset_name=dataset_name, split=split)
    selected_ids = {item.strip() for item in (instance_ids or []) if item and item.strip()}
    cases: list[SWEBenchCase] = []
    for item in rows:
        instance_id = str(item.get("instance_id") or "").strip()
        if not instance_id:
            continue
        if selected_ids and instance_id not in selected_ids:
            continue
        problem_statement = str(item.get("problem_statement") or item.get("issue") or "").strip()
        if not problem_statement:
            continue
        repo = _normalize_repo(item.get("repo") or "")
        expected_paths = _expected_paths_from_patch_fields(item)
        cases.append(
            SWEBenchCase(
                instance_id=instance_id,
                repo=repo,
                issue=problem_statement,
                base_commit=str(item.get("base_commit") or "").strip(),
                test_command="",
                setup_commands=[],
                tags=_official_tags(dataset_name=dataset_name, split=split),
                expected_paths=expected_paths,
                expected_multi_file=len(expected_paths) > 1,
            )
        )
        if max_cases is not None and len(cases) >= max_cases:
            break
    return cases


def write_official_predictions(
    results: list[dict[str, Any]],
    output_path: str | Path,
    *,
    model_name_or_path: str,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for item in results:
            payload = {
                "instance_id": str(item.get("instance_id") or ""),
                "model_name_or_path": model_name_or_path,
                "model_patch": _extract_model_patch(item),
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def build_official_eval_instructions(
    *,
    predictions_path: str | Path,
    dataset_name: str = "",
    split: str = "test",
) -> str:
    dataset_hint = dataset_name or "<official-dataset-id>"
    return (
        "Use the official SWE-bench harness to score the generated predictions.\n"
        f"Predictions: {Path(predictions_path)}\n"
        f"Dataset: {dataset_hint}\n"
        f"Split: {split}\n\n"
        "Example:\n"
        "python -m swebench.harness.run_evaluation "
        f"--dataset_name {dataset_hint} "
        f"--split {split} "
        f"--predictions_path {Path(predictions_path)}"
    )


def _load_rows(*, dataset_path: str, dataset_name: str, split: str) -> list[dict[str, Any]]:
    if dataset_path:
        return _load_rows_from_file(Path(dataset_path))
    if dataset_name:
        try:
            from datasets import load_dataset
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Loading a public SWE-bench dataset from HuggingFace requires `datasets`. "
                "Install it with `pip install datasets` or pass --dataset-path with a local JSON/JSONL export."
            ) from exc
        dataset = load_dataset(dataset_name, split=split)
        return [dict(item) for item in dataset]
    raise ValueError("Either dataset_path or dataset_name must be provided.")


def _load_rows_from_file(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".parquet":
        return _load_rows_from_parquet(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, dict):
        rows = payload.get("instances") or payload.get("rows") or payload.get("data") or []
        return [dict(item) for item in rows if isinstance(item, dict)]
    return [dict(item) for item in payload if isinstance(item, dict)]


def _normalize_repo(repo: Any) -> str:
    value = str(repo or "").strip()
    if not value:
        return value
    if Path(value).exists():
        return value
    if len(value) > 2 and value[1:3] in (":\\", ":/"):
        return value
    if value.startswith(("http://", "https://", "git@")):
        return value
    if value.endswith(".git"):
        return f"https://github.com/{value}"
    if "/" in value:
        return f"https://github.com/{value}.git"
    return value


def _load_rows_from_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Loading a local SWE-bench parquet export requires `pyarrow`."
        ) from exc
    table = pq.read_table(path)
    return [dict(item) for item in table.to_pylist()]


def _official_tags(*, dataset_name: str, split: str) -> list[str]:
    tags = ["official_public_eval"]
    if dataset_name:
        tags.append(dataset_name.replace("/", "_"))
    if split:
        tags.append(f"split:{split}")
    return tags


def _extract_model_patch(result: dict[str, Any]) -> str:
    patch_path = str(
        ((result.get("selected_patch") or {}).get("patch_file"))
        or result.get("selected_patch_file")
        or ""
    ).strip()
    if not patch_path:
        return ""
    path = Path(patch_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _expected_paths_from_patch_fields(item: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("patch", "test_patch"):
        text = str(item.get(key) or "")
        for line in text.splitlines():
            if not line.startswith("+++ "):
                continue
            path = line[4:].strip()
            if path == "/dev/null":
                continue
            if path.startswith("b/"):
                path = path[2:]
            if path and path not in paths:
                paths.append(path)
    return paths[:8]
