# Two-session T4 checkpoint resume, 21 November 2026

This run addresses part of [issue #31](https://github.com/ekido-ai/ekido-internal/issues/31)
(V4, the LLM kill and resume test). The ticket-sorter 1.5B LoRA job was trained
on one Tesla T4 in a first Kaggle session and killed after logical step 105.
A second, separate Kaggle session received only the first session's output,
checked it, resumed from the step-80 checkpoint on a different physical T4 and
trained to step 400.

| Measurement | Result |
| --- | --- |
| Killed after logical step | 105 of 400 |
| Last complete checkpoint | step 80 |
| Logical steps redone | 25 |
| Process start to the "resumed at logical step 80" line, in session B | 48.985 seconds |
| Process start to first resumed step (81), in session B | 52.044 seconds |
| Completed step | 400 |
| Final test accuracy | 79 / 100 (0.79); recipe floor 0.80, **not met** |
| Session A GPU | Tesla T4, `GPU-937f8a56-6d5f-fb32-4de9-6813f5efce03` |
| Session B GPU | Tesla T4, `GPU-5369f702-d076-bc65-e3fc-0354ab1360b0` |
| Training seconds, steps 81 to 400 plus final evaluation (`train-evidence.json`) | 351.8 (about 1.10 s per step) |

The final score is below the 0.80 floor, so the ticket's "final score at or
above the recipe's quality bar" check is **not** met by this run. The earlier
single-session two-T4 run of the same job and settings scored 82 / 100
(`../two-t4-fault-20261119/`). Both are single runs on the same reused test
set, so the 3-point difference says nothing about which setup is better.

## Files

| File | What it is |
| --- | --- |
| `run_a.py`, `run_b.py` | The exact Kaggle scripts. Each embeds the same hash-checked source snapshot as `../two-t4-fault-20261119/run.py` (archive SHA-256 `cac28f7c8221f5c1e239f788a8eaa07120f7050e9acce75ee176365433a97bf9`, core `0a9db037170024a1f32748e0b5dcbe14a1a88a3a`, workers `74bf4e753ab30f4ce3b88a577a16b425c6fac923`) |
| `run_a_summary.json` | Session A: GPU list, GPU used, kill step and time, checkpoint manifest and dataset SHA-256 |
| `before-kill.txt` | Session A's training log, steps 1 to 105 |
| `fault-summary.json` | Session B: the checks against A, the two GPU UUIDs, steps lost, session-B timings, final score |
| `after-resume.txt` | Session B's log, from "resumed at logical step 80" to step 400 and the final score |
| `train-evidence.json` | Session B's trainer evidence, including the evaluation and its floor |
| `spec.json`, `exec-config.json`, `dataset.jsonl` | The unchanged job, execution settings and dataset |

`run_a.py` SHA-256 `c26544103d2bb71d4034f6c9bfa84a030f4c287dfd376698adc6362a19cf1beb`,
`run_b.py` SHA-256 `f32efba175ba405b84d81b007442f02cae1c331430aaf16b29b64b8f6b7e83ce`.

## What was checked

`run_b.py` refuses to resume unless the source snapshot, the checkpoint
manifest and the dataset SHA-256 all match what session A recorded, and unless
the resume line reports step 80. `fault-summary.json` is written only after
those checks pass. When the files were received they were cross-checked
against the raw logs: A's log holds steps 1 to 105 without gaps, B's holds
steps 81 to 400 without gaps, the dataset SHA-256 equals A's record and
appears in `spec.json`, and the two GPU UUIDs differ.

## What this does not show

- This is not provider-to-provider failover and not a staging settlement. The
  checkpoint was moved by hand through a Kaggle notebook output.
- Both GPUs are Tesla T4s. They are different physical cards of the same
  model, so this is not a different-architecture test. The T4 to RTX 3060 leg
  is still open.
- There is no single kill-to-resume clock. `wall_clock_gap_a_kill_to_b_start_seconds`
  (533.9) includes the manual transfer between sessions. Only the time inside
  session B is a measured system number.
- The test set was used in earlier experiments, so 0.79 is not an independent
  generalisation estimate.
- The checkpoints (step 80 from A, step 400 from B) are not in this folder; the
  download that held them did not complete. Step 80's manifest hash is recorded
  in `run_a_summary.json`.
- The 351.8 seconds covers the resumed training steps and the final evaluation
  together. It is not a training-only throughput and not a price. Session A's
  training time is not recorded cleanly.
