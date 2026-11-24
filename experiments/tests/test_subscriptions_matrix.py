"""The subscriptions matrix script (A9): structure with a stand-in driver; the full run when the Platform code is importable."""

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "payments" / "run_subscriptions_matrix.py"
spec = importlib.util.spec_from_file_location("run_subscriptions_matrix", SCRIPT)
matrix = importlib.util.module_from_spec(spec)
sys.modules["run_subscriptions_matrix"] = matrix
spec.loader.exec_module(matrix)
PLATFORM = Path(__file__).resolve().parents[3] / "ekido-platform"


class Silent:
    """A driver that cannot do anything: every call raises, as the staging driver does where staging is not ready."""

    name, evidence_type = "stand-in", "stand-in"

    def __getattr__(self, name):
        def fail(*a, **k):
            raise NotImplementedError(f"{name} is not available")

        return fail

    def usage_table(self):
        raise RuntimeError("table broken")


class Structure(unittest.TestCase):
    def test_a_driver_that_cannot_do_the_steps_fails_every_case_and_the_whole_run_without_crashing(self):
        result = matrix.run_matrix(Silent())
        self.assertEqual([c["id"] for c in result["cases"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual([c["name"] for c in result["cases"]], [n for _, n in matrix.CASES])
        self.assertFalse(result["passed"])
        self.assertTrue(all(c["error"] and not c["passed"] for c in result["cases"]))
        self.assertIn("error", result["usage_for_dashboard_comparison"][0])  # a broken closing table cannot stop the file
        self.assertTrue(result["prices_provisional"])

    def test_recovery_is_requested_after_each_failed_case(self):
        recovered = []

        class Recovering(Silent):
            def recover(self):
                recovered.append(1)

        matrix.run_matrix(Recovering())
        self.assertEqual(len(recovered), 6)


class CommandLine(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = matrix.main(list(args))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
                err.write(str(exc.code))
        return code, out.getvalue(), err.getvalue()

    def test_it_lists_what_staging_still_needs(self):
        code, out, _ = self.run_main("--list-blockers")
        self.assertEqual(code, 0)
        for needle in ("plan objects", "routes", "SSM", "Checkout"):
            self.assertIn(needle, out)

    def test_an_existing_result_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "r.json"
            existing.write_text("earlier")
            self.assertEqual(self.run_main("--driver", "local", "--out", str(existing))[0], 2)
            self.assertEqual(existing.read_text(), "earlier")

    def test_staging_refuses_without_keys_or_with_a_live_key_and_never_echoes_it(self):
        names = ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET")
        for n in names:
            os.environ.pop(n, None)
        code, _, err = self.run_main("--driver", "staging")
        self.assertNotEqual(code, 0)
        self.assertIn("environment variables", err)
        os.environ.update(EKIDO_STAGING_API_KEY="x", RAZORPAY_TEST_KEY_ID="rzp_live_abc", RAZORPAY_TEST_KEY_SECRET="y")
        try:
            code, _, err = self.run_main("--driver", "staging")
            self.assertNotEqual(code, 0)
            self.assertNotIn("rzp_live_abc", err)
        finally:
            for n in names:
                os.environ.pop(n, None)

    def test_the_staging_driver_fails_every_case_with_a_clear_reason(self):
        os.environ.update(EKIDO_STAGING_API_KEY="x", RAZORPAY_TEST_KEY_ID="rzp_test_abc", RAZORPAY_TEST_KEY_SECRET="s3cret")
        try:
            result = matrix.run_matrix(matrix.StagingDriver("https://example.invalid"))
        finally:
            for n in ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET"):
                os.environ.pop(n, None)
        self.assertFalse(result["passed"])
        self.assertTrue(all("staging cannot do this yet" in (c["error"] or "") for c in result["cases"]))
        self.assertNotIn("s3cret", str(result))


@unittest.skipUnless((PLATFORM / "ekido_platform" / "plans.py").exists(), "needs the ekido-platform checkout (with plans) next to this repo, with its dependencies")
class FullLocalRun(unittest.TestCase):
    def test_all_six_cases_pass_against_the_real_plan_code(self):
        driver = None
        try:
            driver = matrix.LocalDriver(str(PLATFORM))
        except SystemExit as exc:
            self.skipTest(str(exc))
        assert driver is not None
        result = matrix.run_matrix(driver)
        for case in result["cases"]:
            self.assertTrue(case["passed"], f"case {case['id']}: {case['error']} {[k for k in case['checks'] if not k['ok']]}")
        self.assertTrue(result["passed"])
        self.assertEqual(result["driver"], "local")
        self.assertIn("fake gateway", result["evidence_type"])
        self.assertGreaterEqual(len(result["usage_for_dashboard_comparison"]), 5)


if __name__ == "__main__":
    unittest.main()
