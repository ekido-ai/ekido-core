"""The `distill-gen/v1` contract: the generation job a teacher runs before a student is trained (docs/api/distill-gen-v1.md).

The Platform builds the spec, the Coordinator checks and places it, the provider's runtime generates, a verifier re-checks the file. All four
use these helpers, so they cannot disagree on bytes or hashes. Dependency-free.

It is deliberately not one of `job_spec.TEMPLATES`: a generation job is not a training job, and `POST /jobs` must keep refusing it.
"""

from __future__ import annotations

import hashlib
import json
import re

from .data_identity import require_commit, require_digest
from .recipes import RECIPES

TEMPLATE = "distill-gen/v1"
TEACHER_ID = "Qwen/Qwen2.5-7B-Instruct"
TEACHER_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
TEACHER_QUANTIZATION = "4bit"
FILTER_VERSION = 1
MAX_SEED_ROWS = 100
MAX_TEST_HASHES = 10_000
MAX_REGENERATION_ATTEMPT = 1
SPEC_FIELDS = ("template", "recipe_id", "teacher", "seeds", "test_input_sha256", "per_seed", "generation_seed", "max_new_tokens",
               "attempts", "filter_version", "attempt")
OUTPUT_ROWS = "generated.jsonl"
OUTPUT_REPORT = "generation_report.json"


def normalise(value: str) -> str:
    """Spaces collapsed, case folded: the same rule as the generator's dedupe and the verifier's checks."""
    return re.sub(r"\s+", " ", value.strip()).casefold()


def input_sha256(value: str) -> str:
    """What the spec carries instead of a test input's text."""
    return hashlib.sha256(normalise(value).encode("utf-8")).hexdigest()


def jsonl_bytes(rows: list[dict]) -> bytes:
    """The one serialisation of rows (`seeds.jsonl` and `generated.jsonl`): compact, key-sorted, UTF-8, one row and one LF per line."""
    return b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for row in rows)


def test_input_hashes(recipe_id: str, test_rows: list[dict]) -> list[str]:
    source, _ = RECIPES[recipe_id].columns
    return sorted({input_sha256(row[source]) for row in test_rows})


def _whole(spec: dict, name: str, low: int, high: int, problems: list[str]) -> None:
    value = spec.get(name)
    if type(value) is not int or not low <= value <= high:
        problems.append(f"{name} must be a whole number from {low} to {high}")


def spec_problems(spec: object) -> list[str]:
    """Everything wrong with a generation spec, in words a caller can act on. Empty means acceptable."""
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    problems = [f"{name} is missing" for name in SPEC_FIELDS if name not in spec]
    problems += [f"{name} is not a field of {TEMPLATE}" for name in sorted(set(spec) - set(SPEC_FIELDS))]
    if problems:
        return problems
    if spec["template"] != TEMPLATE:
        problems.append(f"template must be {TEMPLATE}")
    if not isinstance(spec["recipe_id"], str) or spec["recipe_id"] not in RECIPES:
        problems.append(f"recipe_id must be one of {', '.join(sorted(RECIPES))}")
    teacher = spec["teacher"]
    if not isinstance(teacher, dict) or set(teacher) != {"id", "revision", "quantization"}:
        problems.append("teacher must have exactly id, revision and quantization")
    else:
        if teacher["id"] != TEACHER_ID:
            problems.append(f"teacher.id must be {TEACHER_ID}")
        try:
            require_commit(teacher["revision"], "teacher.revision")
        except ValueError as exc:
            problems.append(str(exc))
        if teacher["quantization"] != TEACHER_QUANTIZATION:
            problems.append(f"teacher.quantization must be {TEACHER_QUANTIZATION}")
    seeds = spec["seeds"]
    if not isinstance(seeds, dict) or set(seeds) != {"sha256", "bytes", "rows"}:
        problems.append("seeds must have exactly sha256, bytes and rows")
    else:
        try:
            require_digest(seeds["sha256"], "seeds.sha256")
        except ValueError as exc:
            problems.append(str(exc))
        _whole(seeds, "bytes", 1, 4_000_000, problems)
        _whole(seeds, "rows", 1, MAX_SEED_ROWS, problems)
    hashes = spec["test_input_sha256"]
    if (not isinstance(hashes, list) or not 1 <= len(hashes) <= MAX_TEST_HASHES
            or not all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes) or hashes != sorted(set(hashes))):
        problems.append("test_input_sha256 must be a sorted list of unique SHA-256 hashes of the test inputs")
    _whole(spec, "per_seed", 1, 20, problems)
    _whole(spec, "generation_seed", 0, 2**31 - 1, problems)
    _whole(spec, "max_new_tokens", 1, 512, problems)
    _whole(spec, "attempts", 1, 10, problems)
    _whole(spec, "filter_version", FILTER_VERSION, FILTER_VERSION, problems)
    _whole(spec, "attempt", 0, MAX_REGENERATION_ATTEMPT, problems)
    return problems
