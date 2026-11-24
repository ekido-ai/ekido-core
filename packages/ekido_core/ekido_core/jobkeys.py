"""Per-job encryption keys, in the standard age format (https://age-encryption.org/v1).

Every job gets its own X25519 keypair. Data (datasets, checkpoints, models) is encrypted to the job's *recipient*
(the public half, `age1...`), so anyone may encrypt but only a holder of the *identity* (`AGE-SECRET-KEY-1...`) may
read. The identity is kept only in memory while it is needed; at rest it exists only *wrapped* (encrypted) by AWS KMS
(`alias/ekido-data`, with the job id as encryption context) or, in tests, by a local key.

No cryptography is written here. Encryption and decryption are `pyrage` (the Rust `age` crate); KMS does the
wrapping. This module only chooses the keys, moves bytes through them and binds a wrapped identity to its job.

Rules this module keeps (ticket A11):
- an identity is never logged, never put in an exception message and never printed (`JobKey.__repr__` hides it);
- a wrong identity or a tampered ciphertext raises `JobKeyError`; it never returns wrong plaintext;
- the same `JobKey` can be rebuilt from a wrapped identity only for the job id it was wrapped for.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol

try:  # pyrage is a hard requirement of this module; the message below says what to install.
    import pyrage
    from pyrage import x25519
except ImportError as exc:  # pragma: no cover - exercised only on a machine without the dependency
    raise ImportError("ekido_core.jobkeys needs pyrage: pip install 'pyrage>=1.4,<2'") from exc

AGE_HEADER = b"age-encryption.org/v1\n"
KMS_KEY_ALIAS = "alias/ekido-data"
_IDENTITY_PREFIX = "AGE-SECRET-KEY-1"
_RECIPIENT_PREFIX = "age1"


class JobKeyError(Exception):
    """A key could not be made, parsed, wrapped, unwrapped or used. Messages never contain key material."""


@dataclass(frozen=True)
class JobKey:
    """A job's keypair. `identity` is secret: keep it in memory only, and wrap it before it is stored."""

    recipient: str
    identity: str = field(repr=False)

    def __repr__(self) -> str:  # explicit, so a debugger or a log line can never show the secret half
        return f"JobKey(recipient={self.recipient!r}, identity=<hidden>)"

    __str__ = __repr__


def create_job_key() -> JobKey:
    """A new random age X25519 keypair for one job."""
    identity = x25519.Identity.generate()
    return JobKey(recipient=str(identity.to_public()), identity=str(identity))


def _recipient(recipient: str) -> x25519.Recipient:
    if not isinstance(recipient, str) or not recipient.startswith(_RECIPIENT_PREFIX):
        raise JobKeyError("recipient must be an age1... X25519 public key")
    try:
        return x25519.Recipient.from_str(recipient)
    except Exception as exc:  # pyrage raises RecipientError; keep our own type and say nothing about the input
        raise JobKeyError("recipient is not a valid age public key") from exc


def _identity(identity: str) -> x25519.Identity:
    if not isinstance(identity, str) or not identity.startswith(_IDENTITY_PREFIX):
        raise JobKeyError("identity must be an AGE-SECRET-KEY-1... X25519 secret key")
    try:
        return x25519.Identity.from_str(identity)
    except Exception as exc:
        raise JobKeyError("identity is not a valid age secret key") from exc


def encrypt_bytes(data: bytes, recipient: str) -> bytes:
    """Encrypt `data` to `recipient`. The result begins with the age header `age-encryption.org/v1`."""
    try:
        return pyrage.encrypt(bytes(data), [_recipient(recipient)])
    except JobKeyError:
        raise
    except Exception as exc:
        raise JobKeyError("encryption failed") from exc


def decrypt_bytes(ciphertext: bytes, identity: str) -> bytes:
    """Decrypt `ciphertext` with `identity`. A wrong identity or any change to the ciphertext raises `JobKeyError`."""
    try:
        return pyrage.decrypt(bytes(ciphertext), [_identity(identity)])
    except JobKeyError:
        raise
    except Exception as exc:
        raise JobKeyError("decryption failed: wrong key or damaged data") from exc


def encrypt_stream(reader: BinaryIO, writer: BinaryIO, recipient: str) -> None:
    """Encrypt from a file-like `reader` to `writer` without holding the whole input in memory (for large files)."""
    try:
        pyrage.encrypt_io(reader, writer, [_recipient(recipient)])
    except JobKeyError:
        raise
    except Exception as exc:
        raise JobKeyError("encryption failed") from exc


def decrypt_stream(reader: BinaryIO, writer: BinaryIO, identity: str) -> None:
    """Decrypt a stream. age authenticates in chunks, so damaged data raises before the damaged chunk is released,
    but earlier chunks may already have been written: discard the output when this raises."""
    try:
        pyrage.decrypt_io(reader, writer, [_identity(identity)])
    except JobKeyError:
        raise
    except Exception as exc:
        raise JobKeyError("decryption failed: wrong key or damaged data") from exc


