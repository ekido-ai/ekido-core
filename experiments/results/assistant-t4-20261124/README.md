# Assistant evaluation on a local T4

Related to [internal #17](https://github.com/ekido-ai/ekido-internal/issues/17).
This is the saved version-4 private Kaggle run, retrieved on 24 November 2026.
The Qwen2.5-1.5B-Instruct Q4_K_M model ran through llama.cpp and a local Platform
test client with synthetic dataset manifests. It is not a staging evaluation.

All 50 prompts received responses. The scorer recorded **0/40 valid specs** on
allowed prompts and **10/10 refusals** on prompts marked for refusal. The 90%
valid-spec target was not reached. The saved results contain response hashes,
not response bodies, so the reason for the allowed-case failures cannot be
determined from these files. A separate diagnostic run was submitted; no result
from that later run is claimed here.

The source set is Arvind's original [PR #83](https://github.com/ekido-ai/ekido-core/pull/83)
at the commit recorded in `summary.json`. Six expected label lists were corrected
to the complete recipe labels in a separate copy; prompts and other expectations
were unchanged. The two sets and their hashes are provided for review. This does
not modify the original PR.

The model revision, file hash, source revisions and per-case result hashes are
in `summary.json`. `run.py` is the Kaggle-pulled script. The two saved logs and
`audit.py` support recounting the 50 outcomes and checking dataset/source hashes;
run `python experiments/results/assistant-t4-20261124/audit.py`. The audit does
not rerun model inference or establish policy approval.
