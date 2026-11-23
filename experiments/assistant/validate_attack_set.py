"""Checks the assistant's attack set: requests built to trick it, and what it must do with each.

    python -I experiments/assistant/validate_attack_set.py [path/to/attacks.jsonl]

Each line is {"id", "category", "language", "prompt", "expect", ...}:
- "expect" is "refuse" (it must refuse or send to review), "safe" (any answer is fine as long as it stays inside the
  rules below), or "reject" (the API must refuse the input itself with a 4xx).
- "recipe", optional: if the assistant proposes a recipe, it must be this one.
- "never", optional: text that must never appear anywhere in the response.
- "build", optional: {"repeat", "times", "suffix"} makes the message, for inputs too long to keep in the file.
- "dataset_id" / "conversation_id", optional: sent with the message, to test someone else's data or a forged token.

The checks: at least 50 cases, unique ids, every category from CATEGORIES with at least 5 cases, at least 20 that must
be refused, and each field with the right type. Exit code 0 means it passed; every problem is printed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "ekido_core"))
from ekido_core.recipes import RECIPES  # noqa: E402

CATEGORIES = {"injection", "jailbreak", "data-fishing", "obfuscation", "malformed"}
EXPECT = {"refuse", "safe", "reject"}
LANGUAGES = {"en", "hi", "hinglish", "mixed", "none"}
MIN_CASES, MIN_PER_CATEGORY, MIN_REFUSE = 50, 5, 20
KEYS = {"id", "category", "language", "prompt", "expect", "recipe", "never", "build", "dataset_id", "conversation_id"}


def message(case: dict) -> str:
    """The text sent to the assistant: the prompt, or the built-up long input."""
    build = case.get("build")
    if build:
        return build["repeat"] * build["times"] + build["suffix"]
    return case["prompt"]


def validate(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path}: missing"]
    errors: list[str] = []
    ids: list[str] = []
    categories: Counter = Counter()
    refusals = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {number}: not valid JSON ({exc.msg})")
            continue
        if not isinstance(case, dict):
            errors.append(f"line {number}: must be a JSON object")
            continue
        extra = set(case) - KEYS
        if extra:
            errors.append(f"line {number}: unknown fields {sorted(extra)}")
        ids.append(str(case.get("id")))
        if not isinstance(case.get("id"), str) or not case["id"]:
            errors.append(f"line {number}: 'id' must be non-empty text")
        if case.get("category") not in CATEGORIES:
            errors.append(f"line {number}: category {case.get('category')!r} is not one of {sorted(CATEGORIES)}")
        else:
            categories[case["category"]] += 1
        if case.get("language") not in LANGUAGES:
            errors.append(f"line {number}: language {case.get('language')!r} is not one of {sorted(LANGUAGES)}")
        if case.get("expect") not in EXPECT:
            errors.append(f"line {number}: expect {case.get('expect')!r} is not one of {sorted(EXPECT)}")
        elif case["expect"] == "refuse":
            refusals += 1
        if not isinstance(case.get("prompt"), str):
            errors.append(f"line {number}: 'prompt' must be text (it may be empty only when 'build' is given)")
        build = case.get("build")
        if build is not None:
            if not (isinstance(build, dict) and set(build) == {"repeat", "times", "suffix"}
                    and isinstance(build["repeat"], str) and build["repeat"]
                    and type(build["times"]) is int and 1 <= build["times"] <= 10_000 and isinstance(build["suffix"], str)):
                errors.append(f"line {number}: 'build' must be {{repeat: text, times: 1-10000, suffix: text}}")
        elif isinstance(case.get("prompt"), str) and not case["prompt"]:
            errors.append(f"line {number}: an empty prompt needs 'build'")
        recipe = case.get("recipe")
        if recipe is not None and recipe not in RECIPES:
            errors.append(f"line {number}: recipe {recipe!r} is not one of {sorted(RECIPES)}")
        never = case.get("never")
        if never is not None and not (isinstance(never, list) and never and all(isinstance(x, str) and x for x in never)):
            errors.append(f"line {number}: 'never' must be a non-empty list of text")
        for field in ("dataset_id", "conversation_id"):
            if field in case and not (isinstance(case[field], str) and case[field]):
                errors.append(f"line {number}: '{field}' must be non-empty text")
    if len(ids) < MIN_CASES:
        errors.append(f"{len(ids)} cases, needs at least {MIN_CASES}")
    for category in sorted(CATEGORIES):
        if categories[category] < MIN_PER_CATEGORY:
            errors.append(f"category {category}: {categories[category]} cases, needs at least {MIN_PER_CATEGORY}")
    if refusals < MIN_REFUSE:
        errors.append(f"{refusals} cases must be refused, needs at least {MIN_REFUSE}")
    duplicates = [i for i, c in Counter(ids).items() if c > 1]
    if duplicates:
        errors.append(f"duplicate ids: {duplicates}")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "attacks.jsonl"
    errors = validate(path)
    for error in errors:
        print(error)
    if not errors:
        print(f"{path}: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
