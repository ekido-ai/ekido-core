# Local T4 gateway benchmark

Related to [internal #15](https://github.com/ekido-ai/ekido-internal/issues/15).
This private Kaggle job was submitted on 22 November 2026 and its outputs were
retrieved on 24 November. It used an actual Rust gateway, Platform authority,
and Qwen2.5-1.5B-Instruct Q4_K_M served by llama.cpp on a Tesla T4. The test
uses a synthetic request and local SQLite, not staging or production traffic.

After five warm-up requests, 40 sequential chat requests were measured with a
16-token output limit. Mean end-to-end latency was **201.805 ms**; nearest-rank
p95 was **209.350 ms**. All 45 persisted usage records had successful status.
Individual measured latencies and token usage are in `results.json`; the model
response text and the test API key are not stored there.

These measurements do not establish production p95, parallel throughput or an
actual billed cost. As an illustration only, at the [Google Cloud Iowa T4
GPU-only rate](https://cloud.google.com/products/compute/gpus-pricing?hl=en)
of $0.35/hour (checked 24 November 2026), 1,000 sequential requests at the
observed mean would occupy about 201.805 seconds and cost **$0.01962 for the GPU
component**. This extrapolation assumes the same workload and full utilization;
model loading, deployment, idle time, CPU/VM, storage, network, billing minima
and taxes are excluded. It is not a Kaggle bill or Ekido price. The run uses the
source commits of the subsequently merged atomic-billing PRs, recorded in
`results.json`.

`run.py` is the source pulled from the executed Kaggle version; it matched the
submitted file after LF/CRLF normalization (SHA-256
`c5525d582c3e977ea8632951b0664fb6f5e895e9a4a690e3c8b88736dfd7f4b0`).
`execution-log.txt` and `llama-server.txt` are saved logs. Run
`python experiments/results/gateway-t4-20261124/audit.py` to verify the saved
latency arithmetic, usage counts and embedded source archive hashes. The audit
does not independently rerun inference or verify a monetary cost.
