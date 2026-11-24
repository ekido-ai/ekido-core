"""The candidate challenge audit must reject bad labels and invoice arithmetic."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RECIPES = Path(__file__).resolve().parents[1] / "recipes"
sys.path.insert(0, str(RECIPES))
import audit_invoice_challenge as audit  # noqa: E402


class InvoiceChallengeTest(unittest.TestCase):
    def setUp(self):
        self.original = audit.read("challenge.csv")
        self.existing = {name: audit.read(name) for name in ("train.csv", "test.csv")}

    def check_with(self, rows):
        # Bypass only the generator equality check: the separate validation must
        # catch an error even if the generator itself were changed to emit it.
        def read(name):
            return rows if name == "challenge.csv" else self.existing[name]

        with patch.object(audit, "read", side_effect=read), patch.object(audit, "generated_rows", return_value=rows):
            audit.main()

    def test_valid_data(self):
        self.check_with(self.original)

    def test_wrong_normalized_date(self):
        rows = copy.deepcopy(self.original)
        label = json.loads(rows[0]["json"])
        label["date"] = "2020-01-01"
        rows[0]["json"] = json.dumps(label)
        with self.assertRaisesRegex(ValueError, "normalized date"):
            self.check_with(rows)

    def test_incorrect_arithmetic(self):
        rows = copy.deepcopy(self.original)
        rows[0]["text"] = rows[0]["text"].replace("Item A: INR 900.00", "Item A: INR 901.00")
        with self.assertRaisesRegex(ValueError, "arithmetic"):
            self.check_with(rows)

    def test_overlap_is_rejected(self):
        rows = copy.deepcopy(self.original)
        rows[0]["text"] = self.existing["train.csv"][0]["text"]
        with self.assertRaisesRegex(ValueError, "overlapping|duplicate or existing"):
            self.check_with(rows)


if __name__ == "__main__":
    unittest.main()
