"""Measure how often ROUGE accepts deliberately altered catalogue facts."""
import csv
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "packages/ekido_core"))
from ekido_core.recipes import passes, score_one  # noqa: E402


def replace_exactly_once(text, original, replacement):
    pattern = r"(?<!\w)" + re.escape(original) + r"(?!\w)"
    output, count = re.subn(pattern, lambda _: replacement, text, flags=re.IGNORECASE)
    if count != 1:
        raise ValueError(f"Expected one instance of {original!r}; got {count} in {text!r}")
    return output


def main():
    with (HERE / "test.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 60
    accepted = Counter()
    for row in rows:
        fields = dict(part.strip().split(": ", 1) for part in row["attributes"].split("; "))
        for field, replacement in (("colour", "ultraviolet"), ("size", "999 cm")):
            assert fields[field].lower() != replacement
            altered = replace_exactly_once(row["description"], fields[field], replacement)
            accepted[field] += passes("product-descriptions", altered, row["description"])
        assert math.isclose(score_one("product-descriptions", row["description"], row["description"]), 1.0)
    for field in ("colour", "size"):
        print(f"{field}: {accepted[field]}/{len(rows)} deliberately incorrect descriptions pass")
    print("Synthetic counterfactuals, not model outputs or a real-world error estimate.")


if __name__ == "__main__":
    main()
