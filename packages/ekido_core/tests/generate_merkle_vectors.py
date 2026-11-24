"""Writes docs/schemas/vectors/proofs/merkle_vectors.json (ticket C25). Deterministic: running it again changes nothing.

    python packages/ekido_core/tests/generate_merkle_vectors.py

Any other implementation of the proof check (a public verify page, a Rust or TypeScript tool) must reproduce every root
and accept every path in this file.
"""

import json
from pathlib import Path

from ekido_core.merkle import audit_path, root

OUT = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "vectors" / "proofs" / "merkle_vectors.json"
SIZES = {"one": 1, "two": 2, "three": 3, "five": 5, "seven": 7, "eight": 8, "thirteen": 13}


def build() -> dict:
    trees = []
    for name, n in SIZES.items():
        leaves = [f"proof-{i}" for i in range(n)]
        data = [x.encode() for x in leaves]
        trees.append({"name": name, "leaves": leaves, "root": root(data).hex(), "paths": [[p.hex() for p in audit_path(data, i)] for i in range(n)]})
    return {
        "hash": "keccak-256",
        "leaf": "leaf hash = keccak256(0x00 || leaf bytes), where the leaf bytes are the UTF-8 of the string in `leaves`",
        "node": "node hash = keccak256(0x01 || left || right); a tree of n leaves splits at the largest power of two below n (RFC 6962)",
        "check": "an audit path is the sibling hashes from the leaf up; verify with the algorithm in RFC 9162, section 2.1.3.2, using these hashes",
        "trees": trees,
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
