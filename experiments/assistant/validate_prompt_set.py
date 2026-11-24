"""Checks the assistant's test set: plain-language requests and what the assistant should do with each.

    python -I experiments/assistant/validate_prompt_set.py [path/to/prompts.jsonl]

Each line is {"prompt": str, "expected": {"recipe": str, "language": str, "labels": [str]?}, "should_refuse": bool}.
A request that must be refused has "should_refuse": true and may leave "expected" out. The checks:
- at least 50 lines, valid JSON, with those keys and types
- at least 10 requests that must be refused (the acceptable-use policy cases)
- every other line names a known recipe and a language (en, hinglish or hi)
- when expected labels are supplied, they match the selected classification recipe
- no duplicate prompts.

Exit code 0 means it passed. Every problem is printed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "ekido_core"))
from ekido_core.recipes import RECIPES  # noqa: E402

LANGUAGES = {"en", "hinglish", "hi"}
MIN_LINES, MIN_REFUSALS = 50, 10


def validate(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path}: missing"]
    errors: list[str] = []
    prompts: list[str] = []
    refusals = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {number}: not valid JSON ({exc.msg})")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {number}: must be a JSON object")
            continue
        prompt, refuse, expected = record.get("prompt"), record.get("should_refuse"), record.get("expected")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"line {number}: 'prompt' must be non-empty text")
            continue
        prompts.append(" ".join(prompt.lower().split()))
        if not isinstance(refuse, bool):
            errors.append(f"line {number}: 'should_refuse' must be true or false")
            continue
        if refuse:
            refusals += 1
            continue
        if not isinstance(expected, dict):
            errors.append(f"line {number}: 'expected' must be an object when the request is allowed")
            continue
        recipe_id, language = expected.get("recipe"), expected.get("language")
        if not isinstance(recipe_id, str) or recipe_id not in RECIPES:
            errors.append(f"line {number}: expected.recipe {recipe_id!r} is not one of {sorted(RECIPES)}")
        if not isinstance(language, str) or language not in LANGUAGES:
            errors.append(f"line {number}: expected.language {language!r} is not one of {sorted(LANGUAGES)}")
        labels = expected.get("labels")
        if labels is not None and not (isinstance(labels, list) and labels and all(isinstance(x, str) and x for x in labels)):
            errors.append(f"line {number}: expected.labels, when given, must be a non-empty list of text")
        elif labels is not None and isinstance(recipe_id, str) and recipe_id in RECIPES:
            required = RECIPES[recipe_id].labels
            if not required:
                errors.append(f"line {number}: expected.labels is only valid for a classification recipe")
            elif len(labels) != len(required) or set(labels) != set(required):
                errors.append(f"line {number}: expected.labels must match the recipe labels {list(required)}")
    if len(prompts) < MIN_LINES:
        errors.append(f"{len(prompts)} prompts, needs at least {MIN_LINES}")
    if refusals < MIN_REFUSALS:
        errors.append(f"{refusals} prompts must be refused, needs at least {MIN_REFUSALS}")
    duplicates = [p for p, c in Counter(prompts).items() if c > 1]
    if duplicates:
        errors.append(f"{len(duplicates)} duplicated prompts, e.g. {duplicates[0][:60]!r}")
    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else Path(__file__).resolve().parent / "prompts.jsonl"
    errors = validate(path)
    for error in errors:
        print(f"error: {error}")
    print("PASS" if not errors else f"FAIL: {len(errors)} problems")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
