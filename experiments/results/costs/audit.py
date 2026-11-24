"""Audit the saved 20-step T4 measurement matrix without a GPU."""
import ast
import base64
import csv
import hashlib
import io
import json
import math
import sys
import tarfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/ekido_core"))
from ekido_core.canonical import document_hash  # noqa: E402
from ekido_core.job_spec import MODEL_REVISIONS  # noqa: E402

HERE = Path(__file__).resolve().parent
RUN = HERE / "t4-20261121"
RECIPES = ("ticket-sorter-hinglish", "invoice-fields", "product-descriptions", "faq-bot-hinglish", "review-sentiment")
CORE = "0fd7b3e32217bc9d9ab6659e72f5925a7d179751"
WORKER = "2bfde0d6b4743227900a33d0d140990788425d34"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    tree = ast.parse((RUN / "run.py").read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"PAYLOAD", "SOURCE_HASH", "CORE", "WORKER", "RECIPES"}:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    archive = base64.b64decode(constants["PAYLOAD"])
    assert hashlib.sha256(archive).hexdigest() == constants["SOURCE_HASH"]
    assert constants["CORE"] == CORE and constants["WORKER"] == WORKER
    assert tuple(constants["RECIPES"]) == RECIPES
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as outer:
        core_bytes = outer.extractfile("core.tar").read()
        worker_bytes = outer.extractfile("worker.tar").read()
    with tarfile.open(fileobj=io.BytesIO(worker_bytes), mode="r:") as worker:
        train_bytes = worker.extractfile("runtime/ekido_runtime/train.py").read()
        assert hashlib.sha256(train_bytes).hexdigest() == "965dfbe5651a5d1420cc03a55797bf266b68a33e804886a6a5cbaca2c35514cd"
    summary = load(RUN / "summary.json")
    assert summary["core_commit"] == CORE and summary["worker_commit"] == WORKER
    assert summary["gpu"] == "Tesla T4" and summary["steps"] == 20 and len(summary["runs"]) == 10
    with tarfile.open(fileobj=io.BytesIO(core_bytes), mode="r:") as core:
        for recipe in RECIPES:
            original = []
            for split in ("train", "test"):
                raw = core.extractfile(f"experiments/recipes/{recipe}/{split}.csv").read().decode("utf-8")
                original += [{"split": split, **row} for row in csv.DictReader(io.StringIO(raw, newline=""))]
            for model, revision in MODEL_REVISIONS.items():
                key = recipe + "-" + model.rsplit("/", 1)[-1].lower()
                data = load(HERE / (key + ".json"))
                assert data == load(RUN / (key + ".json"))
                case = RUN / key
                spec, manifest = load(case / "spec.json"), load(case / "checkpoint-manifest.json")
                evidence = load(case / "training/evidence.json")
                blob = (case / "dataset.jsonl").read_bytes()
                records = [json.loads(line) for line in blob.decode("utf-8").splitlines()]
                assert records == original
                assert hashlib.sha256(blob).hexdigest() == data["dataset_sha256"] == spec["dataset"]["sha256"]
                assert len(blob) == spec["dataset"]["bytes"]
                assert manifest["immutable_hash"] == document_hash(spec) and manifest["logical_step"] == 20
                assert data["status"] == "complete" and data["gpu"] == "Tesla T4"
                assert data["model"] == model and data["model_revision"] == revision
                assert data["recipe"] == recipe and spec["model"] == {"id": model, "revision": revision}
                metrics = data["measurement"]
                assert metrics == evidence["training_metrics"]
                assert summary["runs"][key] == {"status": "complete", "file": key + ".json", **metrics}
                assert metrics["steps"] == evidence["completed_step"] == 20
                assert metrics["gpu_name"] == "Tesla T4" and metrics["seconds"] > 0
                assert 0 < metrics["non_padding_tokens"] <= metrics["input_tokens_including_padding"]
                assert 0 < metrics["peak_allocated_bytes"] <= metrics["peak_reserved_bytes"]
                assert math.isclose(metrics["non_padding_tokens_per_second"],
                                    metrics["non_padding_tokens"] / metrics["seconds"], rel_tol=1e-12)
                print(f"{key}: {metrics['non_padding_tokens_per_second']:.2f} tokens/s; {metrics['seconds']:.2f}s")
    estimate = load(HERE / "illustrative-gcp-t4-estimate.json")
    assert estimate["gpu_hourly_rate"] == "0.35" and estimate["region"] == "us-central1"
    values = estimate["estimated_gpu_only_usd_per_million_tokens"]
    assert values.keys() == summary["runs"].keys()
    for key, run in summary["runs"].items():
        amount = Decimal("0.35") * Decimal(1_000_000) * Decimal(str(run["seconds"])) / (Decimal(3600) * Decimal(run["non_padding_tokens"]))
        assert values[key] == str(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    print("PASS: 10 dataset identities, manifests, measurements and arithmetic, including illustrative costs")


if __name__ == "__main__":
    main()
