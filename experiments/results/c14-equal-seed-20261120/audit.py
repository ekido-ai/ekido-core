"""Recount the saved predictions and check the C14 run's data identities."""
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "packages/ekido_core"))
from ekido_core.canonical import document_hash  # noqa: E402
from ekido_core.recipes import passes  # noqa: E402


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


summary, spec, manifest = load("summary.json"), load("spec.json"), load("checkpoint-manifest.json")
blob = (HERE / "dataset.jsonl").read_bytes()
assert hashlib.sha256(blob).hexdigest() == summary["dataset_sha256"] == spec["dataset"]["sha256"] == manifest["dataset_sha256"]
assert manifest["immutable_hash"] == document_hash(spec)
assert manifest["logical_step"] == summary["selected_step"] == 400
rows = [json.loads(line) for line in blob.decode("utf-8").splitlines()]
train = [row for row in rows if row["split"] == "train"]
validation = [row for row in rows if row["split"] == "test"]
assert len(train) == 626 and len(validation) == 100
with (HERE / "source-train.csv").open(encoding="utf-8", newline="") as handle:
    original = list(csv.DictReader(handle))
labels = ("complaint", "order", "question", "refund", "other")
rng = random.Random(42)
seeds = [row for label in labels for row in rng.sample([row for row in original if row["label"] == label], 6)]
assert seeds == load("seed_rows.json")
assert all(sum(row["text"] == seed["text"] and row["label"] == seed["label"] for row in train) >= 6 for seed in seeds)
with (HERE / "historical-test.csv").open(encoding="utf-8", newline="") as handle:
    historical = list(csv.DictReader(handle))
for name, inputs in (("validation", validation), ("historical_test", historical)):
    result = summary[name]
    assert len(inputs) == len(result["examples"]) == result["total"] == 100
    correct = Counter()
    for row, prediction in zip(inputs, result["examples"]):
        assert (row["text"], row["label"]) == (prediction["text"], prediction["gold"])
        assert passes("ticket-sorter-hinglish", prediction["answer"], prediction["gold"]) == prediction["passed"]
        correct[prediction["gold"]] += prediction["passed"]
    assert sum(correct.values()) == result["correct"]
    assert all(result["per_label"][label]["correct"] == correct[label] for label in labels)
    print(f"{name}: {result['correct']}/{result['total']}")
assert summary["independent_test"] is None
print("PASS: dataset, seed rows, spec, checkpoint manifest and 200 saved predictions")
