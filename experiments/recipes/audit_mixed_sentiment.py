"""Structural audit for the candidate mixed-sentiment challenge."""
import csv
import re
from collections import Counter
from pathlib import Path

from validate_dataset import PII_PATTERNS

ROOT = Path(__file__).resolve().parent / "review-sentiment"


def read(name):
    with (ROOT / name).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["text", "label"]:
            raise ValueError(f"{name}: wrong columns")
        return list(reader)


def normalise(text):
    return " ".join(text.casefold().split())


def main():
    rows = read("mixed-challenge.csv")
    if Counter(row["label"] for row in rows) != {"positive": 8, "negative": 8, "neutral": 8}:
        raise ValueError("unexpected label counts")
    existing = {normalise(row["text"]) for name in ("train.csv", "test.csv") for row in read(name)}
    seen = set()
    for row in rows:
        text = row["text"].strip()
        key = normalise(text)
        if not key or key in existing or key in seen:
            raise ValueError("empty, duplicate or overlapping review")
        seen.add(key)
        if any(pattern.search(text) for pattern in PII_PATTERNS.values()):
            raise ValueError("PII-shaped text needs review")
    hindi = sum(bool(re.search(r"[\u0900-\u097f]", row["text"])) for row in rows)
    if hindi < 5:
        raise ValueError("insufficient Devanagari examples")
    print(f"{len(rows)} reviews; 8 per class; {hindi} with Devanagari; no exact overlap or PII-pattern hits")


if __name__ == "__main__":
    main()
