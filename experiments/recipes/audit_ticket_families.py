"""Audit manually inferred ticket families and illustrate clustering sensitivity.

This does not reconstruct the unavailable original generator or establish
confidence on customer data. See ticket-sorter-hinglish/FAMILY-AUDIT.md.
"""
import csv
import hashlib
import json
import math
import random
import sys
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/ekido_core"))
from ekido_core.recipes import eval_set_hash, passes  # noqa: E402

DATA = ROOT / "experiments/recipes/ticket-sorter-hinglish"
SUMMARY = ROOT / "experiments/results/gguf-two-t4-20261119/helper-verification/summary.json"
OUT = ROOT / "experiments/results/datasets/ticket-family-confidence.json"


def wilson(successes, total):
    z = NormalDist().inv_cdf(.975)
    p = successes / total
    divisor = 1 + z * z / total
    midpoint = (p + z * z / (2 * total)) / divisor
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / divisor
    return [midpoint - half, midpoint + half]


def main():
    with (DATA / "test.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    mapping = json.loads((DATA / "semantic-families.json").read_text(encoding="utf-8"))
    summary_bytes = SUMMARY.read_bytes()
    summary = json.loads(summary_bytes)
    test_hash = eval_set_hash("ticket-sorter-hinglish", rows)
    if len(rows) != 100 or test_hash != mapping["eval_set_hash"] or test_hash != summary["eval_set_hash"]:
        raise ValueError("test set differs from the annotated and evaluated set")
    groups = list(mapping["families"].values())
    indexes = [index for group in groups for index in group]
    if not groups or any(not group for group in groups) or sorted(indexes) != list(range(len(rows))):
        raise ValueError("families must partition all test rows exactly once")
    if any(len({rows[i]["label"] for i in group}) != 1 for group in groups):
        raise ValueError("a family contains inconsistent gold classes")
    answers = summary["raw_completion"]["Q8_0"]["answers"]
    if len(answers) != len(rows):
        raise ValueError("missing saved answers")
    correct = []
    for row, answer in zip(rows, answers):
        if answer["gold"] != row["label"]:
            raise ValueError("saved reference differs from test row")
        passed = passes("ticket-sorter-hinglish", answer["answer"], row["label"])
        if passed != answer["passed"]:
            raise ValueError("saved pass flag differs from scorer")
        correct.append(int(passed))
    if sum(correct) != 83:
        raise ValueError("unexpected historical Q8 score")
    rng = random.Random(20261121)
    cluster_totals = [(sum(correct[i] for i in group), len(group)) for group in groups]
    bootstrap = []
    for _ in range(20000):
        sample = rng.choices(cluster_totals, k=len(groups))
        bootstrap.append(sum(s for s, _ in sample) / sum(n for _, n in sample))
    bootstrap.sort()
    kish_n = len(rows) ** 2 / sum(len(group) ** 2 for group in groups)
    result = {
        "test_eval_set_hash": test_hash,
        "source_summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "model": "Q8_0", "correct": sum(correct), "rows": len(rows),
        "inferred_semantic_families": len(groups),
        "family_size_histogram": {str(n): sum(len(g) == n for g in groups) for n in sorted({len(g) for g in groups})},
        "kish_n_assuming_perfect_within_family_correlation": round(kish_n, 3),
        "iid_wilson_95_percent_interval": [round(x, 4) for x in wilson(sum(correct), len(rows))],
        "family_bootstrap_95_percent_interval": [round(bootstrap[499], 4), round(bootstrap[19499], 4)],
        "bootstrap_resamples": 20000, "bootstrap_seed": 20261121,
        "qualification": "Inferred semantic groups and reused synthetic data; intervals are sensitivity illustrations, not customer-data confidence or quality-gate decisions."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
