"""A job's public proof (ticket C25): its terms, its quality verdict and its payout split, fingerprinted.

Every paid job leaves one proof record. The record holds only hashes, never the data or any name: the quote's
`terms_hash`, the `verdict_hash` (the hash of the signed verdict) and `payouts_hash` (the payout split, sorted by payee).
The batch of records is built into a Merkle tree (`merkle.py`) and its root is written to the ProofAnchor contract, so
anyone holding a job's record and its audit path can check it was part of an anchored batch and never changed.
"""

from __future__ import annotations

import re

from .canonical import canonical_bytes, document_hash
from .merkle import MerkleError, audit_path, root, verify_audit_path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
KIND = "ekido.proof.v1"


def payouts_hash(payouts: dict[str, int]) -> str:
    """The hash of a payout split: whole paise per payee, in payee order. Zero or negative amounts are refused."""
    if not isinstance(payouts, dict) or not payouts:
        raise MerkleError("a payout split needs at least one payee")
    for payee, amount in payouts.items():
        if not isinstance(payee, str) or not payee or type(amount) is not int or amount <= 0:
            raise MerkleError("each payout must be a named payee and a positive whole number of paise")
    return document_hash({"kind": "ekido.payouts.v1", "payouts": [[p, payouts[p]] for p in sorted(payouts)]})


def proof_record(job_id: str, terms_hash: str, verdict_hash: str, payouts: dict[str, int]) -> dict:
    """The record that goes into a batch. `terms_hash` and `verdict_hash` are lowercase hex SHA-256 (64 characters)."""
    if not isinstance(job_id, str) or not job_id:
        raise MerkleError("a proof needs a job id")
    for name, value in (("terms_hash", terms_hash), ("verdict_hash", verdict_hash)):
        if not isinstance(value, str) or not _HEX64.match(value):
            raise MerkleError(f"{name} must be 64 lowercase hex characters")
    return {"kind": KIND, "job_id": job_id, "terms_hash": terms_hash, "verdict_hash": verdict_hash, "payouts_hash": payouts_hash(payouts)}


def record_bytes(record: dict) -> bytes:
    """The exact bytes of a record, as hashed into the tree (canonical JSON, RFC 8785 style)."""
    if record.get("kind") != KIND or set(record) != {"kind", "job_id", "terms_hash", "verdict_hash", "payouts_hash"}:
        raise MerkleError("this is not a proof record")
    return canonical_bytes(record)


def batch_root(records: list[dict]) -> bytes:
    return root([record_bytes(r) for r in records])


def prove(records: list[dict], index: int) -> dict:
    """What a customer or a third party needs to check one job: the record, its place, the batch size and the path."""
    return {"record": records[index], "index": index, "tree_size": len(records), "path": [p.hex() for p in audit_path([record_bytes(r) for r in records], index)]}


def verify_proof(proof: dict, expected_root_hex: str, count: int | None = None) -> bool:
    """Check a `prove` result against a root read from the contract (`0x` prefix optional).

    Pass the batch's `count` as stored in the contract. An audit path alone does not pin the number of leaves (two nearby
    sizes can share a path shape), so the stored count is what binds the batch size; without it only the root is checked."""
    try:
        if count is not None and proof["tree_size"] != count:
            return False
        expected = bytes.fromhex(expected_root_hex.removeprefix("0x"))
        path = [bytes.fromhex(p) for p in proof["path"]]
        return verify_audit_path(record_bytes(proof["record"]), proof["index"], proof["tree_size"], path, expected)
    except (KeyError, TypeError, ValueError, MerkleError, AttributeError):
        return False
