"""The family audit must reject changed rows and invalid group assignments."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RECIPES = Path(__file__).resolve().parents[1] / "recipes"
sys.path.insert(0, str(RECIPES))
import audit_ticket_families as audit  # noqa: E402


class TicketFamilyAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        shutil.copytree(audit.DATA, self.data)
        self.output = Path(self.tmp.name) / "out.json"

    def run_audit(self):
        with patch.object(audit, "DATA", self.data), patch.object(audit, "OUT", self.output):
            audit.main()

    def test_duplicate_row_assignment_fails(self):
        path = self.data / "semantic-families.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        next(iter(value["families"].values())).append(0)
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "partition"):
            self.run_audit()

    def test_changed_test_set_fails(self):
        path = self.data / "test.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("t-shirt", "shirt", 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "test set differs"):
            self.run_audit()

    def test_report_is_reproducible(self):
        self.run_audit()
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual((data["inferred_semantic_families"], data["correct"]), (42, 83))
        self.assertEqual(data["family_bootstrap_95_percent_interval"], [0.7282, 0.9216])


if __name__ == "__main__":
    unittest.main()
