# Invoice challenge evaluation, 20 November 2026

The saved invoice student from [core #94](https://github.com/ekido-ai/ekido-core/pull/94)
and its untrained Qwen2.5-1.5B base were evaluated on the supplementary
60-row synthetic `invoice-fields/challenge.csv`, using the project field
scorer. The GPU notebook's metadata records `NvidiaTeslaT4`; the script
required CUDA. The run did not train a new model.

| Model | All fields correct | Mean field score |
| --- | ---: | ---: |
| Base | 59/60 (0.9833) | 0.9967 |
| Student checkpoint, step 50 | 60/60 (1.0000) | 1.0000 |

The base's only failed row returned a timestamp rather than the required ISO
date. The project scorer extracts the JSON object and does not penalize extra
text after it. The student was selected before this challenge existed; this
was a single exploratory evaluation, not model selection. The high base score
means the result does not establish a meaningful benefit from training. The
challenge has only five synthetic layouts, is not human-written, and is not a
customer-data or production-accuracy measurement.

Unlike the existing recipe prompt, both arms received an additional instruction
to return dates as `YYYY-MM-DD` and totals with two decimals and no commas.
Therefore these scores should not be compared directly to the historical 50/50
student result on the original test set with the unmodified prompt. The saved
`summary.json` has all 120 predictions, the instruction, scores, test-set hash
and checkpoint manifest. The model weights are retained in the private Kaggle
run and locally rather than in Git; the manifest is included here.

`run.py` is the source pulled from the private completed notebook and has
SHA-256 `a53afaa21f7856743b3471189144b81c4ddbbddf85cd117aa7a1830b0d39e8d1`.
The pulled source matches the submitted source after LF/CRLF normalisation; it
is not byte-identical because Kaggle's pull produced CRLF line endings. The
input-file byte hash in the result identifies the submitted Windows CSV;
`eval_set_hash` identifies its parsed rows independent of outer CSV line endings.
Run `python experiments/results/invoice-challenge-20261120/audit.py` to check
the saved checkpoint metadata, dataset identity and all predictions and scores.
