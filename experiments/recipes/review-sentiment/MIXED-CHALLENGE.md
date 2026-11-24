# Candidate mixed-sentiment reviews

`mixed-challenge.csv` contains 24 fictional, AI-written reviews for the mixed
sentiment gap in [core #74](https://github.com/ekido-ai/ekido-core/issues/74).
Each includes a positive and a negative aspect. Eight express an overall
positive view, eight an overall negative view, and eight explicitly describe
an overall mixed or neither-positive-nor-negative view. The proposed neutral
label for the latter is a candidate convention, not an established project
policy. Reviews are in English, Roman Hinglish and Devanagari Hindi.

Run `python experiments/recipes/audit_mixed_sentiment.py` to check the schema,
label counts, exact duplicates and exact overlap with the existing split, and
the repository's PII-shaped patterns. This audit cannot prove the subjective
labels are correct. The candidate needs independent human label review and an
agreed interpretation of mixed sentiment before use in a quality gate.

This is supplementary AI-written data, not the current `test.csv` and not
customer data. Existing results do not apply to this set. A separate,
exploratory checkpoint and base comparison is recorded in
`experiments/results/mixed-sentiment-20261120/`.
