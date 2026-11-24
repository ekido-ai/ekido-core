"""The payment matrix script (A5): its structure is tested with stand-in drivers; the full run is tested when the Platform code is importable."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "payments" / "run_matrix.py"
spec = importlib.util.spec_from_file_location("run_matrix", SCRIPT)
run_matrix = importlib.util.module_from_spec(spec)
sys.modules["run_matrix"] = run_matrix
spec.loader.exec_module(run_matrix)
PLATFORM = Path(__file__).resolve().parents[3] / "ekido-platform"


class GoodDriver:
    """A tiny in-memory stand-in that behaves correctly."""

    name, evidence_type = "stand-in", "stand-in"

    def __init__(self):
        self.orders, self.rows, self.refunds, self.seen = {}, {}, {}, set()

    def create_order(self, label):
        oid = f"o{len(self.orders)}"
        self.orders[oid] = {"status": "CREATED", "amount": 100}
        self.rows[oid] = []
        return oid

    def order_status(self, o): return self.orders[o]["status"]
    def order_amount(self, o): return self.orders[o]["amount"]
    def pay(self, o, method, fail=False): return f"p-{o}-{len(self.seen)}"

    def deliver_capture_webhook(self, o, p, event_id):
        if event_id in self.seen:
            return "duplicate"
        self.seen.add(event_id)
        self.orders[o]["status"] = "HELD"
        self.rows[o].append(("CAPTURE", "", 100))
        return "held"

    def deliver_failed_webhook(self, o, p, event_id):
        self.seen.add(event_id)
        return "failed_recorded"

    def deliver_forged_capture_webhook(self, o, event_id, signature): return 401
    def ledger(self, o): return list(self.rows[o])
    def split_for(self, o): return {"a": 40, "b": 60}

    def settle(self, o, split):
        self.orders[o]["status"] = "SETTLED"
        self.rows[o] += [("PROVIDER_EARNING", k, v) for k, v in split.items()]

    def refund(self, o):
        if self.orders[o]["status"] != "REFUNDED":
            self.orders[o]["status"] = "REFUNDED"
            self.rows[o].append(("REFUND", "", -100))
            self.refunds[o] = self.refunds.get(o, 0) + 1

    def refunded(self, o): return self.orders[o]["status"] == "REFUNDED"
    def refunded_amount(self, p): return 100
    def refund_count(self, p): return 1
    def reconcile(self): return {"ok": True, **{k: [] for k in ("unknown_payments", "not_held", "amount_mismatch", "refund_mismatch", "missing_at_gateway", "ledger_unbalanced")}}
    def ledger_table(self): return []


class MatrixStructure(unittest.TestCase):
    def test_a_well_behaved_driver_passes_all_eight_cases(self):
        # the stand-in is not meant to be perfect; these cases only need it to answer the way the real code does
        result = run_matrix.run_matrix(GoodDriver())
        self.assertEqual([c["id"] for c in result["cases"]], list(range(1, 9)))
        self.assertEqual([c["name"] for c in result["cases"]], [n for _, n in run_matrix.CASES])
        self.assertTrue(all(c["checks"] for c in result["cases"]))
        for case in result["cases"]:
            self.assertEqual(case["passed"], not case["error"] and all(k["ok"] for k in case["checks"]))

    def test_a_driver_that_answers_wrongly_fails_that_case_and_the_whole_run(self):
        class Wrong(GoodDriver):
            def deliver_capture_webhook(self, o, p, event_id):
                return "held"  # never says "duplicate"

        result = run_matrix.run_matrix(Wrong())
        failed = [c["id"] for c in result["cases"] if not c["passed"]]
        self.assertIn(6, failed)
        self.assertFalse(result["passed"])
        self.assertEqual(result["summary"]["passed"] + result["summary"]["failed"], 8)

    def test_a_step_that_raises_is_a_failed_case_not_a_crash(self):
        class Broken(GoodDriver):
            def settle(self, o, split):
                raise RuntimeError("boom")

        result = run_matrix.run_matrix(Broken())
        case4 = result["cases"][3]
        self.assertFalse(case4["passed"])
        self.assertIn("boom", case4["error"])
        self.assertEqual(len(result["cases"]), 8)  # the other cases still ran

    def test_a_failure_triggers_recovery_and_a_broken_closing_table_cannot_stop_the_result(self):
        recovered = []

        class Fragile(GoodDriver):
            def deliver_capture_webhook(self, o, p, event_id):
                raise RuntimeError("transaction left open")

            def recover(self):
                recovered.append(1)

            def ledger_table(self):
                raise RuntimeError("session is broken")

        result = run_matrix.run_matrix(Fragile())
        self.assertGreaterEqual(len(recovered), 1)  # the driver was told to recover after a failed case
        self.assertEqual(len(result["cases"]), 8)
        self.assertIn("error", result["ledger_for_dashboard_comparison"][0])

    def test_a_case_with_no_checks_cannot_pass(self):
        self.assertFalse(run_matrix.Case(1, "x").passed)

    def test_the_result_never_contains_the_secrets_it_was_given(self):
        os.environ["RAZORPAY_TEST_KEY_SECRET"] = "super-secret-value"
        try:
            text = json.dumps(run_matrix.run_matrix(GoodDriver()))
        finally:
            del os.environ["RAZORPAY_TEST_KEY_SECRET"]
        self.assertNotIn("super-secret-value", text)


class CommandLine(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = run_matrix.main(list(args))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
                err.write(str(exc.code))
        return code, out.getvalue(), err.getvalue()

    def test_it_lists_what_staging_still_needs(self):
        code, out, _ = self.run_main("--list-blockers")
        self.assertEqual(code, 0)
        for needle in ("orders", "settle", "SSM", "reconcile"):
            self.assertIn(needle, out)

    def test_an_existing_result_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "result.json"
            existing.write_text("earlier result")
            code, _, err = self.run_main("--driver", "local", "--out", str(existing))
            self.assertEqual(code, 2)
            self.assertEqual(existing.read_text(), "earlier result")

    def test_staging_refuses_to_start_without_keys_or_with_a_live_key(self):
        for name in ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET"):
            os.environ.pop(name, None)
        code, _, err = self.run_main("--driver", "staging")
        self.assertNotEqual(code, 0)
        self.assertIn("environment variables", err)
        os.environ.update(EKIDO_STAGING_API_KEY="x", RAZORPAY_TEST_KEY_ID="rzp_live_abc", RAZORPAY_TEST_KEY_SECRET="y")
        try:
            code, _, err = self.run_main("--driver", "staging")
            self.assertNotEqual(code, 0)
            self.assertIn("test key", err)
            self.assertNotIn("rzp_live_abc", err)
        finally:
            for name in ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET"):
                os.environ.pop(name, None)

    def test_the_staging_driver_fails_every_case_loudly_until_staging_can_do_the_steps(self):
        os.environ.update(EKIDO_STAGING_API_KEY="x", RAZORPAY_TEST_KEY_ID="rzp_test_abc", RAZORPAY_TEST_KEY_SECRET="y")
        try:
            result = run_matrix.run_matrix(run_matrix.StagingDriver("https://example.invalid"))
        finally:
            for name in ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET"):
                os.environ.pop(name, None)
        self.assertFalse(result["passed"])
        for case in result["cases"]:
            self.assertTrue("staging cannot do this yet" in (case["error"] or "") or "depends on case" in (case["error"] or ""), case["error"])
        self.assertIn("depends on case 1", result["cases"][3]["error"])  # a later case says why, instead of a bare KeyError


@unittest.skipUnless((PLATFORM / "ekido_platform" / "payments.py").exists(), "needs the ekido-platform checkout next to this repo, with its dependencies")
class FullLocalRun(unittest.TestCase):
    def test_all_eight_cases_pass_against_the_real_platform_code(self):
        driver = None
        try:
            driver = run_matrix.LocalDriver(str(PLATFORM))
        except SystemExit as exc:
            self.skipTest(str(exc))
        assert driver is not None
        result = run_matrix.run_matrix(driver)
        for case in result["cases"]:
            self.assertTrue(case["passed"], f"case {case['id']}: {case['error']} {[k for k in case['checks'] if not k['ok']]}")
        self.assertTrue(result["passed"])
        self.assertEqual(result["driver"], "local")
        self.assertIn("fake gateway", result["evidence_type"])
        self.assertEqual(len(result["ledger_for_dashboard_comparison"]), 5)  # five orders: cases 1, 2, 3, 6 and 7
        for row in result["ledger_for_dashboard_comparison"]:
            self.assertIn(row["status"], ("SETTLED", "REFUNDED", "HELD", "CREATED"))


if __name__ == "__main__":
    unittest.main()
