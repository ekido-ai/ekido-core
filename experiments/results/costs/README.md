# T4 training measurements, 21 November 2026

These results support [internal #57](https://github.com/ekido-ai/ekido-internal/issues/57).
Each top-level `<recipe>-<model>.json` is the corresponding raw T4 result from
the private Kaggle run. All five synthetic recipe datasets and both pinned
Qwen models were trained for **20 logical steps** on one Tesla T4. The job used
micro-batch 1, accumulation 8, FP16, gradient checkpointing and SDPA. The
sampling pool was the complete committed recipe dataset, not a distillation
experiment; 20 steps do not necessarily visit every row. These short runs measure throughput; they do not establish model
quality or a final production price.

| Recipe | Base | Loop seconds | Non-padding tokens/s | Peak allocated GiB | GPU seconds per million tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| Ticket sorter | 0.5B | 39.96 | 207.46 | 2.29 | 4820.3 |
| Ticket sorter | 1.5B | 43.19 | 191.95 | 6.41 | 5209.7 |
| Invoice fields | 0.5B | 36.78 | 701.70 | 2.44 | 1425.1 |
| Invoice fields | 1.5B | 43.10 | 598.84 | 6.57 | 1669.9 |
| Product descriptions | 0.5B | 36.64 | 257.91 | 2.26 | 3877.3 |
| Product descriptions | 1.5B | 43.12 | 219.13 | 6.37 | 4563.5 |
| Clinic FAQ | 0.5B | 37.41 | 245.98 | 2.35 | 4065.5 |
| Clinic FAQ | 1.5B | 44.13 | 208.54 | 6.46 | 4795.2 |
| Review sentiment | 0.5B | 37.33 | 155.81 | 2.24 | 6418.2 |
| Review sentiment | 1.5B | 43.51 | 133.66 | 6.35 | 7481.6 |

The timing is the training loop **including checkpoint writes and per-step
logging**, but excludes model loading, dataset preparation and evaluation.
Non-padding tokens include prompts and completions, including repeated rows;
padding-inclusive counts are also recorded. GPU peak allocated and reserved
memory include model allocations and the allocator's cache at measurement start.
The one checkpoint at the end of each 20-step segment affects the throughput;
longer jobs and different checkpoint frequencies may produce different rates.

The last column is arithmetic: `1,000,000 / measured_non_padding_tokens_per_second`.
For an independently sourced hourly rate `R` in a chosen currency, the
corresponding training-loop amount would be `(R / 3600) * GPU_seconds_per_million`,
before any billing minimum, taxes, loading, retries or other overhead. As an
illustration, the [Google Cloud T4 price](https://cloud.google.com/products/compute/gpus-pricing?hl=en)
for Iowa (us-central1), retrieved 21 November 2026, was $0.35 per GPU-hour.
Applying that rate to these measured loops gives $0.1386–$0.7274 per million
non-padding tokens; the per-run calculations are in
`illustrative-gcp-t4-estimate.json`. This is a GPU-only example excluding VM,
storage, networking, taxes, loading, evaluation and retries; it is neither a
Kaggle bill nor an Ekido provider price. No RTX 3060 measurements are present;
the issue is not complete.

The `t4-20261121/` directory retains the execution log, exact pulled notebook,
per-run dataset, spec, evidence and checkpoint manifest. The full checkpoint
tensors were discarded by this benchmark and are not model deliverables. The
core commit is `0fd7b3e32217bc9d9ab6659e72f5925a7d179751`, the worker commit
is `2bfde0d6b4743227900a33d0d140990788425d34`, and the pulled notebook's SHA-256
is `3a1558e7cf7d07a0a342ddb146802bffff11529d5ac837b654473934b02a74bb`.
The pulled notebook matched the submitted source after LF/CRLF normalisation.

Run `python experiments/results/costs/audit.py` from the repository root to
check all ten datasets against the embedded source snapshot, model revisions,
checkpoint manifests, saved measurements and throughput arithmetic. The audit
does not independently measure GPU time or establish an external tariff.
