"""The subscriptions test matrix (ticket A9): six cases, one result file.

    python -I experiments/payments/run_subscriptions_matrix.py --driver local --platform ../ekido-platform --out experiments/results/payments/subscriptions-local-fake-<date>.json
    python -I experiments/payments/run_subscriptions_matrix.py --driver staging --out experiments/results/payments/subscriptions-<date>.json

The cases, in this order:
  1  subscribe to each plan (Starter and Business)      4  cancel
  2  renewal                                            5  hitting the free-tier limit
  3  failed renewal                                     6  upgrade

It follows `run_matrix.py` (A5): the same two drivers, the same result file shape, the same rules (a case that raises is a failed case, the
file refuses to overwrite, keys only from the environment and never written). The `local` driver runs the real Platform plan code
(`ekido_platform.plans`, with the signed webhook route of `ekido_platform.payments`) against a **fake** Razorpay and a clock the script moves.
It proves the cases and says nothing about Razorpay. The `staging` driver needs the Razorpay plan objects, the plan routes and the keys;
`--list-blockers` prints what is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import itertools
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location("run_matrix_a5", Path(__file__).with_name("run_matrix.py"))
base = importlib.util.module_from_spec(_spec)
sys.modules["run_matrix_a5"] = base
_spec.loader.exec_module(base)
Case = base.Case

CASES = (
    (1, "subscribe to each plan"),
    (2, "renewal"),
    (3, "failed renewal"),
    (4, "cancel"),
    (5, "hitting the free-tier limit"),
    (6, "upgrade"),
)

STAGING_BLOCKERS = (
    "the Razorpay test dashboard needs two plan objects (Starter and Business), and their ids in the Platform's settings",
    "the Platform has no routes for plans yet (/v1/orgs/{id}/plan, subscribe, cancel, change): the API contract has none",
    "nothing calls the plan limits from the job start or the hosted-model gateway yet",
    "Razorpay test keys and the webhook secret are not in AWS SSM yet (ticket A1)",
    "a person must pay the first charge in Razorpay Checkout (test mode), and renewals and failed renewals need Razorpay's test clock or a test subscription with a short period",
)

START = datetime(2026, 11, 1, tzinfo=timezone.utc)


def run_matrix(driver) -> dict:
    results = {i: Case(i, n) for i, n in CASES}

    def table():
        try:
            return driver.usage_table()
        except Exception as exc:
            return [{"error": f"{type(exc).__name__}: {str(exc)[:200]}"}]

    def run(case_id, body):
        case = results[case_id]
        try:
            body(case)
        except Exception as exc:
            case.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            recover = getattr(driver, "recover", None)
            if recover is not None:
                try:
                    recover()
                except Exception:  # a recovery that fails must not stop the other cases from running
                    pass

    def subscribe_each(case):
        for plan in ("starter", "business"):
            org = f"org-sub-{plan}"
            out = driver.subscribe(org, plan)
            case.check(f"{plan}: a new subscription starts pending", "PENDING", out["status"])
            case.check(f"{plan}: no benefits before the first charge", "free", driver.plan(org))
            case.check(f"{plan}: Razorpay was asked for the {plan} plan", plan, driver.razorpay_plan_of(out["subscription_id"]))
            driver.charge(out["subscription_id"], START)
            case.check(f"{plan}: after the first charge and its webhook the plan is active", plan, driver.plan(org))
        case.check("a team that already subscribes cannot start a second subscription", "ALREADY_SUBSCRIBED", driver.try_subscribe("org-sub-starter", "business"))

    run(1, subscribe_each)

    def renewal(case):
        org = "org-renew"
        sid = driver.subscribe(org, "starter")["subscription_id"]
        driver.charge(sid, START)
        for _ in range(driver.jobs_included("starter")):
            driver.record_job(org, "small")
        case.check("the period's included jobs are used up", False, driver.job_included(org, "small"))
        driver.set_clock(START + timedelta(days=30, hours=1))
        case.check("after the period ends and before the renewal is confirmed, no benefits", "free", driver.plan(org))
        driver.charge(sid, START + timedelta(days=30))
        case.check("after the renewal is confirmed the plan is active again", "starter", driver.plan(org))
        case.check("a new period gives a fresh allowance", True, driver.job_included(org, "small"))
        driver.set_clock(START)

    run(2, renewal)

    def failed_renewal(case):
        org = "org-failed"
        sid = driver.subscribe(org, "starter")["subscription_id"]
        driver.charge(sid, START)
        driver.set_gateway_status(sid, "pending")
        case.check("Razorpay says the renewal charge failed (pending): synced as past due", "synced_past_due", driver.deliver_event("subscription.pending", sid, "evt_fr_1"))
        case.check("a past-due team has no paid benefits", "free", driver.plan(org))
        driver.set_gateway_status(sid, "halted")
        case.check("retries ran out (halted): synced as halted", "synced_halted", driver.deliver_event("subscription.halted", sid, "evt_fr_2"))
        case.check("a halted team is still on free", "free", driver.plan(org))
        driver.charge(sid, START + timedelta(days=3), event="subscription.charged", event_id="evt_fr_3")
        case.check("when the customer pays, the plan comes back", "starter", driver.plan(org))
        case.check("the same webhook delivered twice changes nothing", "duplicate", driver.deliver_event("subscription.halted", sid, "evt_fr_2"))

    run(3, failed_renewal)

    def cancel(case):
        org = "org-cancel"
        sid = driver.subscribe(org, "starter")["subscription_id"]
        driver.charge(sid, START)
        out = driver.cancel(org)
        case.check("cancel is requested for the end of the paid period", True, out["cancel_at_period_end"])
        case.check("Razorpay was told to cancel at the end of the cycle", True, driver.cancel_at_cycle_end_sent(sid))
        case.check("the team keeps the plan it paid for", "starter", driver.plan(org))
        driver.cancel(org)
        case.check("cancelling twice sends only one request to Razorpay", 1, driver.cancel_calls(sid))
        driver.set_gateway_status(sid, "cancelled")
        case.check("when Razorpay ends it, the team drops to free", "synced_cancelled", driver.deliver_event("subscription.cancelled", sid, "evt_c_1"))
        case.check("after the end the plan is free", "free", driver.plan(org))

    run(4, cancel)

    def free_limit(case):
        org = "org-free"
        case.check("a new team is on free", "free", driver.plan(org))
        case.check("the first small job is included", True, driver.job_included(org, "small"))
        driver.record_job(org, "small")
        case.check("the second small job is not included (pay the fixed price instead)", False, driver.job_included(org, "small"))
        case.check("a medium job is not included on free", False, driver.job_included(org, "medium"))
        case.check("hosted requests up to the monthly allowance are served", 0, driver.use_requests(org, driver.requests_included("free")))
        case.check("the next hosted request is refused and points at an upgrade", "REQUEST_LIMIT:starter", driver.try_request(org))
        driver.set_clock(datetime(2026, 12, 1, tzinfo=timezone.utc))
        case.check("a new calendar month restores the allowance", True, driver.try_request(org) == "ok")
        driver.set_clock(START)

    run(5, free_limit)

    def upgrade(case):
        org = "org-upgrade"
        sid = driver.subscribe(org, "starter")["subscription_id"]
        driver.charge(sid, START)
        driver.record_job(org, "small")
        driver.use_requests(org, 100)
        case.check("on starter a large job is not included", False, driver.job_included(org, "large"))
        out = driver.change_plan(org, "business")
        case.check("the plan changes now", "business", out["plan"])
        case.check("Razorpay moved the subscription to the business plan", "business", driver.razorpay_plan_of(sid))
        case.check("business includes the large size", True, driver.job_included(org, "large"))
        case.check("this period's usage was kept (1 job, 100 requests)", {"jobs": 1, "requests": 100}, driver.usage(org))

    run(6, upgrade)

    cases = [results[i].as_dict() for i, _ in CASES]
    return {
        "tool": "experiments/payments/run_subscriptions_matrix.py",
        "driver": driver.name,
        "evidence_type": driver.evidence_type,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": all(c["passed"] for c in cases),
        "cases": cases,
        "summary": {"passed": sum(c["passed"] for c in cases), "failed": sum(not c["passed"] for c in cases)},
        "usage_for_dashboard_comparison": table(),
        "prices_provisional": True,
        "dashboard_check": "compare with the subscriptions list in the Razorpay test dashboard by hand and attach a screenshot with keys hidden (not done by this script)",
    }


class _FakeSubscriptions:
    def __init__(self):
        self.subs, self.calls, self.n = {}, [], itertools.count(1)

    def create_subscription(self, *, plan_id, total_count, notes):
        sid = f"sub_{next(self.n):03d}"
        self.subs[sid] = {"id": sid, "plan_id": plan_id, "status": "created", "current_start": None, "current_end": None, "short_url": f"https://rzp.io/{sid}"}
        return dict(self.subs[sid])

    def fetch_subscription(self, subscription_id):
        return dict(self.subs[subscription_id])

    def cancel_subscription(self, subscription_id, *, at_cycle_end):
        self.calls.append(("cancel", subscription_id, at_cycle_end))
        return dict(self.subs[subscription_id])

    def update_subscription(self, subscription_id, *, plan_id):
        self.calls.append(("update", subscription_id, plan_id))
        self.subs[subscription_id]["plan_id"] = plan_id
        return dict(self.subs[subscription_id])


class LocalDriver:
    name = "local"
    evidence_type = "fake gateway and a script-controlled clock: proves the cases and the code paths, says nothing about Razorpay itself"
    SECRET = "subscriptions-matrix-secret"

    def __init__(self, platform_path: str | None):
        if platform_path:
            sys.path.insert(0, str(Path(platform_path).resolve()))
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from ekido_platform import payments, plans
            from ekido_platform.main import Settings, create_app
        except ImportError as exc:
            raise SystemExit(f"the local driver needs the Platform code (with plans) and its dependencies: {exc}. Use --platform <path to ekido-platform>.")
        self._select, self._plans, self._payments = select, plans, payments
        self.gateway = _FakeSubscriptions()
        self.app = create_app(Settings(database_url="sqlite://", _env_file=None))
        self.session = Session(self.app.state.engine)
        self.clock = START
        self.rzp = {"starter": "plan_rzp_starter", "business": "plan_rzp_business"}
        self.service = plans.PlansService(self.gateway, self.rzp, now=lambda: self.clock)
        self.rail = payments.RazorpayRail(self.gateway, self.SECRET, on_subscription_event=self.service.sync_subscription)

    def recover(self):
        self.session.rollback()

    def set_clock(self, when):
        self.clock = when

    def subscribe(self, org, plan):
        return self.service.subscribe(self.session, org, plan)

    def try_subscribe(self, org, plan):
        try:
            self.service.subscribe(self.session, org, plan)
            return "subscribed"
        except self._payments.PaymentError as exc:
            return exc.code

    def razorpay_plan_of(self, sid):
        remote = self.gateway.subs[sid]["plan_id"]
        return next(k for k, v in self.rzp.items() if v == remote)

    def charge(self, sid, start, event="subscription.activated", event_id=None):
        self.gateway.subs[sid].update(status="active", current_start=int(start.timestamp()), current_end=int((start + timedelta(days=30)).timestamp()))
        return self.deliver_event(event, sid, event_id or f"evt_{sid}_{int(start.timestamp())}")

    def set_gateway_status(self, sid, status):
        self.gateway.subs[sid]["status"] = status

    def deliver_event(self, event, sid, event_id):
        raw = json.dumps({"event": event, "payload": {"subscription": {"entity": {"id": sid}}}}, separators=(",", ":")).encode()
        return self.rail.handle_webhook(self.session, raw, hmac.new(self.SECRET.encode(), raw, hashlib.sha256).hexdigest(), event_id)

    def plan(self, org):
        self.session.expire_all()
        return self.service.effective_plan(self.session, org).id

    def jobs_included(self, plan):
        return self._plans.PLANS[plan].jobs_included

    def requests_included(self, plan):
        return self._plans.PLANS[plan].requests_included

    def job_included(self, org, tier):
        return self.service.job_allowance(self.session, org, tier).included

    def record_job(self, org, tier):
        self.service.record_job(self.session, org, tier)

    def use_requests(self, org, n):
        return self.service.consume_requests(self.session, org, n)

    def try_request(self, org):
        try:
            self.service.consume_requests(self.session, org, 1)
            return "ok"
        except self._plans.PlanLimit as exc:
            return f"{exc.code}:{exc.upgrade_to}"

    def cancel(self, org):
        return self.service.cancel(self.session, org)

    def cancel_calls(self, sid):
        return sum(1 for c in self.gateway.calls if c[0] == "cancel" and c[1] == sid)

    def cancel_at_cycle_end_sent(self, sid):
        return any(c[0] == "cancel" and c[1] == sid and c[2] is True for c in self.gateway.calls)

    def change_plan(self, org, plan):
        return self.service.change_plan(self.session, org, plan)

    def usage(self, org):
        rows = self.session.scalars(self._select(self._plans.PlanUsage).where(self._plans.PlanUsage.org_id == org))
        return {r.kind: r.used for r in rows}

    def usage_table(self):
        out = []
        for row in self.session.scalars(self._select(self._plans.TeamPlan).order_by(self._plans.TeamPlan.created_at)):
            out.append({"team": row.org_id, "plan": row.plan, "status": row.status, "subscription": row.subscription_id, "effective_plan": self.service.effective_plan(self.session, row.org_id).id})
        return out


class StagingDriver:
    name = "staging"
    evidence_type = "real staging server and Razorpay test mode"

    def __init__(self, base_url: str):
        missing = [v for v in ("EKIDO_STAGING_API_KEY", "RAZORPAY_TEST_KEY_ID", "RAZORPAY_TEST_KEY_SECRET") if not os.environ.get(v)]
        if missing:
            raise SystemExit("set these environment variables first (never paste them anywhere): " + ", ".join(missing))
        if not os.environ["RAZORPAY_TEST_KEY_ID"].startswith("rzp_test_"):
            raise SystemExit("RAZORPAY_TEST_KEY_ID must be a test key (rzp_test_...). Live keys are refused.")
        self.base_url = base_url

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def blocked(*args, **kwargs):
            raise NotImplementedError(f"{name}: staging cannot do this yet. See --list-blockers.")

        return blocked

    def recover(self):
        return None  # nothing to roll back on staging

    def usage_table(self):
        return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--driver", choices=("local", "staging"), default="local")
    parser.add_argument("--out", type=Path, help="result file; refused if it already exists")
    parser.add_argument("--platform", help="path to the ekido-platform checkout (local driver)")
    parser.add_argument("--url", default="https://ekido-staging-api.duckdns.org/sepolia")
    parser.add_argument("--list-blockers", action="store_true")
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
