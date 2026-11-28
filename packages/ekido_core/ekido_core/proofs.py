"""A job's public proof (ticket C25): its terms, its quality verdict and its payout split, fingerprinted.

Every paid job leaves one proof record. The record holds only hashes, never the data or any name: the quote's
`terms_hash`, the `verdict_hash` (the hash of the signed verdict) and `payouts_hash` (the payout split, sorted by payee,
with a random per-job salt in front).
The batch of records is built into a Merkle tree (`merkle.py`) and its root is written to the ProofAnchor contract, so
anyone holding a job's record and its audit path can check it was part of an anchored batch and never changed.

The salt keeps the providers hidden from the customer (decision 8). A customer receives the record, and provider wallets are
public on the chain, and the split follows from the job's price, so without a salt the customer could hash candidate splits until
one matched and learn which providers trained their job. With a 32-byte random salt that the customer never receives, that guess
cannot be checked. The salt and the split go only to the providers paid and the operator; the customer's record is still checked
against the anchored root, because `payouts_hash` is just an opaque field to them.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from .canonical import canonical_bytes
from .merkle import MerkleError, audit_path, root, verify_audit_path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
KIND = "ekido.proof.v1"
SALT_BYTES = 32
PAYOUTS_KIND = "ekido.payouts.v2"  # v1 was the unsalted hash; it was never anchored


def new_salt() -> bytes:
    """A fresh random salt for one job's payout split. Keep it next to the proof; give it only to the providers paid and the operator."""
    return secrets.token_bytes(SALT_BYTES)


def _checked_salt(salt: bytes) -> bytes:
    if not isinstance(salt, (bytes, bytearray)) or len(salt) != SALT_BYTES:
        raise MerkleError(f"the salt must be {SALT_BYTES} random bytes")
    if not any(salt):
        raise MerkleError("the salt must be random, not all zero")
    return bytes(salt)


def payouts_hash(payouts: dict[str, int], salt: bytes) -> str:
    """The hash of a payout split: sha256(salt || canonical({kind, payouts})), whole paise per payee in payee order.
    Zero or negative amounts are refused, and so is a missing or wrong-sized salt: there is no unsalted form."""
    if not isinstance(payouts, dict) or not payouts:
        raise MerkleError("a payout split needs at least one payee")
    for payee, amount in payouts.items():
        if not isinstance(payee, str) or not payee or type(amount) is not int or amount <= 0:
            raise MerkleError("each payout must be a named payee and a positive whole number of paise")
    body = canonical_bytes({"kind": PAYOUTS_KIND, "payouts": [[p, payouts[p]] for p in sorted(payouts)]})
    return hashlib.sha256(_checked_salt(salt) + body).hexdigest()


def proof_record(job_id: str, terms_hash: str, verdict_hash: str, payouts: dict[str, int], salt: bytes) -> dict:
    """The record that goes into a batch. `terms_hash` and `verdict_hash` are lowercase hex SHA-256 (64 characters).
    `salt` is the job's secret payout salt (`new_salt()`); it is not in the record, so store it beside the proof, never with the customer's copy."""
    if not isinstance(job_id, str) or not job_id:
        raise MerkleError("a proof needs a job id")
    for name, value in (("terms_hash", terms_hash), ("verdict_hash", verdict_hash)):
        if not isinstance(value, str) or not _HEX64.match(value):
            raise MerkleError(f"{name} must be 64 lowercase hex characters")
    return {"kind": KIND, "job_id": job_id, "terms_hash": terms_hash, "verdict_hash": verdict_hash, "payouts_hash": payouts_hash(payouts, salt)}


def verify_payouts(record: dict, payouts: dict[str, int], salt: bytes) -> bool:
    """For a paid provider or the operator, who hold the split and the salt: does this record commit to exactly them?"""
    try:
        return hmac.compare_digest(payouts_hash(payouts, salt), str(record["payouts_hash"]))
    except (KeyError, TypeError, MerkleError):
        return False


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
