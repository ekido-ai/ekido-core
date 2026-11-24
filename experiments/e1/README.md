# E1: offline comparison of saved runs

Related to [internal #136](https://github.com/ekido-ai/ekido-internal/issues/136).
This tool prepares the comparison after approved held-out data and real outputs
exist. It makes no network calls, collects no API key and does not create a
human-reviewed set or run a model. Its scope is `review-sentiment` and
`invoice-fields`, with base, student and one API run.

Provide:

* A UTF-8 held-out JSONL and a separate training JSONL using the recipe's normal
  columns. Exact normalized duplicate inputs within held-out data or shared with
  training are rejected. This does not detect semantic duplicates, previous
  exposure in earlier experiments or another person's training data.
* A review JSON object with `recipe_id`, the SHA-256 of the exact held-out file
  bytes as `dataset_sha256`, `confirmed: true`, `reviewer` and `evidence`.
  These fields are an attestation supplied by the operator; the program cannot
  authenticate a human review or verify the evidence. Never assert review that did
  not happen. Obtain permission before sending any data to an external API.
* Three run JSON files with `role` (`base`, `student`, `api`), the same
  `dataset_sha256`, `model`, `model_revision`, `price`, and `records`. Records
  must be in dataset order, one per row, with `input_sha256` (SHA-256 of the
  UTF-8 source text), `answer`, `input_tokens`, and `output_tokens`. Keep the
  original raw files and their provenance; no API key belongs in any file.

Every `price` requires `currency: "USD"`, an HTTPS `source_url`, ISO `date` and
explicit `assumptions`. For `kind: "tokens"`, supply exact decimal strings
`input_usd_per_million` and `output_usd_per_million`; measured input and output
token counts are summed. For `kind: "gpu_time"`, supply exact decimal strings
`observed_seconds` and `usd_per_hour` for the measured requests. GPU-time
estimates may exclude idle, VM, storage, network, taxes or other costs; record
those exclusions in `assumptions`. These are estimates, not verified bills; the
tool does not authenticate prices, usage, provider behavior or measurement timing.

```sh
python experiments/e1/compare.py --dataset test.jsonl --train train.jsonl \
  --review review.json --base base.json --student student.json --api api.json \
  --out results.json
```

The result contains per-example answers, references and scores, run-file and
dataset hashes, the supplied attestation, price inputs and estimates per 1,000.
It is published atomically without overwriting an existing result. The ordinary
recipe scorer remains unchanged; these results alone do not establish statistical
independence, factual correctness, production quality or customer savings.
Test data and outputs may contain sensitive information: keep them private and
do not commit customer content without explicit authorization.
