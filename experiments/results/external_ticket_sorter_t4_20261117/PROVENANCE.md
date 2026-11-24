# User-supplied T4 ticket-sorter evidence

The user supplied `train-evidence.json`, `distill-evidence.json`, `C10.json` and `SUMMARY.json` in `ekido-core-runtime.zip` on 17 November 2026. They are preserved without content edits. The accompanying report described a Kaggle Tesla T4 run on that date; no exact run timestamp, complete inference log, model checkpoint or notebook was supplied. The GPU and scores are therefore reported by the submitter and have not been independently reproduced here.

The training evidence identifies `Qwen/Qwen2.5-0.5B-Instruct` at revision `7ae557604adf67be50417f59c2c2f167def9a775`. Its base evaluation reports 100 examples and evaluation-set hash `6cde355819a157aff27ddc281d148e14fb5fad454a2ea583076a51178f663c29`. That hash and example count match the committed ticket-sorter test set merged in Ekido #57. The merged test CSV is the same Git blob as the version used in the previous baseline preflight.

The supplied training evidence reports a base pass rate of 0.35 and a trained pass rate of 0.49; the latter is below the stated recipe floor of 0.8. The distillation evidence reports 0.48 on the same test-set hash against a 0.35 base. Only ten sample answers per evaluation are included, so the complete set of individual predictions cannot be checked from these files. The teacher outputs, generation settings, teacher revision and full student checkpoint are not present; this single small run does not complete issue #33.

This was an early, short run, not a measurement of the recipe's performance
ceiling. The training evidence reports 30 completed logical steps, micro-batch
16, accumulation 1 and 500 training rows: 480 training positions, roughly
one pass if rows were sampled once per position. `C10.json` separately reports
`merged_step: 30`. The samples do not establish how rows were sampled or how
a longer run would perform. In the ten stored **base** answers, nine begin
with `complaint`; in the ten stored **trained** answers, only one does. These
samples are too small to establish the output distribution over all 100 rows.
The later, longer [two-T4 run](https://github.com/ekido-ai/ekido-core/pull/81)
is separate evidence, evaluated on the same reused synthetic test set.

The summary identifies the GPU and records a failed GGUF export stage. A separate `C10.json` reports output sizes and a zero CLI exit code but has an empty captured answer; neither file establishes that the model served a useful answer on staging. Both are retained as supplied rather than treated as a successful serving result. The summary's elapsed times and the training file's `seconds` field describe different scopes and must not be used as a per-recipe training-cost benchmark.

The files are evidence of what was supplied, not a standalone output of `baseline.py`. This supplied run alone did not complete [issue #29](https://github.com/ekido-ai/ekido-internal/issues/29); the later baseline matrix was recorded separately in [PR #82](https://github.com/ekido-ai/ekido-core/pull/82).

SHA-256 of the original LF-encoded files:

| File | SHA-256 |
| --- | --- |
| `train-evidence.json` | `802ec4fc1dffa504b77c44e59520e9d8a80be5dc3caf8849dbbdc5202d4f6962` |
| `SUMMARY.json` | `229272e9f749bd34ac45c5640f79eca72f127207d60b083998c190f5a91c4bd2` |
| `distill-evidence.json` | `547e8d041786a0aa8e98ae4d3dea6fe7b4be0bf40cf46943276bfc29c3400a39` |
| `C10.json` | `19e7e65f775902f2d86053094d92752fcd978e5e2f9b0017778ede8b42df1522` |
