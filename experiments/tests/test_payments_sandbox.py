"""The sandbox driver of the payment matrix: the local checkout page and its safety checks. No call to Razorpay is made here."""

import importlib.util
import json
import os
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "payments" / "run_matrix.py"
spec = importlib.util.spec_from_file_location("run_matrix_sandbox", PATH)
matrix = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = matrix  # dataclasses look the module up by name
spec.loader.exec_module(matrix)


class CheckoutPage(unittest.TestCase):
    def setUp(self):
        self.checkout = matrix._Checkout("rzp_test_abc", 0, 5)
        self.base = f"http://127.0.0.1:{self.checkout.server.server_port}"
        self.addCleanup(self.checkout.server.server_close)
        self.addCleanup(self.checkout.server.shutdown)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.read().decode()

    def post(self, body):
        urllib.request.urlopen(urllib.request.Request(self.base + "/done", data=json.dumps(body).encode(), method="POST"), timeout=5).read()

    def test_a_step_is_offered_and_only_its_own_payment_id_completes_it(self):
        result = {}
        worker = threading.Thread(target=lambda: result.setdefault("payment", self.checkout.pay("order_123", "pay by card")))
        worker.start()
        for _ in range(100):
            step = json.loads(self.get("/current"))
            if step.get("id"):
                break
        self.assertEqual((step["number"], step["order"], step["instruction"], step["key_id"]), (1, "order_123", "pay by card", "rzp_test_abc"))
        self.post({"id": "step99", "payment": "pay_other"})  # a stale or forged step id
        self.post({"id": step["id"], "payment": "not-a-payment"})
        self.assertTrue(worker.is_alive())
        self.post({"id": step["id"], "payment": "pay_ABC123"})
        worker.join(timeout=5)
        self.assertEqual(result["payment"], "pay_ABC123")
        self.assertEqual(json.loads(self.get("/current")), {})

    def test_it_listens_only_on_this_machine_and_never_serves_the_secret(self):
        self.assertEqual(self.checkout.server.server_address[0], "127.0.0.1")
        page = self.get("/")
        self.assertIn("checkout.razorpay.com", page)
        self.assertNotIn("rzp_test_abc", page)  # the key id arrives with a step; there is no secret anywhere in the page

    def test_a_payment_the_page_never_reported_is_found_by_asking_razorpay(self):
        self.checkout.probe_every = 0.05
        answers = iter([None, None, "pay_FOUND1"])
        self.assertEqual(self.checkout.pay("order_1", "pay", probe=lambda: next(answers)), "pay_FOUND1")
        self.assertEqual(json.loads(self.get("/current")), {})  # the step is closed, so a late page report is ignored

    def test_nobody_paying_is_a_clear_failure_not_a_hang(self):
        self.checkout.wait_seconds = 0.2
        with self.assertRaises(RuntimeError):
            self.checkout.pay("order_1", "pay")


class SandboxRefusals(unittest.TestCase):
    def test_it_needs_test_keys_in_the_environment_and_refuses_a_live_key(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as caught:
            matrix.SandboxDriver(None)
        self.assertIn("RAZORPAY_TEST_KEY_ID", str(caught.exception))
        with patch.dict(os.environ, {"RAZORPAY_TEST_KEY_ID": "rzp_live_x", "RAZORPAY_TEST_KEY_SECRET": "s3cr3t"}), self.assertRaises(SystemExit) as caught:
            matrix.SandboxDriver(None)
        self.assertIn("test key", str(caught.exception))
        self.assertNotIn("s3cr3t", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
