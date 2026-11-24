# Three 30-seed distillation runs on T4, 19 November 2026

These runs provide the base/student comparison for
[issue #33](https://github.com/ekido-ai/ekido-internal/issues/33). Each used
30 labelled seeds from its committed training split, Qwen2.5-7B-Instruct as
the 4-bit teacher, and a Qwen2.5-1.5B-Instruct LoRA student for 50 logical
steps. Selection was fixed in advance: ten seeds per sentiment class and 30
seeded random examples for each other recipe.

| Recipe | Accepted generated rows | Test rows | Base pass rate | Student pass rate | Recipe floor |
| --- | ---: | ---: | ---: | ---: | ---: |
| Review sentiment | 83 | 100 | 0.80 | 0.83 | 0.80 |
| Invoice fields | 76 | 50 | 0.00 | 0.12 | 0.70 |
| Clinic FAQ | 90 | 60 | 0.00 | 0.10 | 0.60 |

Sentiment reached its floor on this test; invoice and FAQ did not. These are
synthetic test sets, and teacher-generated labels were not independently
hand-reviewed. The committed test sets have also been used in prior work.

The reproducible literal audit in `audit_generated_quality.py` and
`quality-audit.json` found at least one missing literal target value in all
76 invoice inputs; all 76 were missing the exact invoice number and total.
Among 90 FAQ inputs, 15 contained the complete target answer verbatim and 22
contained a `New Question:` marker. These counts are specific checks, not a
complete semantic label review. They expose unreliable targets and answer
leakage and mean these generated invoice/FAQ rows should not be treated as
clean training data.

Each recipe directory retains the 30 selected seeds, the accepted generated
rows and test rows (`student_dataset.jsonl`), student spec, generation
settings and base/student evidence. The teacher's unfiltered/rejected text was
not retained. The JSONL checksum matches the spec; train inputs were checked
for exact duplicates and exact overlap with both seeds and test inputs. The
trainer's evaluation-set hash matches the committed test split. All three
step-50 checkpoint manifests match the specs and the downloaded trainable and
optimizer tensors. The weights are stored locally and in the private
[Kaggle run](https://www.kaggle.com/code/vaibhavthegoat/ekido-distillation-matrix),
not in this Git repository.

`summary.json` records total elapsed time and peak allocated GPU memory across
teacher generation and student training, not training-only throughput.
`run.txt` is the raw Kaggle log and `run.py` is the exact executed script
(SHA-256 `a8030be7063a77e0e27809d061c808d457d51574565e7c1f0e8b55b61a577b85`).
The source snapshots are core `0a9db037170024a1f32748e0b5dcbe14a1a88a3a`
and workers `74bf4e753ab30f4ce3b88a577a16b425c6fac923`. The worker source
requests teacher revision `a09a35458c702b33eeacc393d103063234e8bc28`, but the
model's observed `_commit_hash` was absent, so the trainer's
`teacher_revision` fields are null; they have not been backfilled. The
student revision and generation settings are in each evidence file.
