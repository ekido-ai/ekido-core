"""The baseline script's scoring, without a model."""
import importlib.util
import functools
import hashlib
import inspect
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recipes_baseline", HERE / "recipes" / "baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class Baseline(unittest.TestCase):
    def test_runtime_fingerprint_uses_decorated_function_source(self):
        @functools.wraps(json.dumps)
        def wrapped(*args, **kwargs):
            return json.dumps(*args, **kwargs)

        expected = hashlib.sha256(Path(inspect.getfile(json.dumps)).read_bytes()).hexdigest()
        self.assertEqual(baseline.source_sha256(wrapped), expected)

    def test_summary_counts_passes_and_keeps_samples(self):
        rows = [{"text": f"review {i}", "label": "positive"} for i in range(4)]
        result = baseline.summarise("review-sentiment", rows, ["positive", "Positive.", "negative", ""])
        self.assertEqual((result["pass_rate"], result["examples"], result["metric"]), (0.5, 4, "accuracy"))
        self.assertEqual([s["passed"] for s in result["samples"]], [True, True, False, False])
        self.assertEqual(len(result["eval_set_hash"]), 64)

    def test_only_licence_checked_models_are_offered(self):
        with self.assertRaises(SystemExit):
            baseline.main([str(HERE / "recipes" / "review-sentiment"), "--model", "Qwen/Qwen2.5-3B-Instruct"])


if __name__ == "__main__":
    unittest.main()
