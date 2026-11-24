"""Writes docs/schemas/vectors/age/age_vectors.json: shared test vectors for per-job age encryption (ticket A11).

    python packages/ekido_core/tests/generate_age_vectors.py

The browser (`age-encryption` npm package, A14) and the Rust agent must decrypt every vector here and get the same
SHA-256. age adds fresh randomness each time it encrypts, so running this again writes *different* ciphertexts that
are just as valid. Only regenerate when the vector format changes, then update every implementation's copy together.

The identities in the file are TEST KEYS that are published on purpose. They protect nothing and must never be used
for real data.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from ekido_core import jobkeys

OUT = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "vectors" / "age" / "age_vectors.json"
SIZES = {"empty": 0, "one_byte": 1, "64kib": 64 * 1024, "64kib_plus_1": 64 * 1024 + 1}


def plaintext(length: int) -> bytes:
    """Byte i is (i * 7 + 3) mod 256, so every implementation can rebuild the plaintext and compare."""
    return bytes((i * 7 + 3) % 256 for i in range(length))


def build() -> dict:
    key = jobkeys.create_job_key()
    other = jobkeys.create_job_key()
    cases = []
    for name, length in SIZES.items():
        data = plaintext(length)
        ciphertext = jobkeys.encrypt_bytes(data, key.recipient)
        tampered = bytearray(ciphertext)
        tampered[-1] ^= 0x01
        cases.append({
            "name": name,
            "plaintext_length": length,
            "plaintext_sha256": hashlib.sha256(data).hexdigest(),
            "ciphertext_base64": base64.b64encode(ciphertext).decode("ascii"),
            "tampered_ciphertext_base64": base64.b64encode(bytes(tampered)).decode("ascii"),
        })
    return {
        "format": "age v1 (https://age-encryption.org/v1), X25519 recipient, binary (not armored)",
        "warning": "TEST KEYS, published on purpose. Never use these for real data.",
        "plaintext_rule": "byte i of the plaintext is (i * 7 + 3) mod 256, for i in 0..plaintext_length-1",
        "how_to_check": [
            "for each case: decrypt ciphertext_base64 with test_identity, SHA-256 the result, expect plaintext_sha256",
            "for each case: decrypting ciphertext_base64 with wrong_identity must fail",
            "for each case: decrypting tampered_ciphertext_base64 with test_identity must fail",
            "each ciphertext must start with the ASCII text 'age-encryption.org/v1' and a newline",
        ],
        "test_identity": key.identity,
        "recipient": key.recipient,
        "wrong_identity": other.identity,
        "cases": cases,
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
