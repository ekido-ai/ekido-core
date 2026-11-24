# Supplementary synthetic invoice challenge

`challenge.csv` is a candidate stress set for the invoice dataset review in
[core #74](https://github.com/ekido-ai/ekido-core/issues/74). Its 60 invoices
use ten fictional vendor names, six GSTIN-shaped state prefixes, two document
number patterns, three date formats, comma-grouped amounts, fictional addresses,
line items and taxes. All tax identifiers have deliberately invalid check
digits. Generate and audit it from the repository root:

```
python experiments/recipes/generate_invoice_challenge.py
python experiments/recipes/audit_invoice_challenge.py
```

Labels normalise dates to `YYYY-MM-DD` and totals to ungrouped decimal strings
with two fractional digits. Day-first dates have days above 12 to avoid locale
ambiguity. A model evaluation using these labels needs to tell the model this
output convention or explicitly define an equivalent scoring rule; the current
recipe prompt does not state it. The audit checks date parsing, label fields,
line-item arithmetic, invalid GSTIN checksums, deterministic regeneration and
exact input separation from the existing train and test splits.

This is generated from five layouts, with repetitive labels and no human-written
or customer invoices. It is a supplementary candidate, **not** the current
`test.csv`, a replacement quality gate, or evidence of production accuracy.
Existing baseline and training results refer to the original test set; they
must not be attributed to this challenge. An exploratory evaluation of a
saved checkpoint and its base is recorded under
`experiments/results/invoice-challenge-20261120/`; it uses an explicit
normalisation instruction, which differs from the current recipe prompt.
An agreed normalisation contract and independent human-written examples are
needed before considering this challenge for a quality gate.
