# Payment test matrix (A5)

`run_matrix.py` runs the eight payment cases from the ticket and writes one result file. See its docstring for the cases.

## Today: the local driver

```
python -I experiments/payments/run_matrix.py --driver local --platform ../ekido-platform --out experiments/results/payments/local-fake-<date>.json
```

This runs the real Platform payment code against a **fake** Razorpay. It proves the cases, the checks and the result file; it says nothing about Razorpay. `experiments/results/payments/local-fake-20261119.json` is such a run: 8 of 8 cases passed.

The matrix also catches real mistakes in the Platform code: with the webhook signature check switched off case 7 fails, and with the duplicate-event check switched off case 6 fails (the result file is still written, with the failure shown). It does not cover an amount mismatch between the webhook and Razorpay; the Platform's own tests do.

## On staging: the staging driver

Needs, first: the staging routes and wiring listed by `--list-blockers`, and the Razorpay test keys in AWS SSM (A1). Then, with the keys in the **environment** (never in a command line, a file or a message):

```
EKIDO_STAGING_API_KEY=...  RAZORPAY_TEST_KEY_ID=rzp_test_...  RAZORPAY_TEST_KEY_SECRET=...
python -I experiments/payments/run_matrix.py --driver staging --out experiments/results/payments/<date>.json
```

Paying is done by a person in Razorpay Checkout (test mode): UPI `success@razorpay`, or Razorpay's test card. After the run, compare the `ledger_for_dashboard_comparison` table with the Razorpay test dashboard and attach a screenshot with every key and ID that is not an order or payment id hidden.

The result file refuses to overwrite an earlier one.
