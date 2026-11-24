"""Encrypted checkpoint files, without torch (ticket A13): the provider agent and the verifier use this, and neither imports torch.

A GPCK/2 checkpoint stores each file twice: the plaintext tensors (what the training runtime reads and writes) and an age
blob `<name>.age` (what is uploaded). See `gpck.py` for the format and `jobkeys.py` for the keys.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import jobkeys

FORMAT_V2 = "GPCK/2"
ENCRYPTION = "age-v1"
CIPHERTEXT_SUFFIX = ".age"
TRAINABLE_FILE = "trainable.safetensors"
OPTIMIZER_FILE = "optimizer.safetensors"
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024


class CheckpointError(ValueError):
    """The checkpoint must be refused. `code` matches the quality report's reason codes."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def ciphertext_name(name: str) -> str:
    """Where a file's encrypted copy is stored next to it: `trainable.safetensors` becomes `trainable.safetensors.age`."""
    return name + CIPHERTEXT_SUFFIX


def encrypt_file(plain: Path, recipient: str) -> Path:
    """Encrypts `plain` to `recipient` into `<name>.age`, writing a temporary file first so a crash leaves no half file."""
    target = plain.with_name(ciphertext_name(plain.name))
    temp = target.with_name(target.name + ".tmp")
    with open(plain, "rb") as reader, open(temp, "wb") as writer:
        jobkeys.encrypt_stream(reader, writer, recipient)
        writer.flush()
        os.fsync(writer.fileno())
    os.replace(temp, target)
    return target


def check_stored_blob(path: Path, entry: dict, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
    """Check an encrypted blob against its manifest entry (`sha256` and `bytes` of the stored bytes), before decrypting it."""
    path = Path(path)
    if not path.is_file():
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{path.name} is missing")
    size = path.stat().st_size
    if size > max_bytes:
        raise CheckpointError("MALFORMED_CHECKPOINT", f"{path.name} is {size} bytes, over the {max_bytes} limit")
    if size != entry.get("bytes") or sha256_file(path) != entry.get("sha256"):
        raise CheckpointError("HASH_MISMATCH", f"{path.name} differs from the manifest")


def decrypt_checkpoint_files(source: Path, manifest: dict, identity: str, target: Path, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> dict[str, Path]:
    """Decrypt a GPCK/2 checkpoint's blobs from `source` (`<name>.age` files) into plaintext tensor files in `target`.

    Each blob is checked against the manifest before it is decrypted and each result is checked against the manifest's plaintext
    hash after, so neither a swapped blob nor a manifest that lies about the content is accepted. A wrong key or a damaged blob is
    refused. Nothing is left in `target` for a file that fails. The identity is used only here and never written anywhere.
    """
    if manifest.get("format") != FORMAT_V2:
        raise CheckpointError("MALFORMED_CHECKPOINT", "only a GPCK/2 manifest describes encrypted files")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {TRAINABLE_FILE, OPTIMIZER_FILE}:
        raise CheckpointError("MALFORMED_CHECKPOINT", "a checkpoint needs exactly the trainable and optimizer files")
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    try:
        for name in (TRAINABLE_FILE, OPTIMIZER_FILE):
            entry = files[name]
            if not isinstance(entry, dict) or entry.get("encryption") != ENCRYPTION:
                raise CheckpointError("MALFORMED_CHECKPOINT", f"{name} is not marked as encrypted")
            blob = source / ciphertext_name(name)
            check_stored_blob(blob, entry, max_bytes)
            temp = target / (name + ".tmp")
            try:
                with open(blob, "rb") as reader, open(temp, "wb") as writer:
                    jobkeys.decrypt_stream(reader, writer, identity)
            except jobkeys.JobKeyError as exc:
                temp.unlink(missing_ok=True)
                raise CheckpointError("DECRYPT_FAILED", f"{name} could not be decrypted: wrong key or damaged data") from exc
            if temp.stat().st_size != entry.get("plaintext_bytes") or sha256_file(temp) != entry.get("plaintext_sha256"):
                temp.unlink(missing_ok=True)
                raise CheckpointError("HASH_MISMATCH", f"{name} decrypts to something other than the manifest describes")
            os.replace(temp, target / name)
            written[name] = target / name
    except Exception:
        for path in written.values():
            path.unlink(missing_ok=True)
        raise
    return written
