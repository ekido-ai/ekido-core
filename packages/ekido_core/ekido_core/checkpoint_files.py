"""Validate untrusted checkpoint file entries before they reach a downloader or disk path."""

import re

CHECKPOINT_FILENAMES = frozenset(("trainable.safetensors", "optimizer.safetensors"))
MAX_FILE_BYTES = 512 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")
from .checkpoint_crypto import ENCRYPTION, FORMAT_V2
FORMAT_V1 = "GPCK/1"


def _sized(entry: dict, name: str, hash_key: str, size_key: str) -> None:
    digest, size = entry.get(hash_key), entry.get(size_key)
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        raise ValueError(f"invalid SHA-256 for {name}")
    if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
        raise ValueError(f"invalid file size for {name}")


def checkpoint_files(manifest: dict) -> dict:
    """The manifest's file entries, validated. GPCK/1 and GPCK/2 are both read. For GPCK/2 `sha256` and `bytes` describe the
    stored (encrypted) blob, which is what is downloaded; the plaintext fields are checked after decrypting."""
    files = manifest.get("files") if isinstance(manifest, dict) else None
    version = manifest.get("format", FORMAT_V1) if isinstance(manifest, dict) else FORMAT_V1
    if version not in (FORMAT_V1, FORMAT_V2):
        raise ValueError("unknown checkpoint format")
    # Exact basenames also exclude traversal, absolute paths, alternate streams and extra files.
    if not isinstance(files, dict) or set(files) != CHECKPOINT_FILENAMES:
        raise ValueError(f"{version} requires exactly trainable.safetensors and optimizer.safetensors")
    for name, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError(f"invalid file entry for {name}")
        _sized(entry, name, "sha256", "bytes")
        if version == FORMAT_V2:
            _sized(entry, name, "plaintext_sha256", "plaintext_bytes")
            if entry.get("encryption") != ENCRYPTION:
                raise ValueError(f"{name} is not marked as encrypted with {ENCRYPTION}")
        elif any(k in entry for k in ("plaintext_sha256", "plaintext_bytes", "encryption")):
            raise ValueError(f"{name}: a GPCK/1 manifest cannot carry encryption fields")
    return files