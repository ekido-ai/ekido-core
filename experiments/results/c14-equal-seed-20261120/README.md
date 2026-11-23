# C14 equal-seed-weight exploratory run

Related to [internal #18](https://github.com/ekido-ai/ekido-internal/issues/18)
and [#33](https://github.com/ekido-ai/ekido-internal/issues/33). A Tesla T4 run
tested extra weighting of the original 30 labelled seeds: six examples per class,
each repeated five extra times, alongside 446 previously generated rows. The
resulting training set had 626 rows. The checkpoint at step 400 was fixed before
the final evaluation; the run also reports scores at earlier checkpoints.

The saved validation predictions score 89/100. The supplied historical test
predictions score 72/100, below the recipe's 0.80 floor. Both sets were reused in
earlier experiments, so these numbers do not establish independent generalisation.
The 100 validation labels and earlier teacher diagnostics are additional label
uses beyond the 30 seeds. The issue is not claimed complete by this evidence.

`summary.json` includes all 200 predictions and per-class counts. `dataset.jsonl`,
the saved source CSVs, seed rows, spec, training evidence, step-400 manifest,
executed script and log allow the recorded result to be inspected. Run
`python experiments/results/c14-equal-seed-20261120/audit.py` to recount the saved
predictions and check the data, spec and manifest identities. This audit does not
rerun inference or independently verify GPU measurements.

The locally retained `selected_checkpoint.zip` is not in Git. Its SHA-256 is
`c56ef5135d20d072974b1853202479556d7985a56e8305a8f92d848e682eb46e`.
Before submission its contents were checked against the included manifest; the
repo-only audit cannot recheck the omitted model tensors.
