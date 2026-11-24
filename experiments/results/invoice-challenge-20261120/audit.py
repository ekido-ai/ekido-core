"""Rescore the saved invoice challenge run against the checked-in dataset."""
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/ekido_core"))
from ekido_core.canonical import document_hash  # noqa: E402
from ekido_core.recipes import eval_set_hash, passes, score  # noqa: E402

HERE = Path(__file__).resolve().parent
result = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
spec = json.loads((HERE / "student_spec.json").read_text(encoding="utf-8"))
manifest = json.loads((HERE / "checkpoint-manifest.json").read_text(encoding="utf-8"))
with (ROOT / "experiments/recipes/invoice-fields/challenge.csv").open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))
for row in rows:
    row["text"] = row["text"].replace("\r\n", "\n").replace("\r", "\n")

assert len(rows) == result["rows"] == 60
assert eval_set_hash("invoice-fields", rows) == result["eval_set_hash"]
assert manifest == result["checkpoint_manifest"]
assert manifest["logical_step"] == 50 and manifest["immutable_hash"] == document_hash(spec)
assert manifest["model"] == spec["model"] == result["model"]
for arm, expected in (("base", 59), ("student", 60)):
    data = result[arm]
    predictions = data["predictions"]
    assert len(predictions) == len(rows)
    for row, prediction in zip(rows, predictions):
        assert row["text"] == prediction["input"] and row["json"] == prediction["reference"]
        assert passes("invoice-fields", prediction["answer"], prediction["reference"]) == prediction["passed"]
    correct = sum(p["passed"] for p in predictions)
    assert correct == expected and math.isclose(data["pass_rate"], correct / len(rows), abs_tol=1e-12)
    assert math.isclose(data["mean_score"], score("invoice-fields", [p["answer"] for p in predictions],
                                                [p["reference"] for p in predictions]), abs_tol=1e-12)
    print(f"{arm}: {correct}/{len(rows)}; predictions and scores verified")
print("Pulled notebook SHA-256:", hashlib.sha256((HERE / "run.py").read_bytes()).hexdigest())
