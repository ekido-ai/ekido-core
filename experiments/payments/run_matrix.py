"""The payment test matrix (ticket A5): eight cases, one result file.

    python -I experiments/payments/run_matrix.py --driver local --out experiments/results/payments/<date>.json
    python -I experiments/payments/run_matrix.py --driver staging --out experiments/results/payments/<date>.json

The cases, in this order:
  1  pay with a UPI test ID                     5  a job that fails the quality check: automatic refund
  2  pay with a test card                       6  a duplicate webhook
  3  a failed payment                           7  a webhook with a bad signature
  4  a job that passes: a payout split          8  reconciliation after all of them

Two drivers run the same cases:
- `local` runs the real Ekido Platform code (`ekido_platform.payments`) in this process against a **fake** Razorpay. It proves
  the cases and the result file work. It says nothing about Razorpay itself. It needs `ekido-platform` on the Python path
  (`PYTHONPATH=<path to ekido-platform>`) and its dependencies; with `-I` Python ignores PYTHONPATH, so give `--platform <path>`.
- `staging` drives the real staging server and Razorpay's **test mode**. Paying needs a person: the script prints the order and waits
  while you pay in Razorpay Checkout with UPI `success@razorpay` or the test card, then it checks what our side recorded. Several of
  its steps need staging routes that do not exist yet; `--list-blockers` prints exactly which. Keys are read from the environment
  (`EKIDO_STAGING_API_KEY`, `RAZORPAY_TEST_KEY_ID`, `RAZORPAY_TEST_KEY_SECRET`) and are never written to the result file or printed.

The result file lists every check of every case with what was expected and what was found, plus a ledger table to compare with the
Razorpay test dashboard by eye (the ticket also wants a screenshot with keys hidden). `passed` is true only if every check passed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import itertools
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CASES = (
    (1, "pay with a UPI test ID"),
    (2, "pay with a test card"),
    (3, "a failed payment"),
    (4, "a job that passes: payout split"),
    (5, "a job that fails the quality check: automatic refund"),
    (6, "a duplicate webhook"),
    (7, "a webhook with a bad signature"),
    (8, "reconciliation after all of them"),
)

STAGING_BLOCKERS = (
    # Checked against the Platform and the Coordinator on 24 Nov: the quotes and orders routes, the Razorpay webhook, the settle and refund
    # routes and the Coordinator's call to them (fiat settlement) now exist. What is still missing:
    "the staging driver itself is not written: a payment has to be made in Razorpay Checkout (test mode) in a browser, so it needs a browser step",
    "the staging settings are not in place: RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET and INTERNAL_TOKEN on the Platform, "
    "PLATFORM_URL and PLATFORM_INTERNAL_TOKEN on the Coordinator (ekido-infra sets none of them)",
    "no route lists the ledger or reconciles (an admin route or a one-off script on the server is needed to compare the ledger with Razorpay)",
    "Razorpay test keys and the webhook secret are not in AWS SSM yet (ticket A1)",
    "a test job that passes and one that fails the quality check must be startable on staging on demand (POST /v1/orgs/{id}/jobs starts a job from a paid order; "
    "a job that fails the quality check on purpose still needs a fault or a recipe for it)",
)


@dataclass
class Case:
    id: int
    name: str
    checks: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    error: str | None = None

    def check(self, what: str, expected, actual) -> bool:
        ok = expected == actual
        self.checks.append({"what": what, "expected": expected, "actual": actual, "ok": ok})
        return ok

    @property
    def passed(self) -> bool:
        return self.error is None and bool(self.checks) and all(c["ok"] for c in self.checks)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "passed": self.passed, "checks": self.checks, "evidence": self.evidence, "error": self.error}


# ---------------------------------------------------------------------------------------------------- the matrix


def run_matrix(driver) -> dict:
    """Runs the eight cases through `driver` and returns the result document. A case that raises is a failed case, never a crash."""
    results: dict[int, Case] = {i: Case(i, n) for i, n in CASES}
    # A last guard: even the closing table must never stop the result file from being written.
    def table():
        try:
            return driver.ledger_table()
        except Exception as exc:
            return [{"error": f"{type(exc).__name__}: {str(exc)[:200]}"}]

    def run(case_id, body):
        case = results[case_id]
        try:
            body(case)
        except Exception as exc:  # the matrix reports a broken case; it does not stop at it
            case.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            recover = getattr(driver, "recover", None)
            if recover is not None:
                try:
                    recover()
                except Exception:  # a recovery that fails must not stop the other cases from running
                    pass  # e.g. roll back a database transaction the failure left open, so the next case can run

    held = {}

    def needs(case_id: int, depends_on: int):
        if depends_on not in held:
            raise RuntimeError(f"depends on case {depends_on}, which did not complete, so its order and payment are not available")
        return held[depends_on]

    def pay(case, method):
        order = driver.create_order(f"matrix-{case.id}")
        case.check("a new order starts CREATED", "CREATED", driver.order_status(order))
        payment = driver.pay(order, method)
        driver.deliver_capture_webhook(order, payment, event_id=f"evt_{case.id}_capture")
        case.check("the payment is held after the capture webhook", "HELD", driver.order_status(order))
        case.check("the ledger holds exactly one CAPTURE of the order's amount", [("CAPTURE", "", driver.order_amount(order))], driver.ledger(order))
        case.evidence.update(order=order, payment=payment, method=method)
        held[case.id] = (order, payment)

    run(1, lambda c: pay(c, "upi"))
    run(2, lambda c: pay(c, "card"))

    def failed(case):
        order = driver.create_order("matrix-3")
        payment = driver.pay(order, "card", fail=True)
        driver.deliver_failed_webhook(order, payment, event_id="evt_3_failed")
        case.check("a failed payment leaves the order CREATED (the customer can try again)", "CREATED", driver.order_status(order))
        case.check("no money is recorded", [], driver.ledger(order))
        retry = driver.pay(order, "upi")
        driver.deliver_capture_webhook(order, retry, event_id="evt_3_retry")
        case.check("a second, successful attempt on the same order is held", "HELD", driver.order_status(order))
        case.evidence.update(order=order, failed_payment=payment, retry_payment=retry)

    run(3, failed)

    def passes(case):
        order, _ = needs(4, 1)
        split = driver.split_for(order)
        driver.settle(order, split)
        case.check("the order is SETTLED", "SETTLED", driver.order_status(order))
        ledger = driver.ledger(order)
        by_kind: dict[str, int] = {}
        for kind, _, amount in ledger:
            by_kind[kind] = by_kind.get(kind, 0) + amount
        allocated = sum(v for k, v in by_kind.items() if k != "CAPTURE")
        case.check("what was paid equals what was allocated, to the paisa", by_kind.get("CAPTURE"), allocated)
        case.check("the provider earnings equal the split", sorted(split.values()), sorted(a for k, p, a in ledger if k == "PROVIDER_EARNING"))
        case.check("no refund was made", False, driver.refunded(order))
        case.evidence.update(order=order, split=split)

    run(4, passes)

    def refunds(case):
        order, payment = needs(5, 2)
        driver.refund(order)
        case.check("the order is REFUNDED", "REFUNDED", driver.order_status(order))
        case.check("Razorpay refunded the full amount", driver.order_amount(order), driver.refunded_amount(payment))
        case.check("the ledger nets to zero", 0, sum(a for _, _, a in driver.ledger(order)))
        driver.refund(order)
        case.check("asking again refunds only once", 1, driver.refund_count(payment))
        case.evidence.update(order=order, payment=payment)

    run(5, refunds)

    def duplicate(case):
        order = driver.create_order("matrix-6")
        payment = driver.pay(order, "upi")
        first = driver.deliver_capture_webhook(order, payment, event_id="evt_6_same")
        again = driver.deliver_capture_webhook(order, payment, event_id="evt_6_same")
        case.check("the first delivery is processed", "held", first)
        case.check("the repeat is acknowledged and ignored", "duplicate", again)
        case.check("the ledger still has one CAPTURE", 1, len(driver.ledger(order)))
        case.evidence.update(order=order, payment=payment)

    run(6, duplicate)

    def bad_signature(case):
        # A forged call claims a payment that Razorpay never made, so there is no real payment behind it: nothing exists at the gateway.
        order = driver.create_order("matrix-7")
        for label, signature in (("a wrong signature", "0" * 64), ("no signature", "")):
            case.check(f"{label} is refused with 401", 401, driver.deliver_forged_capture_webhook(order, event_id="evt_7", signature=signature))
        case.check("nothing was recorded", ["CREATED", []], [driver.order_status(order), driver.ledger(order)])
        case.evidence.update(order=order, note="the forged webhook named a payment that does not exist at Razorpay")

    run(7, bad_signature)

    def reconcile(case):
        report = driver.reconcile()
        case.check("reconciliation finds no difference", True, report.get("ok"))
        for key in ("unknown_payments", "not_held", "amount_mismatch", "refund_mismatch", "missing_at_gateway", "ledger_unbalanced"):
            case.check(f"{key} is empty", [], report.get(key))
        case.evidence.update(report=report)

    run(8, reconcile)

    cases = [results[i].as_dict() for i, _ in CASES]
    return {
        "tool": "experiments/payments/run_matrix.py",
        "driver": driver.name,
        "evidence_type": driver.evidence_type,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": all(c["passed"] for c in cases),
        "cases": cases,
        "summary": {"passed": sum(c["passed"] for c in cases), "failed": sum(not c["passed"] for c in cases)},
        "ledger_for_dashboard_comparison": table(),
        "dashboard_check": "compare ledger_for_dashboard_comparison with the Razorpay test dashboard by hand and attach a screenshot with keys hidden (not done by this script)",
    }


# ---------------------------------------------------------------------------------------------------- the local driver


class LocalDriver:
    """The real Platform payment code against a fake Razorpay, in this process."""

    name = "local"
    evidence_type = "fake gateway: proves the cases and the code paths, says nothing about Razorpay itself"

    SECRET = "matrix-webhook-secret"

    def __init__(self, platform_path: str | None):
        if platform_path:
            sys.path.insert(0, str(Path(platform_path).resolve()))
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from ekido_core.quotes import make_quote
            from ekido_platform import payments
            from ekido_platform.main import Settings, create_app
        except ImportError as exc:
            raise SystemExit(f"the local driver needs the Platform code and its dependencies: {exc}. Use --platform <path to ekido-platform>.")
        self._select, self._payments, self._make_quote = select, payments, make_quote
        self.app = create_app(Settings(database_url="sqlite://", _env_file=None))
        self.session = Session(self.app.state.engine)
        self.gateway = _FakeGateway()
        self.rail = payments.RazorpayRail(self.gateway, self.SECRET)
        self.quote_ids = itertools.count(1)
        self.last_refund_count = 0

    def _quote(self, rows):
        return self._make_quote(recipe_id="ticket-sorter-hinglish", base_model="Qwen/Qwen2.5-0.5B-Instruct", train_rows=rows, test_rows=40, dataset_sha256="a" * 64)

    def create_order(self, label: str) -> str:
        quote = self._quote(100 + 37 * next(self.quote_ids))  # a different quote each time, so each case gets its own order
        order = self.rail.create_order(self.session, org_id="org-matrix", quote_id=label, quote=quote)
        return order.id

    def recover(self):
        self.session.rollback()

    def _order(self, order_id):
        return self.session.get(self._payments.PaymentOrder, order_id)

    def order_status(self, order_id):
        self.session.expire_all()
        return self._order(order_id).status

    def order_amount(self, order_id):
        return self._order(order_id).amount_paise

    def pay(self, order_id, method, fail=False):
        return self.gateway.pay(self._order(order_id).gateway_order_id, method, status="failed" if fail else "captured")

    def _webhook(self, name, payment_id, event_id):
        raw = json.dumps({"event": name, "payload": {"payment": {"entity": self.gateway.payments[payment_id]}}}, separators=(",", ":")).encode()
        return self.rail.handle_webhook(self.session, raw, hmac.new(self.SECRET.encode(), raw, hashlib.sha256).hexdigest(), event_id)

    def deliver_capture_webhook(self, order_id, payment_id, event_id):
        return self._webhook("payment.captured", payment_id, event_id)

    def deliver_failed_webhook(self, order_id, payment_id, event_id):
        return self._webhook("payment.failed", payment_id, event_id)

    def deliver_forged_capture_webhook(self, order_id, event_id, signature):
        order = self._order(order_id)
        entity = {"id": "pay_forged0000", "order_id": order.gateway_order_id, "amount": order.amount_paise, "currency": "INR", "status": "captured"}
        raw = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": entity}}}, separators=(",", ":")).encode()
        try:
            return self.rail.handle_webhook(self.session, raw, signature, event_id)
        except self._payments.PaymentError as exc:
            return exc.status

    def ledger(self, order_id):
        entries = self.session.scalars(self._select(self._payments.LedgerEntry).where(self._payments.LedgerEntry.order_id == order_id).order_by(self._payments.LedgerEntry.kind, self._payments.LedgerEntry.account))
        return [(e.kind, e.account, e.amount_paise) for e in entries]

    def split_for(self, order_id):
        budget = self._order(order_id).quote["provider_budget_paise"]
        return {"provider-a": budget // 3, "provider-b": budget - budget // 3}

    def settle(self, order_id, split):
        self.rail.settle(self.session, order_id, split)

    def refund(self, order_id):
        self.rail.refund(self.session, order_id, "quality check failed")

    def refunded(self, order_id):
        return self.order_status(order_id) == "REFUNDED"

    def refunded_amount(self, payment_id):
        return self.gateway.payments[payment_id]["amount_refunded"]

    def refund_count(self, payment_id):
        return sum(1 for r in self.gateway.refunds.values() if r["payment_id"] == payment_id)

    def reconcile(self):
        now = int(time.time())
        return self.rail.reconcile(self.session, from_ts=now - 3600, to_ts=now + 3600).as_dict()

    def ledger_table(self):
        rows = []
        for order in self.session.scalars(self._select(self._payments.PaymentOrder).order_by(self._payments.PaymentOrder.created_at)):
            rows.append({"order": order.gateway_order_id, "payment": order.gateway_payment_id, "amount_paise": order.amount_paise, "status": order.status,
                         "customer_net_paise": sum(a for kind, _, a in self.ledger(order.id) if kind in ("CAPTURE", "REFUND"))})
        return rows


class _FakeGateway:
    def __init__(self):
        self.orders, self.payments, self.refunds, self.n = {}, {}, {}, itertools.count(1)

    def create_order(self, *, amount_paise, currency, receipt, notes):
        oid = f"order_{next(self.n):04d}"
        self.orders[oid] = {"id": oid, "amount": amount_paise, "currency": currency}
        return dict(self.orders[oid])

    def pay(self, order_id, method, status="captured"):
        pid = f"pay_{next(self.n):04d}"
        self.payments[pid] = {"id": pid, "order_id": order_id, "amount": self.orders[order_id]["amount"], "currency": "INR", "status": status, "method": method,
                              "amount_refunded": 0, "created_at": int(time.time())}
        return pid

    def fetch_payment(self, payment_id):
        return dict(self.payments[payment_id])

    def refund_payment(self, payment_id, amount_paise, *, receipt):
        if receipt not in self.refunds:
            self.payments[payment_id].update(status="refunded", amount_refunded=amount_paise)
            self.refunds[receipt] = {"id": f"rfnd_{next(self.n):04d}", "payment_id": payment_id, "amount": amount_paise}
        return dict(self.refunds[receipt])

    def list_payments(self, *, from_ts, to_ts):
        return [dict(p) for p in self.payments.values()]


# ---------------------------------------------------------------------------------------------------- the staging driver


class StagingDriver:
    """Drives the real staging server and Razorpay's test mode. Built so that it fails loudly, not quietly, where staging cannot yet do a step."""

    name = "staging"
    evidence_type = "real staging server and Razorpay test mode"

    def __init__(self, base_url: str):
        missing = [v for v in ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET") if not os.environ.get(v)]
        if missing:
            raise SystemExit("set these environment variables first (never paste them anywhere): " + ", ".join(missing))
        if not os.environ["RAZORPAY_TEST_KEY_ID"].startswith("rzp_test_"):
            raise SystemExit("RAZORPAY_TEST_KEY_ID must be a test key (rzp_test_...). Live keys are refused.")
        self.base_url = base_url

    def _blocked(self, step: str):
        raise NotImplementedError(f"{step}: staging cannot do this yet. See --list-blockers.")

    def create_order(self, label): self._blocked("creating an order (POST /v1/quotes/{id}/orders)")
    def order_status(self, order): self._blocked("reading an order's status")
    def order_amount(self, order): self._blocked("reading an order's amount")
    def pay(self, order, method, fail=False): self._blocked("paying in Razorpay Checkout (a person pays with UPI success@razorpay or the test card)")
    def deliver_capture_webhook(self, *a, **k): self._blocked("delivering a signed webhook")
    def deliver_failed_webhook(self, *a, **k): self._blocked("delivering a failed-payment webhook")
    def deliver_forged_capture_webhook(self, *a, **k): self._blocked("delivering a forged webhook")
    def ledger(self, order): self._blocked("reading the ledger")
    def split_for(self, order): self._blocked("a job's payout split")
    def settle(self, order, split): self._blocked("settling a passed job")
    def refund(self, order): self._blocked("refunding a failed job")
    def refunded(self, order): self._blocked("reading refund state")
    def refunded_amount(self, payment): self._blocked("reading Razorpay's refund")
    def refund_count(self, payment): self._blocked("counting refunds")
    def reconcile(self): self._blocked("reconciliation")
    def ledger_table(self): return []


# ---------------------------------------------------------------------------------------------------- command line


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--driver", choices=("local", "staging"), default="local")
    parser.add_argument("--out", type=Path, help="result file; refused if it already exists")
    parser.add_argument("--platform", help="path to the ekido-platform checkout (local driver)")
    parser.add_argument("--url", default="https://ekido-staging-api.duckdns.org/sepolia", help="the staging API (staging driver)")
    parser.add_argument("--list-blockers", action="store_true", help="print what staging still needs, then stop")
    args = parser.parse_args(argv)
    if args.list_blockers:
        print("The staging driver cannot run until:")
        for blocker in STAGING_BLOCKERS:
            print(" -", blocker)
        return 0
    if args.out is not None and args.out.exists():
        print(f"{args.out} already exists; choose a new name so an earlier result is never overwritten", file=sys.stderr)
        return 2
    driver = LocalDriver(args.platform) if args.driver == "local" else StagingDriver(args.url)
    result = run_matrix(driver)
    text = json.dumps(result, indent=2, default=str) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    for case in result["cases"]:
        print(f"case {case['id']} {'PASS' if case['passed'] else 'FAIL'}  {case['name']}" + (f"  [{case['error']}]" if case["error"] else ""))
    print(f"{result['summary']['passed']} of {len(result['cases'])} cases passed ({result['driver']} driver)")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
