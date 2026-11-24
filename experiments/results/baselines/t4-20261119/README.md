# Recipe baseline matrix on T4, 19 November 2026

These are ten new, untrained base-model runs for
[issue #29](https://github.com/ekido-ai/ekido-internal/issues/29), using the
current five committed recipe test sets. In particular, product descriptions
uses the held-out product split introduced by #73, not the older split.

| Recipe | Examples | 0.5B pass rate | 1.5B pass rate | 0.5B mean score | 1.5B mean score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ticket sorter | 100 | 0.35 | 0.65 | 0.35 | 0.65 |
| Invoice fields | 50 | 0.00 | 0.00 | 0.696 | 0.712 |
| Product descriptions | 60 | 0.00 | 0.00 | 0.108 | 0.118 |
| FAQ bot | 60 | 0.00 | 0.00 | 0.042 | 0.048 |
| Review sentiment | 100 | 0.51 | 0.80 | 0.51 | 0.80 |

Pass rate and mean metric are distinct: invoice uses field F1, product and FAQ
use ROUGE-L, and the two classifiers use accuracy. The JSON files in the parent
`experiments/results/baselines/` directory retain the
unrounded scores, sample outputs, model revisions, timestamps, per-run timing,
evaluation-set hashes and source hashes. A zero pass rate does not imply a
zero mean F1 or ROUGE-L. The datasets are synthetic; these results do not
establish performance on real customer data.

The two scripts are the exact executed private Kaggle scripts, which embed
compressed source snapshots. They validate the datasets and run the committed
baseline implementation with greedy inference on CUDA. Their SHA-256 hashes
are `3cf1579fabde5059ffe5dfb678de63830262712f9be34615d73ff590cd661697`
(`product-notebook.py`) and
`82c58816b6b6408714bb3faadc096112ffd0a73d7e5be6fa4b9ffe954d69ef6f`
(`other-recipes-notebook.py`). The `*-run.txt` files are the downloaded Kaggle
logs. Each script was pulled back from Kaggle and matched byte for byte.

The data and core source were taken from core commit
`e2187d404284d9c7aa3ca6a8421c0a7625fedd98`, the fingerprint fix in
[PR #80](https://github.com/ekido-ai/ekido-core/pull/80). The worker source was
`c4cf5de05b52ae0d4ee05612451bcbda2741868c`. PR #80 is needed on main for a
fresh matrix run to record the actual worker source hash correctly. Each
result's baseline, recipe and runtime fingerprints were independently checked
against the exact archived source. The worker's later main revision changed
distillation, not the inference file used by these runs.

The fixed matrix runner was also run against these ten files with `--resume
--dry-run` using the archived sources. All five dataset validators passed and
the runner reported `0 commands planned; no model was run. 10 matching results
reused.`
