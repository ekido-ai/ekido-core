"""A Merkle tree for job proofs (ticket C25), the shape of RFC 6962 / RFC 9162 with keccak-256.

Anyone can recompute a batch root from the proofs and check one job against it, so this is deliberately small and
standard. Leaves and inner nodes are hashed with different prefixes (0x00 for a leaf, 0x01 for a node), so a node can
never be passed off as a leaf. A tree of n leaves splits at the largest power of two below n, so there is no
"duplicate the last leaf" ambiguity, and an audit path proves one leaf at one index in a tree of one size.

`root` is what the ProofAnchor contract stores. Everything here is bytes; use `.hex()` for display.
"""

from __future__ import annotations

from typing import Sequence

from eth_utils import keccak

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


class MerkleError(ValueError):
    pass


def leaf_hash(data: bytes) -> bytes:
    return keccak(LEAF_PREFIX + bytes(data))


def node_hash(left: bytes, right: bytes) -> bytes:
    if len(left) != 32 or len(right) != 32:
        raise MerkleError("a node is made of two 32-byte hashes")
    return keccak(NODE_PREFIX + left + right)


def _split(n: int) -> int:
    """The largest power of two strictly below n (n >= 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _mth(hashes: Sequence[bytes]) -> bytes:
    n = len(hashes)
    if n == 1:
        return hashes[0]
    k = _split(n)
    return node_hash(_mth(hashes[:k]), _mth(hashes[k:]))


def _path(index: int, hashes: Sequence[bytes]) -> list[bytes]:
    n = len(hashes)
    if n == 1:
        return []
    k = _split(n)
    if index < k:
        return _path(index, hashes[:k]) + [_mth(hashes[k:])]
    return _path(index - k, hashes[k:]) + [_mth(hashes[:k])]


def root(leaves: Sequence[bytes]) -> bytes:
    """The root of the tree whose leaves hold `leaves` (raw data, in order). At least one leaf is needed."""
    if not leaves:
        raise MerkleError("a batch needs at least one proof")
    return _mth([leaf_hash(d) for d in leaves])


def audit_path(leaves: Sequence[bytes], index: int) -> list[bytes]:
    """The sibling hashes that prove leaf `index`, from the leaf up to the root."""
    if not leaves:
        raise MerkleError("a batch needs at least one proof")
    if type(index) is not int or not 0 <= index < len(leaves):
        raise MerkleError("that leaf is not in the tree")
    return _path(index, [leaf_hash(d) for d in leaves])


def verify_audit_path(data: bytes, index: int, tree_size: int, path: Sequence[bytes], expected_root: bytes) -> bool:
    """True only if `data` is leaf `index` of a tree with `tree_size` leaves and root `expected_root` (RFC 9162, 2.1.3.2)."""
    if type(index) is not int or type(tree_size) is not int or tree_size < 1 or not 0 <= index < tree_size:
        return False
    if len(expected_root) != 32 or any(len(p) != 32 for p in path):
        return False
    fn, sn = index, tree_size - 1
    r = leaf_hash(data)
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            if not fn & 1:
                while not fn & 1 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == expected_root
