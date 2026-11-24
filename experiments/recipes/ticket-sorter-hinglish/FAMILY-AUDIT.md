# Ticket test family and confidence sensitivity audit

For the review in [core #74](https://github.com/ekido-ai/ekido-core/issues/74),
`semantic-families.json` assigns every row of the existing 100-row synthetic
test set to one of **42 manually inferred semantic families**. For example,
questions about extra checkout charges share a family across languages and
product names. The source generator was not supplied, so these are an AI
assistant's reviewable groupings by meaning, not a verified count of the
generator's actual templates. A different reasonable grouping can change the
result. Row indices are zero-based and pinned to the test-set identity hash.

Run `python experiments/recipes/audit_ticket_families.py` from the repository
root. It checks that the groups partition the pinned test rows exactly once,
that each family has a consistent gold class, and that the 100 saved Q8
predictions in `experiments/results/gguf-two-t4-20261119/helper-verification/`
rescore correctly. It writes `experiments/results/datasets/ticket-family-confidence.json`.

The saved Q8 result is **83/100**. If the 100 rows were independent Bernoulli
observations, its two-sided 95% Wilson interval would be **[0.7445, 0.8911]**.
Resampling the 42 inferred families instead, with 20,000 fixed-seed bootstrap
draws, gives the illustrative interval **[0.7282, 0.9216]**. Under the strong
assumptions of equal marginal variance and perfect correlation within each
family, the family-size weights imply a Kish-equivalent sample size of about
**34**, not 100. These are different assumptions and methods, not competing
measurements of customer accuracy.

The 0.80 floor is applied by the current project rule to the observed test
accuracy; this audit does not change that rule. Neither illustrative interval
establishes that underlying accuracy exceeds 0.80. The bootstrap assumes the
inferred families are exchangeable independent units, which is not established;
the set is synthetic, heavily templated and reused, and these groupings have
not received independent review. Fresh, partly human-written data is still
needed before making claims about real-world performance or interpreting these
intervals as customer-data confidence.
