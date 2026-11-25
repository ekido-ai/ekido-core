# distill-gen/v1: the contract

Distillation is two jobs with the customer's approval between them. A **teacher** writes training rows from a few seed examples; the customer
looks at a sample; a **student** is then trained on the approved set with the ordinary `llm-lora/v1` job. This page is what the Platform,
the Coordinator, the provider runtime and the verifier build against. Code: `ekido_core.distill_contract`. Schema:
`docs/schemas/distill_gen_spec.schema.json`.

## Who builds what

| Part | Where | Ticket |
|---|---|---|
| Spec and rules | ekido-core | this page |
| Generation on the device | ekido-workers `runtime/` | internal #133 |
| Check of the generated file | ekido-workers `verifier/` | internal #141 |
| Quote, payment, review, approval, refund | ekido-platform | internal #154 |
| Placement, files, reports to the Platform | ekido-coordinator | internal #154 |
| Review screen | ekido-web | internal #148 |

## The flow

1. The customer uploads **30 seed rows and 20 test rows** (50 in all) in the recipe's two columns.
2. One quote covers both jobs. The customer pays once.
3. Generation job (`distill-gen/v1`) → `generated.jsonl` + `generation_report.json`.
4. The verifier checks the file. A failed check, or a failed job, refunds the order in full.
5. The customer sees **20 random generated rows**, marks bad ones, and approves, regenerates (once) or rejects (full refund).
6. Training job (`llm-lora/v1`) on seeds + generated rows, minus the removed ones. The test set is the customer's 20 test rows only.
7. The normal quality gate settles or refunds the order.

## The spec

```json
{
  "template": "distill-gen/v1",
  "recipe_id": "review-sentiment",
  "teacher": {"id": "Qwen/Qwen2.5-7B-Instruct", "revision": "a09a35458c702b33eeacc393d103063234e8bc28", "quantization": "4bit"},
  "seeds": {"sha256": "<of seeds.jsonl>", "bytes": 2048, "rows": 30},
  "test_input_sha256": ["<sorted, unique>"],
  "per_seed": 4,
  "generation_seed": 42,
  "max_new_tokens": 96,
  "attempts": 3,
  "filter_version": 1,
  "attempt": 0
}
```

- Unknown fields are refused. `distill_contract.spec_problems(spec)` must return `[]`.
- **The provider never receives the test text.** It gets `seeds.jsonl` and the hashes in `test_input_sha256`
  (`distill_contract.input_sha256`: spaces collapsed, case folded, SHA-256).
- `seeds.jsonl` and `generated.jsonl` use `distill_contract.jsonl_bytes`: compact, key-sorted UTF-8, one LF per row. Hashes are over those bytes.
- `attempt` is 0 for the first generation and 1 for the one regeneration; the Platform changes `generation_seed` with it.
- It is not in `job_spec.TEMPLATES`: `POST /jobs` keeps refusing it. It has its own route.

## What the device does (runtime)

- Loads the teacher at the pinned revision, 4-bit, and calls the existing filtered generator seed by seed.
- Excludes a generated input that matches a seed input, an earlier generated input, or a hash in `test_input_sha256`.
- **Progress is counted in seeds.** After each seed it saves the progress file and uploads it through the Coordinator, so another device
  resumes from the next seed.
- Writes `generated.jsonl` (the recipe's two columns, nothing else) and `generation_report.json` with at least `settings`,
  `completed_seeds`, `generated_rows`, `filter_counts`, `generated_sha256`, `generated_bytes`.
- Fails if no row survives.

## What the verifier does

Runs `ekido_verifier.generated_rows.check_generated_jsonl(data, recipe_id, test_input_hashes=..., seed_inputs=...)` and
`check_report(report, verdict)`. One violating row fails the file. It does not re-run generation: it proves the rows pass the filters, not
which model wrote them.

## Coordinator and Platform

All service routes are internal and need the internal token.

| Call | Body | Meaning |
|---|---|---|
| Platform → Coordinator `POST /distillations` | `{"distillation_id", "spec", "seeds_jsonl"}` | returns `{"job_id"}`; 400/409/422 with `detail` if refused |
| Coordinator → Platform `POST /internal/distillations/{id}/generated` | `{"rows_jsonl", "passed", "reasons"}` | after the verifier's check; safe to repeat |
| Coordinator → Platform `POST /internal/distillations/{id}/failed` | `{"reason"}` | no device, or the job failed: full refund; safe to repeat |

- Platform states: `GENERATING → REVIEW → APPROVED → TRAINING`, or `REJECTED`, or `FAILED`. A generation with no report in 6 hours is failed
  and refunded.
- The Platform checks columns and test overlap itself as well; it does not rely on the verifier alone.
- Placement: only a device whose memory probe can load the teacher in 4-bit (a T4-class GPU today).
- The generation job is not linked to the payment order, so training settlement ignores it.

## Done means

On staging, with a real device: upload 30 + 20 → pay → generate (kill and resume once) → check → review with removals → approve → train →
quality gate passes or refunds. A rejected set refunds in full. Raw evidence under `experiments/results/`.

## Open, to be decided by Piyush

1. **What the generation provider is paid**, and from which part of the order. Until it is decided, v1 on staging pays nothing for generation.
2. Whether cross-device resume may slip past the freeze (a restart from zero would then be stated in the report).

## Changes needed in work already written

- Runtime (#133): take `test_input_sha256` instead of test rows; hash and write rows with `jsonl_bytes`; teacher from the spec.
- Platform (#154): build the spec exactly as above (`seeds` object, `per_seed`, `teacher`; drop `target_rows`), send `seeds_jsonl`.
- Verifier (#141): none; it already accepts hashes.
