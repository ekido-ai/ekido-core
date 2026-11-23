"""Illustrative GPU-only costs using a separately sourced hourly price."""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
summary = json.loads((HERE / "t4-20261121/summary.json").read_text(encoding="utf-8"), parse_float=Decimal)
hourly = Decimal("0.35")
values = {}
for name, run in summary["runs"].items():
    seconds = Decimal(run["seconds"])
    tokens = Decimal(run["non_padding_tokens"])
    amount = hourly * Decimal(1_000_000) * seconds / (Decimal(3600) * tokens)
    values[name] = str(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
result = {
    "provider": "Google Cloud Compute Engine", "gpu": "NVIDIA T4", "region": "us-central1",
    "currency": "USD", "gpu_hourly_rate": str(hourly), "retrieved_on": "2026-11-21",
    "source": "https://cloud.google.com/products/compute/gpus-pricing?hl=en",
    "scope": "Illustrative GPU-only on-demand component, excluding VM, storage, network, taxes and overhead; not the Kaggle bill or an Ekido provider price.",
    "formula": "hourly_rate * 1,000,000 * measured_loop_seconds / (3600 * measured_non_padding_tokens)",
    "estimated_gpu_only_usd_per_million_tokens": values,
}
(HERE / "illustrative-gcp-t4-estimate.json").write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
for name, value in values.items():
    print(f"{name}: ${value}/million tokens (illustrative GPU-only)")