def is_age_ciphertext(blob: bytes) -> bool:
    """True when `blob` starts with the age v1 header (a cheap check that a stored object is encrypted)."""
    return bytes(blob[: len(AGE_HEADER)]) == AGE_HEADER


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# Wrapping: how a job's identity is stored at rest.
# ---------------------------------------------------------------------------------------------------------------


class IdentityWrapper(Protocol):
    """Encrypts a job identity for storage, bound to its job id, and gets it back."""

    def wrap(self, identity: str, job_id: str) -> bytes:
        """Return the identity encrypted for storage, bound to `job_id`."""

    def unwrap(self, wrapped: bytes, job_id: str) -> str:
        """Return the identity from `wrapped`; refuse a different `job_id`."""


class KmsClient(Protocol):
    """The two AWS KMS calls we use (the same shape as boto3's `kms` client), so tests can pass a fake."""

    def encrypt(self, **kwargs):
        """KMS Encrypt (KeyId, Plaintext, EncryptionContext) returning {"CiphertextBlob": ...}."""

    def decrypt(self, **kwargs):
        """KMS Decrypt (CiphertextBlob, KeyId, EncryptionContext) returning {"Plaintext": ...}."""


def _check_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not job_id:
        raise JobKeyError("job_id must be a non-empty string")
    return job_id


class KmsWrapper:
    """Wraps identities with AWS KMS. The job id is the encryption context `{"job_id": ...}`, so a wrapped identity
    cannot be unwrapped for a different job even by someone who may call KMS. `key_id` pins decryption to our key."""

    def __init__(self, client: KmsClient, key_id: str = KMS_KEY_ALIAS) -> None:
        self._client, self._key_id = client, key_id

    @classmethod
    def from_boto3(cls, region_name: str = "ap-south-1", key_id: str = KMS_KEY_ALIAS) -> "KmsWrapper":
        import boto3  # imported here so the library works without boto3 where KMS is not used

        return cls(boto3.client("kms", region_name=region_name), key_id)

    def wrap(self, identity: str, job_id: str) -> bytes:
        _identity(identity)  # refuse to wrap something that is not an identity
        try:
            reply = self._client.encrypt(
                KeyId=self._key_id,
                Plaintext=identity.encode("ascii"),
                EncryptionContext={"job_id": _check_job_id(job_id)},
            )
            return bytes(reply["CiphertextBlob"])
        except JobKeyError:
            raise
        except Exception as exc:
            raise JobKeyError("KMS could not wrap the job identity") from exc

    def unwrap(self, wrapped: bytes, job_id: str) -> str:
        try:
            reply = self._client.decrypt(
                CiphertextBlob=bytes(wrapped),
                KeyId=self._key_id,
                EncryptionContext={"job_id": _check_job_id(job_id)},
            )
            identity = bytes(reply["Plaintext"]).decode("ascii")
        except JobKeyError:
            raise
        except Exception as exc:
            raise JobKeyError("KMS could not unwrap the job identity (wrong job, key or data)") from exc
        _identity(identity)
        return identity


class LocalWrapper:
    """A wrapper for tests and local runs. It is also age: the identity (and its job id) are encrypted to a local
    age key, and `unwrap` refuses a blob that was wrapped for another job. It is not a substitute for KMS in
    production; it exists so the same code path is tested without a network."""

    def __init__(self, local_identity: str | None = None) -> None:
        self._local = local_identity or str(x25519.Identity.generate())
        self._local_recipient = str(_identity(self._local).to_public())

    def wrap(self, identity: str, job_id: str) -> bytes:
        _identity(identity)
        payload = json.dumps({"job_id": _check_job_id(job_id), "identity": identity}, separators=(",", ":"))
        return encrypt_bytes(payload.encode("ascii"), self._local_recipient)

    def unwrap(self, wrapped: bytes, job_id: str) -> str:
        payload = json.loads(decrypt_bytes(wrapped, self._local))
        if payload.get("job_id") != _check_job_id(job_id):
            raise JobKeyError("this wrapped identity belongs to a different job")
        identity = payload["identity"]
        _identity(identity)
        return identity


def wrap_job_key(key: JobKey, job_id: str, wrapper: IdentityWrapper) -> bytes:
    """The bytes to store for a job: its identity, wrapped. The recipient is public and stored beside it."""
    return wrapper.wrap(key.identity, job_id)


def unwrap_job_key(wrapped: bytes, job_id: str, wrapper: IdentityWrapper) -> JobKey:
    """Rebuild a job's key from its wrapped identity. Keep the result in memory only."""
    identity = wrapper.unwrap(wrapped, job_id)
    return JobKey(recipient=str(_identity(identity).to_public()), identity=identity)
