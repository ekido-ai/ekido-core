# Mixed-sentiment candidate evaluation, 20 November 2026

The saved step-50 review-sentiment student from
[core #88](https://github.com/ekido-ai/ekido-core/pull/88) and its
Qwen2.5-1.5B base were evaluated on the 24-row supplementary AI-written
mixed-sentiment candidate, using the existing recipe prompt and scorer. The
GPU notebook metadata records `NvidiaTeslaT4`; the script required CUDA.
No new training was performed.

| Model | Correct | Positive | Negative | Proposed neutral |
| --- | ---: | ---: | ---: | ---: |
| Base | 20/24 (0.833) | 8/8 | 8/8 | 4/8 |
| Student | 15/24 (0.625) | 4/8 | 7/8 | 4/8 |

The student was selected before this challenge existed. Its earlier 83/100
result used a different, highly templated test set; the numbers are not a
direct before/after comparison. This small synthetic candidate suggests a
weakness on mixed reviews, but its subjective labels have not received
independent review, and the proposed mixed-as-neutral convention is not an
established project rule. It is not a quality gate or evidence of customer-data
performance.

`summary.json` contains all 48 predictions, per-example results, test-set hash
and the checkpoint manifest. The weights are retained in the original private
Kaggle run and locally, rather than in Git. The pulled notebook `run.py` has
SHA-256 `859f07d4cec52713577de299602f63d8bb78a3c318cfe2c5614bbf0d389bbc33`;
it matches the submitted source after LF/CRLF normalisation, but is not
byte-identical because the pulled file uses CRLF. Run
`python experiments/results/mixed-sentiment-20261120/audit.py` to independently
check the saved predictions, scores, dataset identity and checkpoint metadata.
