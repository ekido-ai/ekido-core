"""Re-score the saved helper run against the committed test set and diagnostic."""

import csv
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root / "packages" / "ekido_core"))
from ekido_core.recipes import eval_set_hash, passes  # noqa: E402

here = Path(__file__).resolve().parent
result = json.loads((here / "summary.json").read_text(encoding="utf-8"))
diagnostic = json.loads((here.parent / "raw-diagnostic" / "summary.json").read_text(encoding="utf-8"))
with (root / "experiments/recipes/ticket-sorter-hinglish/test.csv").open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

assert len(rows) == 100
assert result["eval_set_hash"] == diagnostic["eval_set_hash"] == eval_set_hash("ticket-sorter-hinglish", rows)
assert result["worker_export_sha256"] == "c993361d3718b4d14d2644185459c936ec69725f7de4576a674b10f5314ba556"
assert result["llama_cpp_revision"] == diagnostic["llama_cpp_revision"]
assert result["reference_pass_rate"] == diagnostic["reference_pass_rate"] == 0.82
for quant, expected in (("Q4_K_M", 79), ("Q8_0", 83)):
    run = result["raw_completion"][quant]
    prior = diagnostic["raw_completion"][quant]
    assert run["gguf_sha256"] == prior["gguf_sha256"]
    assert run["examples"] == len(run["answers"]) == len(rows)
    for row, answer in zip(rows, run["answers"]):
        assert row["label"] == answer["gold"]
        assert passes("ticket-sorter-hinglish", answer["answer"], answer["gold"]) == answer["passed"]
    correct = sum(answer["passed"] for answer in run["answers"])
    assert correct == expected and run["pass_rate"] == correct / len(rows)
    assert abs(run["difference_from_hf"] - (run["pass_rate"] - 0.82)) < 1e-9
    assert run["answers"] == prior["answers"]
    print(f"{quant}: {correct}/{len(rows)}; all saved answers match and rescore")

print("Executed notebook SHA-256:", hashlib.sha256((here / "run.py").read_bytes()).hexdigest())
