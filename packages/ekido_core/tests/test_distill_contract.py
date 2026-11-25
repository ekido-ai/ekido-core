import copy
import unittest

from ekido_core import distill_contract as contract
from ekido_core.job_spec import TEMPLATES, spec_problems as job_spec_problems


def spec(**changes):
    base = {
        "template": contract.TEMPLATE,
        "recipe_id": "review-sentiment",
        "teacher": {"id": contract.TEACHER_ID, "revision": contract.TEACHER_REVISION, "quantization": "4bit"},
        "seeds": {"sha256": "a" * 64, "bytes": 2048, "rows": 30},
        "test_input_sha256": sorted([contract.input_sha256("great phone"), contract.input_sha256("bad battery")]),
        "per_seed": 4, "generation_seed": 42, "max_new_tokens": 96, "attempts": 3, "filter_version": 1, "attempt": 0,
    }
    base.update(changes)
    return base


class DistillContract(unittest.TestCase):
    def test_the_documented_spec_is_accepted(self):
        self.assertEqual(contract.spec_problems(spec()), [])

    def test_a_missing_or_unknown_field_is_refused(self):
        missing = spec()
        del missing["per_seed"]
        self.assertIn("per_seed is missing", contract.spec_problems(missing))
        self.assertTrue(contract.spec_problems(spec(test_rows=[{"review": "secret"}])))

    def test_bad_values_are_refused(self):
        good = spec()
        bad_teacher = copy.deepcopy(good["teacher"])
        bad_teacher["revision"] = "main"
        for changes in ({"recipe_id": "poems"}, {"teacher": bad_teacher}, {"seeds": {"sha256": "x", "bytes": 1, "rows": 30}},
                        {"seeds": {"sha256": "a" * 64, "bytes": 1, "rows": 101}}, {"test_input_sha256": []},
                        {"test_input_sha256": ["b" * 64, "a" * 64]}, {"per_seed": 0}, {"per_seed": True}, {"filter_version": 2},
                        {"attempt": 2}, {"template": "llm-lora/v1"}):
            with self.subTest(changes=changes):
                self.assertTrue(contract.spec_problems(spec(**changes)))

    def test_hashes_ignore_case_and_spacing_and_never_carry_text(self):
        self.assertEqual(contract.input_sha256("  Great   Phone "), contract.input_sha256("great phone"))
        hashes = contract.test_input_hashes("review-sentiment", [{"text": "Great phone", "label": "positive"}, {"text": "great  phone", "label": "positive"}])
        self.assertEqual(hashes, [contract.input_sha256("great phone")])

    def test_rows_have_one_serialisation(self):
        self.assertEqual(contract.jsonl_bytes([{"b": "ए", "a": "1"}]), '{"a":"1","b":"ए"}\n'.encode("utf-8"))

    def test_a_generation_job_cannot_be_submitted_as_a_training_job(self):
        self.assertNotIn(contract.TEMPLATE, TEMPLATES)
        self.assertTrue(job_spec_problems(spec()))


if __name__ == "__main__":
    unittest.main()
