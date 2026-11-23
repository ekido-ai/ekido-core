"""Reproduce three manually identified contradictions that passed FAQ ROUGE-L."""
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/ekido_core"))
from ekido_core.recipes import eval_set_hash, passes, recipe, score_one  # noqa: E402

HERE = Path(__file__).resolve().parent
source = HERE / "reevaluation/faq-bot-hinglish.json"
result = json.loads(source.read_text(encoding="utf-8"))
with (ROOT / "experiments/recipes/faq-bot-hinglish/test.csv").open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))
assert len(rows) == result["examples"] == len(result["predictions"]) == 60
assert eval_set_hash("faq-bot-hinglish", rows) == result["eval_set_hash"]
correct = []
for row, prediction in zip(rows, result["predictions"]):
    assert row["question"] == prediction["input"] and row["answer"] == prediction["reference"]
    passed = passes("faq-bot-hinglish", prediction["answer"], prediction["reference"])
    assert passed == prediction["passed"]
    correct.append(passed)
assert sum(correct) == 7
cases = {
    0: ("The sample clinic is open from 9 am to 5 pm.", "The clinic is open from 09.00 to 18.00 daily.",
        "Reported closing time differs: 18:00 instead of 17:00."),
    6: ("The sample clinic is closed on Sundays.", "The clinic is open on Sundays.",
        "The answer says open on the day the reference says closed."),
    24: ("The sample consultation fee is 400 rupees.", "The consultation fee is 100 TL.",
         "Both the amount and the currency differ from the reference."),
}
flagged = []
for index, (reference, answer, reason) in cases.items():
    prediction = result["predictions"][index]
    assert prediction["reference"] == reference and prediction["answer"].strip() == answer
    score = score_one("faq-bot-hinglish", answer, reference)
    assert score >= recipe("faq-bot-hinglish").pass_score and correct[index]
    flagged.append({"zero_based_index": index, "reference": reference, "answer": answer,
                    "reason": reason, "rouge_l": round(score, 6), "passed": True})
report = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "eval_set_hash": result["eval_set_hash"],
          "examples": len(rows), "scorer_passes": sum(correct), "manual_contradictions_among_passes": len(flagged),
          "cases": flagged, "note": "Three clear examples selected by manual inspection, not a complete semantic audit."}
target = HERE / "faq-factual-audit.json"
target.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
print(json.dumps(report, indent=2, ensure_ascii=False))
