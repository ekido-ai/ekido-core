# Two-T4 checkpoint resume, 19 November 2026

This run addresses [issue #31](https://github.com/ekido-ai/ekido-internal/issues/31)
with a real process kill and resume on two distinct Tesla T4 GPUs in one Kaggle
session. The first process trained the ticket-sorter 1.5B LoRA job on GPU 0; it
was killed after completing logical step 105. The second process loaded the
GPCK/1 step-80 checkpoint on GPU 1 and completed step 400.

| Measurement | Result |
| --- | --- |
| Logical steps redone after the kill | 25 |
| Kill to completion of first resumed step | 14.636 seconds |
| Final test accuracy | 82 / 100 (0.82); recipe floor 0.80 |
| Training and test rows | 500 / 100 |

The timing starts immediately before the kill signal and ends after step 81
finishes; it includes process startup and model loading. `before-kill.txt` and
`after-resume.txt` record the training sequence. `manifest.json` is the step-80
checkpoint manifest; `evidence.json` is the resumed trainer's own result.
`fault-summary.json` records GPU UUIDs, free memory and temperature before the
test, the measured time, and the final score. `spec.json` and
`exec-config.json` are the unchanged job and execution settings.

`run.py` is the exact private Kaggle script (SHA-256
`a08bb362befd636faf6d8aedaf063b53d5cb1a3a22ff0b301cd49d6b3d7bd283`). It
embeds compressed source and dataset snapshots, checks their hash, and runs
both processes with different `CUDA_VISIBLE_DEVICES` values. The embedded
snapshots come from core `0a9db037170024a1f32748e0b5dcbe14a1a88a3a` and
workers `74bf4e753ab30f4ce3b88a577a16b425c6fac923`; the model is pinned in
`spec.json`. The generated JSONL dataset's SHA-256 matches both the spec and
the checkpoint manifest. The run used all 500 labelled training rows, not a
30-example distillation setup.

The synthetic test set was used in earlier experiments, so the score is not
an independent generalisation estimate. Both GPUs were in the same Kaggle
machine; this result does not demonstrate provider-to-provider failover or a
staging settlement. It also does not measure an RTX 3060.
