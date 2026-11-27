# Payment test matrix (A5)

`run_matrix.py` runs the eight payment cases from the ticket and writes one result file. See its docstring for the cases.

## Today: the local driver

```
python -I experiments/payments/run_matrix.py --driver local --platform ../ekido-platform --out experiments/results/payments/local-fake-<date>.json
```

This runs the real Platform payment code against a **fake** Razorpay. It proves the cases, the checks and the result file; it says nothing about Razorpay. `experiments/results/payments/local-fake-20261119.json` is such a run: 8 of 8 cases passed.

The matrix also catches real mistakes in the Platform code: with the webhook signature check switched off case 7 fails, and with the duplicate-event check switched off case 6 fails (the result file is still written, with the failure shown). It does not cover an amount mismatch between the webhook and Razorpay; the Platform's own tests do.

## Razorpay test mode, Platform run locally: the sandbox driver

```
RAZORPAY_TEST_KEY_ID=rzp_test_...  RAZORPAY_TEST_KEY_SECRET=...        # environment only, never a command line or a file in a repo
python -I experiments/payments/run_matrix.py --driver sandbox --platform ../ekido-platform --out experiments/results/payments/sandbox-<date>.json
```

Real Razorpay **test** API (orders, payments, refunds, the payment list), the Platform's payment code running in this process. It opens a page on `http://127.0.0.1:5599/` where **a person** pays each step in Razorpay Checkout (a captcha stops automation, and should). The webhook is delivered by the script itself, signed with a secret made for that run, so Razorpay's own webhook delivery is **not** tested. A live key is refused. This is not the staging server.

### Result of 25 Nov (`sandbox-20261125.json`): 7 of 8 passed

- **Methods actually used: netbanking and wallet.** UPI is not offered on this Razorpay account, and no card was used. So cases 1 and 2 prove "a captured payment is held and recorded", **not** that UPI or card payments work.
- Case 8 (reconciliation) **failed**: one payment made about 18 seconds earlier was reported `missing_at_gateway` because Razorpay's payment list had not caught up; it was in the list shortly after. Fixed in ekido-platform (confirm the payment directly before calling it missing). The result file is kept as it is.
- `sandbox-20261125-gateway-crosscheck.json`: every order in the run's ledger table compared with Razorpay by order id, status and net amount: all match.
- One step was completed by hand: the page lost the report of a payment that had succeeded (a retry inside the same popup), so the real captured payment id was read from Razorpay and given to the runner. The driver now asks Razorpay itself.
- Not done: the comparison with the Razorpay **dashboard** by eye (needs a screenshot).

## On staging: the staging driver

Needs, first: the staging routes and wiring listed by `--list-blockers`, and the Razorpay test keys in AWS SSM (A1). Then, with the keys in the **environment** (never in a command line, a file or a message):

```
EKIDO_STAGING_API_KEY=...  RAZORPAY_TEST_KEY_ID=rzp_test_...  RAZORPAY_TEST_KEY_SECRET=...
python -I experiments/payments/run_matrix.py --driver staging --out experiments/results/payments/<date>.json
```

Paying is done by a person in Razorpay Checkout (test mode): UPI `success@razorpay`, or Razorpay's test card. After the run, compare the `ledger_for_dashboard_comparison` table with the Razorpay test dashboard and attach a screenshot with every key and ID that is not an order or payment id hidden.

The result file refuses to overwrite an earlier one.
