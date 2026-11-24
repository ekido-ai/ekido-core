# Supplied C14 run12 evidence

This directory records the user-supplied Kaggle T4 run12, not an independent
rerun. The source `ekido-c14-update-v5.zip` has SHA-256
`4d8727be21185035ecd4ece3e4839b1b1f3c9f384c2cd141897239229986a1e5`.
The JSON, JSONL and script files retain their supplied bytes. The two
per-example files contain the supplied predictions, not newly run inference.

The selected student uses the verified arm at step 320, based on validation.
Recounting the supplied per-example predictions gives 81/100 on validation
and 71/100 on the historical test; the base gives 69/100 and 66/100
respectively. Historical test accuracy is below the 0.80 floor. The test was
reused in previous experiments and is not an independent final holdout.
On that test, `other` is 7/20 and `question` is 12/20. The supplied
`ambiguity_flags.json` marks three seller-registration cases for review;
scores retain the original labels.

The source run reports generation from 30 labelled seeds, plus an audit on
470 non-seed labelled examples and checkpoint selection on 100 validation
examples drawn from those rows. No full-dataset C6 judge was used for run12.
Those additional labelled evaluation uses must be disclosed when describing
the experimental supervision. Teacher self-agreement is not proof that a
generated label is correct.

`dataset_verified.jsonl` hashes to
`9097601e2a66f98e0463472071370980b974ce05a4f53c8312a431ad69d7edaf`,
matching `checkpoint-manifest.json`. Its `test` split is the validation set,
not the historical test set. The separately supplied checkpoint archive has
SHA-256 `dc0f701556f75af9cec6a554f16d33350b1ffd8240f26b0cbfdcc1f077357dd2`.
Its trainable and optimizer files matched the recorded SHA-256 and byte sizes;
the archive itself is not stored in Git. The supplied worker `distill.py` and
core `job_spec.py` fingerprints match their specified Git commits.

No independent GPU evaluation, staging deployment or untouched holdout result
is claimed. `kaggle_run12.py` is preserved as supplied for reproducibility;
inspect its environment setup before running it.
