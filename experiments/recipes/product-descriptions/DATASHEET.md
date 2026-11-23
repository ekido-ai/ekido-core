# Product descriptions dataset

## Source

Fictional product specifications and descriptions created for Ekido issue #26. No external listings, real companies, customer data or product catalogues were used.

## How it was made

An AI coding assistant wrote two small synthetic catalogues, each with ten product categories, explicit materials, sizes and features, and description templates. `experiments/recipes/generate_product_descriptions.py` generates 30 training examples per training product and six test examples per held-out product. No test product name appears in training. Inputs include product name, material, colour, size and feature; outputs describe those supplied values. The audit checks the maximum input similarity to every training row using both sequence similarity and token Jaccard, requiring each to be below 0.85.

The dataset is highly templated and the splits share attribute names and generation rules. The held-out catalogue tests new synthetic product categories; it is not evidence of generalisation to real catalogues or arbitrary writing styles. ROUGE-L may reward surface similarity rather than factual quality. This test split replaces the earlier near-duplicate split; previous baseline scores used the earlier split and must not be reported as scores on this one.

`python experiments/recipes/product-descriptions/audit_factual_scoring.py` runs a
synthetic scoring stress test on the 60 held-out references. It changes only the
colour or the size in each reference to a deliberately incorrect value, while
keeping the original catalogue input. All 60 altered colours and all 60 altered
sizes pass the current per-example ROUGE-L threshold. These are constructed
counterfactuals, not model outputs or a real-world error rate. This audit detects
the scoring weakness; it does not change the quality gate or establish that any
replacement metric has been validated.

## Licence

Created for the Ekido project and contributed under the repository's licence.

## PII check

The examples contain synthetic product attributes and no customer information, personal names, addresses, phone numbers, email addresses or tax identifiers. The dataset validator checks for several PII-shaped patterns; this does not replace an independent content review.

## Label distribution

This is a generation dataset rather than a class-labelled dataset. The 300 training rows are balanced across ten training products and the 60 test rows across ten different held-out products: 30 and 6 examples per product respectively.

## Author

The catalogue, templates and generator were written by an AI coding assistant for Vaibhav Parmar's Ekido issue #26.
