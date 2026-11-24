# Initial Q4/Q8 comparison, 19 November 2026

This is a first export comparison for
[issue #32](https://github.com/ekido-ai/ekido-internal/issues/32), using the
step-400 checkpoint from the two-T4 recovery run in
[PR #81](https://github.com/ekido-ai/ekido-core/pull/81). The checkpoint was
trained on 500 labelled ticket examples and evaluated on the same 100-row
synthetic ticket test set used here.

| Model | Accuracy | Difference from trainer | Within 0.05 tolerance |
| --- | ---: | ---: | --- |
| Original trainer | 0.82 | — | — |
| GGUF Q4_K_M | 0.71 | -0.11 | No |
| GGUF Q8_0 | 0.76 | -0.06 | No |

The 0.05 absolute accuracy tolerance was declared for this experiment; it is
not a published project policy. `summary.json` contains every prediction,
model SHA-256, test-set hash, tolerance and score. `run.txt` is the Kaggle
execution log. `run.py` is the exact executed private notebook script,
SHA-256 `63f2e419375f1bc0169c250f8c2cdbc5c1ba51cfee51e787c98b883ef26ca8f0`.
It embeds pinned worker and core source, consumes the step-400 checkpoint
from the earlier private run, merges it, converts with llama.cpp at
`f8caa5ea30b5775512906ae3b7ee53b21a7a6e1d`, and evaluates each GGUF with the
worker's llama-cli helper. All 200 pass/fail decisions and both score
differences were independently recomputed from the stored answers.

Neither quantized result meets the stated tolerance. This comparison changes
both representation and inference runtime, so it does not isolate quantization
as the cause of the score loss. The test set has been reused in earlier runs.
The first run stored the model hashes but did not retain the large GGUF files.

## Follow-up controls

The `control-run/` directory records a second run of the same checkpoint and
test set. The merged Hugging Face model scored 0.82, matching the trainer.
F16 GGUF scored 0.74, Q4_K_M scored 0.71 and Q8_0 scored 0.76. Thus, a score
gap is present even before quantization when using the llama.cpp inference
path. All 400 stored answers were rescored and the evaluation-set identity
was checked. The exact control script has SHA-256
`1fa2e9ca8a2e9bed586630ba1a000e4cc157d4a02c044458f0fe6ff9cff4b39f`.

The follow-up saved the Q4 and Q8 GGUF files in the private
[Kaggle run](https://www.kaggle.com/code/vaibhavthegoat/ekido-gguf-comparison);
their sizes and SHA-256 hashes are in `control-run/summary.json`.
Both files were also downloaded to the workspace and their SHA-256 hashes
matched the control-run summary; the large weights are not committed to Git.

## Raw-prompt diagnostic

The `raw-diagnostic/` run scored those same Q4 and Q8 files using
`llama-completion` with conversation mode and prompt display disabled. Q4
scored 79/100 and Q8 scored 83/100, compared with 82/100 for merged Hugging
Face: differences of -0.03 and +0.01, both within the predeclared 0.05
absolute tolerance. The Q4 score remains below the recipe's 0.80 floor. The
diagnostic uses a different executable and flags from the original
`llama-cli` run, so it establishes a better matching inference path rather than
isolating one flag as the sole cause. All 200 stored answers and the model and
test-set hashes were checked. Its exact executed script has SHA-256
`5c0d3bc8a6d5936c4eb0e08d70ec406265c47da81892bd701b483cd27c6e9636`.

## Merged worker helper verification

The `helper-verification/` run independently invoked the actual worker helper
merged in [workers PR #17](https://github.com/ekido-ai/ekido-workers/pull/17)
on both saved GGUF files and the same reused synthetic test set. Its source
SHA-256 was `c993361d3718b4d14d2644185459c936ec69725f7de4576a674b10f5314ba556`,
matching the merged worker source. Q4 scored 79/100 and Q8 83/100; all 200
answers match the raw-prompt diagnostic exactly. The Q4 score is still below
the 0.80 quality floor, even though both scores are within the predeclared
0.05 comparison tolerance. These synthetic results do not establish accuracy
on independent or customer data.

The exact executed notebook `helper-verification/run.py` was pulled from the
private Kaggle run and has SHA-256
`a63d5ce13ded59fa427322b87a364f80044855a3bde3bda016f65b577f6493c7`.
Run `python experiments/results/gguf-two-t4-20261119/helper-verification/audit.py`
from the repository root to verify the saved predictions, scores, model and
test-set hashes against the earlier diagnostic and current recipe scorer.
