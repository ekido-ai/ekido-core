# E1 comparison risks before implementation

Related to [internal #136](https://github.com/ekido-ai/ekido-internal/issues/136).
The 24 November scope is review sentiment and invoice fields, compared against
one API. This preparatory tooling cannot create a human review or an API run.

1. A leaked or changed held-out set can make a comparison invalid. Freeze exact
   bytes and check run inputs against the frozen set; do not call pre-exposed or
   unreviewed data independent or human-reviewed.
2. Missing, duplicated or reordered responses can silently compare different
   examples. Require a complete one-to-one match with stable input hashes.
3. A wrong or stale price, missing usage, or treating an estimate as a bill can
   manufacture savings. Require dated, sourced pricing and label assumptions;
   preserve the measured usage behind every estimate.
4. Customer data or secrets might leak via files or an API provider. Use only
   approved examples, keep credentials outside outputs and logs, and do not
   transmit customer data without authorization.
5. A crash or two writers could publish partial or mixed results. Refuse to
   overwrite a completed result and emit output atomically only after validation.

The reviewer should add another failure mode. No real customer, human review,
API credentials, or external service call is implied by this preparatory work.
