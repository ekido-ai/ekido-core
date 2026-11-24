"""GPCK/1 and GPCK/2 checkpoints: safetensors plus a JSON manifest. Pickle is never used, on save or load.

GPCK/2 (ticket A13) is GPCK/1 with every file also stored encrypted to the job's age recipient (`<name>.age`). The manifest's
`sha256` and `bytes` then describe that stored blob, so object storage's own checksum and content addressing still hold, and
`plaintext_sha256` and `plaintext_bytes` describe the tensors, which whoever holds the job key checks after decrypting. The
training runtime only ever needs the public recipient to write one; reading one needs the job's identity, which stays in the agent
and the verifier and never enters the runtime.

Providers are untrusted, so loading validates everything before any tensor reaches a model.
Signature, fencing and lineage are checked by the caller, because they need outside context.
Requires torch and safetensors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

import torch
from safetensors import SafetensorError, safe_open
from safetensors.torch import save_file

from .canonical import document_hash
# The encrypted-file helpers live in checkpoint_crypto (no torch), so the agent and verifier can use them; re-exported here.
from .checkpoint_crypto import (  # noqa: F401
    DEFAULT_MAX_FILE_BYTES,
    ENCRYPTION,
    FORMAT_V2,
    OPTIMIZER_FILE,
    TRAINABLE_FILE,
    CheckpointError,
    check_stored_blob,
    ciphertext_name,
    decrypt_checkpoint_files,
    encrypt_file,
    sha256_file,
)

FORMAT = "GPCK/1"
MANIFEST_FILE = "manifest.json"
OPTIMIZER_FIELDS = ("exp_avg", "exp_avg_sq", "step")

def _write_durable(tensors: dict[str, torch.Tensor], path: Path) -> None:
    save_file(tensors, str(path))
    # Windows refuses to fsync a file opened only for reading.
    with open(path, "r+b") as handle:
        os.fsync(handle.fileno())


def optimizer_state_to_tensors(optimizer: torch.optim.Optimizer, names: Mapping[int, str]) -> dict[str, torch.Tensor]:
    """Adam state keyed by parameter name, because indexes aren't stable across environments.

    A parameter Adam hasn't touched yet has no state, and is stored as no tensors at all: before the
    first step, or when it never received a gradient. State with only some of its fields is refused.
    """
    tensors: dict[str, torch.Tensor] = {}
    for param, state in optimizer.state.items():
        if id(param) not in names:
            raise CheckpointError("BAD_CHECKPOINT", "optimizer state contains an unknown parameter")
        name = names[id(param)]
        if not state:
            continue
        if not isinstance(state, dict) or not all(field in state for field in OPTIMIZER_FIELDS):
            raise CheckpointError("BAD_CHECKPOINT", f"incomplete Adam state for trainable parameter {name}")
        tensors[f"{name}.exp_avg"] = state["exp_avg"].detach().cpu().clone()
        tensors[f"{name}.exp_avg_sq"] = state["exp_avg_sq"].detach().cpu().clone()
        tensors[f"{name}.step"] = torch.as_tensor(state["step"]).detach().cpu().clone().reshape(1)
    return tensors


def write_checkpoint(directory: Path, trainable: dict[str, torch.Tensor], optimizer_tensors: dict[str, torch.Tensor], manifest: dict,
                     recipient: str | None = None) -> dict:
    """Writes tensors, then the manifest last. Returns the completed, unsigned manifest.

    A crash before the manifest exists leaves nothing that can be committed. With a job `recipient` (the public age key) each file is
    also stored encrypted as `<name>.age`, and the manifest is GPCK/2: it describes the encrypted blobs and the plaintext. Encryption
    is random, so a checkpoint is encrypted once; run this once per checkpoint and keep the files.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    trainable_path = directory / TRAINABLE_FILE
    optimizer_path = directory / OPTIMIZER_FILE
    _write_durable(trainable, trainable_path)
    _write_durable(optimizer_tensors, optimizer_path)

    completed = dict(manifest)
    if recipient is None:
        completed["format"] = FORMAT
        completed["files"] = {
            TRAINABLE_FILE: {"sha256": sha256_file(trainable_path), "bytes": trainable_path.stat().st_size},
            OPTIMIZER_FILE: {"sha256": sha256_file(optimizer_path), "bytes": optimizer_path.stat().st_size},
        }
    else:
        completed["format"] = FORMAT_V2
        completed["files"] = {}
        for plain in (trainable_path, optimizer_path):
            stored = encrypt_file(plain, recipient)
            completed["files"][plain.name] = {
                "sha256": sha256_file(stored), "bytes": stored.stat().st_size,
                "plaintext_sha256": sha256_file(plain), "plaintext_bytes": plain.stat().st_size, "encryption": ENCRYPTION,
            }
    temp = directory / (MANIFEST_FILE + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(completed, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, directory / MANIFEST_FILE)
    return completed


def read_manifest(directory: Path) -> dict:
    path = Path(directory) / MANIFEST_FILE
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CheckpointError("MALFORMED_CHECKPOINT", f"unreadable manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") not in (FORMAT, FORMAT_V2):
        raise CheckpointError("MALFORMED_CHECKPOINT", "not a GPCK/1 or GPCK/2 manifest")
    return manifest


def manifest_hash(manifest: dict) -> str:
    return document_hash(manifest)


def _check_file(directory: Path, name: str, manifest: dict, max_bytes: int) -> Path:
    path = directory / name
    entry = manifest.get("files", {}).get(name)
    if not isinstance(entry, dict):
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{name} missing from manifest")
    if not path.is_file():
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{name} missing from checkpoint")
    # In a GPCK/2 manifest, `sha256` and `bytes` describe the encrypted blob; the tensor file here is plaintext (decrypted by
    # whoever holds the job key), so it is checked against the plaintext fields.
    encrypted = manifest.get("format") == FORMAT_V2
    expected_bytes = entry.get("plaintext_bytes" if encrypted else "bytes")
    expected_hash = entry.get("plaintext_sha256" if encrypted else "sha256")
    size = path.stat().st_size
    if size > max_bytes:
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{name} is {size} bytes, over the {max_bytes} limit")
    if size != expected_bytes:
        raise CheckpointError("HASH_MISMATCH", f"{name} size differs from manifest")
    if sha256_file(path) != expected_hash:
        raise CheckpointError("HASH_MISMATCH", f"{name} hash differs from manifest")
    return path




def _expected_dtype(name: str, dtype: torch.dtype) -> torch.dtype:
    # Adam's step counter is a scalar in torch's default dtype, whatever dtype the weights use.
    return torch.float32 if name.endswith(".step") else dtype


def _load_validated(path: Path, expected: Mapping[str, tuple[int, ...]], dtype: torch.dtype) -> dict[str, torch.Tensor]:
    """Parses as safetensors only, so a renamed pickle is just a parse error and nothing executes."""
    tensors: dict[str, torch.Tensor] = {}
    try:
        with safe_open(str(path), framework="pt", device="cpu") as handle:
            found = set(handle.keys())
            if found != set(expected):
                missing, extra = sorted(set(expected) - found), sorted(found - set(expected))
                raise CheckpointError("MALFORMED_CHECKPOINT", f"{path.name}: tensor names differ, missing {missing[:3]}, unexpected {extra[:3]}")
            for name in sorted(found):
                tensor = handle.get_tensor(name)
                if tuple(tensor.shape) != tuple(expected[name]):
                    raise CheckpointError("MALFORMED_CHECKPOINT", f"{name}: shape {tuple(tensor.shape)}, expected {tuple(expected[name])}")
                wanted = _expected_dtype(name, dtype)
                if tensor.dtype != wanted:
                    raise CheckpointError("MALFORMED_CHECKPOINT", f"{name}: dtype {tensor.dtype}, expected {wanted}")
                if not torch.isfinite(tensor).all():
                    raise CheckpointError("NAN_OR_INF", f"{name} contains NaN or Inf")
                tensors[name] = tensor
    except (SafetensorError, OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, CheckpointError):
            raise
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{path.name} is not valid safetensors: {exc}") from exc
    return tensors


def expected_optimizer_shapes(param_shapes: Mapping[str, tuple[int, ...]]) -> dict[str, tuple[int, ...]]:
    shapes: dict[str, tuple[int, ...]] = {}
    for name, shape in param_shapes.items():
        shapes[f"{name}.exp_avg"] = tuple(shape)
        shapes[f"{name}.exp_avg_sq"] = tuple(shape)
        shapes[f"{name}.step"] = (1,)
    return shapes


def _stored_optimizer_shapes(path: Path, param_shapes: Mapping[str, tuple[int, ...]]) -> dict[str, tuple[int, ...]]:
    """Shapes to expect in the optimizer file: each parameter has all of its Adam fields, or none of them."""
    try:
        with safe_open(str(path), framework="pt", device="cpu") as handle:
            found = set(handle.keys())
    except (SafetensorError, OSError, ValueError, RuntimeError) as exc:
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{path.name} is not valid safetensors: {exc}") from exc
    kept: dict[str, tuple[int, ...]] = {}
    for name, shape in param_shapes.items():
        fields = expected_optimizer_shapes({name: shape})
        present = found.intersection(fields)
        if present and len(present) != len(fields):
            raise CheckpointError("MALFORMED_CHECKPOINT", f"{path.name}: incomplete optimizer state for {name}")
        if present:
            kept.update(fields)
    return kept


def load_checkpoint(
    directory: Path,
    param_shapes: Mapping[str, tuple[int, ...]],
    *,
    dtype: torch.dtype = torch.float32,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    expected_immutable_hash: str | None = None,
) -> tuple[dict, dict[str, torch.Tensor], dict[str, torch.Tensor]]:
    """Validate a checkpoint and return (manifest, trainable, optimizer tensors), all on CPU.

    A parameter with no optimizer state has no entries in the optimizer tensors.
    """
    directory = Path(directory)
    manifest = read_manifest(directory)
    if expected_immutable_hash is not None and manifest.get("immutable_hash") != expected_immutable_hash:
        raise CheckpointError("INVALID_LINEAGE", "checkpoint belongs to a different job spec")
    trainable_path = _check_file(directory, TRAINABLE_FILE, manifest, max_file_bytes)
    optimizer_path = _check_file(directory, OPTIMIZER_FILE, manifest, max_file_bytes)
    trainable = _load_validated(trainable_path, param_shapes, dtype)
    optimizer_tensors = _load_validated(optimizer_path, _stored_optimizer_shapes(optimizer_path, param_shapes), dtype)
    return manifest, trainable, optimizer_tensors


def restore_optimizer_state(optimizer: torch.optim.Optimizer, named_params: Mapping[str, torch.nn.Parameter], tensors: Mapping[str, torch.Tensor]) -> None:
    """Puts validated Adam state back, moving each tensor to its parameter's device.

    A parameter the checkpoint holds no state for is left without any, as it was when saved.
    """
    for name, param in named_params.items():
        if f"{name}.step" not in tensors:
            optimizer.state.pop(param, None)
            continue
        optimizer.state[param] = {
            "step": tensors[f"{name}.step"].reshape(()).clone().to(param.device),
            "exp_avg": tensors[f"{name}.exp_avg"].clone().to(param.device),
            "exp_avg_sq": tensors[f"{name}.exp_avg_sq"].clone().to(param.device),
        }
