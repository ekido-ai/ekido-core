"""Writes docs/schemas/vectors/proofs/payouts_vectors.json (core #99). Deterministic: running it again changes nothing.

    python packages/ekido_core/tests/generate_payouts_vectors.py

Any other implementation that checks a job's `payouts_hash` (a provider's tool, the operator's, a Rust or TypeScript verifier) must
reproduce every `payouts_hash` below from the payouts and the salt. The salts here are fixed so the file is repeatable; they are
test values only. A real job uses 32 fresh random bytes (`proofs.new_salt()`) and never publishes them.
"""

import hashlib
import json
from pathlib import Path

from ekido_core.proofs import PAYOUTS_KIND, SALT_BYTES, payouts_hash

OUT = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "vectors" / "proofs" / "payouts_vectors.json"
WALLET_A, WALLET_B, WALLET_C = ("0x" + f"{n:040x}" for n in (0xA1, 0xB2, 0xC3))
CASES = {
    "one payee": {WALLET_A: 10_000},
    "two payees": {WALLET_A: 6_300, WALLET_B: 2_700},
    "two payees, listed in the other order": {WALLET_B: 2_700, WALLET_A: 6_300},
    "three payees": {WALLET_C: 1, WALLET_A: 5_000, WALLET_B: 4_999},
    "a large amount": {WALLET_A: 9_999_999_999},
}


def salt_for(name: str) -> bytes:
    return hashlib.sha256(f"ekido payouts test vector salt: {name}".encode()).digest()


# The reordered case shares the first case's salt, so the two hashes must be equal: payee order does not change the hash.
SALT_OF = {"two payees, listed in the other order": "two payees"}


def build() -> dict:
    cases = []
    for name, payouts in CASES.items():
        salt = salt_for(SALT_OF.get(name, name))
        cases.append({"name": name, "payouts": payouts, "salt": salt.hex(), "payouts_hash": payouts_hash(payouts, salt)})
    other_salt = salt_for("another salt for the same payouts")
    return {
        "hash": "sha256",
        "rule": f'payouts_hash = lowercase hex of sha256(salt || body), where salt is the {SALT_BYTES} raw bytes of `salt` (hex here) and body is the canonical JSON '
                f'(RFC 8785: keys sorted, no spaces, UTF-8) of {{"kind": "{PAYOUTS_KIND}", "payouts": [[payee, paise], ...]}} with the pairs sorted by payee',
        "kind": PAYOUTS_KIND,
        "notes": [
            "payee order in `payouts` does not matter; the pairs are sorted by payee before hashing",
            "every amount is a positive whole number of paise; a salt that is not 32 bytes, or is all zero, must be refused",
            "the same payouts with a different salt give a different hash, so a customer who does not have the salt cannot check a guessed split",
        ],
        "cases": cases,
        "same_payouts_different_salt": {"payouts": CASES["two payees"], "salt": other_salt.hex(), "payouts_hash": payouts_hash(CASES["two payees"], other_salt)},
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
