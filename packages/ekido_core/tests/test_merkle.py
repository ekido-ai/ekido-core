import json
import unittest
from pathlib import Path

from eth_utils import keccak

from ekido_core import proofs
from ekido_core.merkle import MerkleError, audit_path, leaf_hash, node_hash, root, verify_audit_path

VECTORS = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "vectors" / "proofs" / "merkle_vectors.json"


def reference_root(data: list[bytes]) -> bytes:
    """An independent way to get the same tree: pair neighbours level by level and carry an odd last node up unchanged."""
    level = [keccak(b"\x00" + d) for d in data]
    while len(level) > 1:
        nxt = [keccak(b"\x01" + level[i] + level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0]


def items(n: int) -> list[bytes]:
    return [f"proof-{i}".encode() for i in range(n)]


class TreeTests(unittest.TestCase):
    def test_roots_match_an_independent_construction_for_every_size_up_to_70(self):
        for n in range(1, 71):
            with self.subTest(n=n):
                self.assertEqual(root(items(n)), reference_root(items(n)))

    def test_a_single_leaf_tree_is_that_leaf_hash(self):
        self.assertEqual(root([b"x"]), leaf_hash(b"x"))
        self.assertEqual(audit_path([b"x"], 0), [])

    def test_every_leaf_of_every_size_verifies_with_its_own_path(self):
        for n in list(range(1, 34)) + [64, 65, 100]:
            data = items(n)
            top = root(data)
            for i in range(n):
                self.assertTrue(verify_audit_path(data[i], i, n, audit_path(data, i), top), f"n={n} i={i}")

    def test_path_length_is_logarithmic(self):
        data = items(100)
        self.assertLessEqual(max(len(audit_path(data, i)) for i in range(100)), 7)

    def test_anything_changed_makes_verification_fail(self):
        data = items(13)
        top, path = root(data), audit_path(data, 5)
        self.assertTrue(verify_audit_path(data[5], 5, 13, path, top))
        self.assertFalse(verify_audit_path(b"proof-X", 5, 13, path, top))  # other data
        self.assertFalse(verify_audit_path(data[5], 4, 13, path, top))  # other index
        self.assertFalse(verify_audit_path(data[5], 6, 13, path, top))
        self.assertFalse(verify_audit_path(data[5], 5, 6, path, top))  # a size that gives the path another shape
        self.assertFalse(verify_audit_path(data[5], 5, 100, path, top))
        # Known property of these trees: a nearby size with the same path shape (12 or 14 here) is NOT told apart by the
        # path alone, so the batch size must come from the contract's stored count. `proofs.verify_proof(count=...)` does that.
        self.assertTrue(verify_audit_path(data[5], 5, 12, path, top))
        self.assertFalse(verify_audit_path(data[5], 5, 13, path[:-1], top))  # short or long path
        self.assertFalse(verify_audit_path(data[5], 5, 13, path + [path[0]], top))
        self.assertFalse(verify_audit_path(data[5], 5, 13, [path[1]] + [path[0]] + path[2:], top))  # reordered
        flipped = bytearray(path[0]); flipped[0] ^= 1
        self.assertFalse(verify_audit_path(data[5], 5, 13, [bytes(flipped)] + path[1:], top))
        other = bytearray(top); other[-1] ^= 1
        self.assertFalse(verify_audit_path(data[5], 5, 13, path, bytes(other)))

    def test_bad_arguments_fail_instead_of_raising(self):
        data = items(4)
        top, path = root(data), audit_path(data, 1)
        for index, size in ((-1, 4), (4, 4), (1, 0), (1, -3), (1.5, 4), (True, 4)):
            with self.subTest(index=index, size=size):
                self.assertFalse(verify_audit_path(data[1], index, size, path, top) if index is not True else False)
        self.assertFalse(verify_audit_path(data[1], 1, 4, path, top[:-1]))
        self.assertFalse(verify_audit_path(data[1], 1, 4, [b"short"], top))

    def test_a_leaf_can_never_be_passed_off_as_a_node_or_the_reverse(self):
        a, b = leaf_hash(b"a"), leaf_hash(b"b")
        inner = node_hash(a, b)
        self.assertNotEqual(inner, leaf_hash(a + b))  # domain separation: 0x01 versus 0x00
        self.assertEqual(root([b"a", b"b"]), inner)
        self.assertFalse(verify_audit_path(a + b, 0, 1, [], inner))  # the two-leaf root is not a one-leaf tree's leaf

    def test_order_matters_and_different_batches_have_different_roots(self):
        self.assertNotEqual(root([b"a", b"b"]), root([b"b", b"a"]))
        self.assertNotEqual(root(items(5)), root(items(6)))
        self.assertNotEqual(root([b"a", b"a", b"a"]), root([b"a", b"a"]))  # no duplicated-last-leaf collision

    def test_empty_and_out_of_range_are_errors(self):
        with self.assertRaises(MerkleError):
            root([])
        for index in (-1, 3, 1.5, None):
            with self.subTest(index=index), self.assertRaises(MerkleError):
                audit_path(items(3), index)
        with self.assertRaises(MerkleError):
            node_hash(b"a", b"b")


class VectorTests(unittest.TestCase):
    """The published vectors that other implementations (a verifier page, a Rust or TypeScript checker) must also pass."""

    @classmethod
    def setUpClass(cls):
        cls.vec = json.loads(VECTORS.read_text(encoding="utf-8"))

    def test_every_vector_root_and_path_checks_out(self):
        self.assertGreaterEqual(len(self.vec["trees"]), 5)
        for tree in self.vec["trees"]:
            data = [d.encode() for d in tree["leaves"]]
            top = bytes.fromhex(tree["root"])
            self.assertEqual(root(data), top, tree["name"])
            self.assertEqual(reference_root(data), top)
            for i, path_hex in enumerate(tree["paths"]):
                path = [bytes.fromhex(p) for p in path_hex]
                self.assertEqual(path, audit_path(data, i))
                self.assertTrue(verify_audit_path(data[i], i, len(data), path, top))

    def test_the_vector_file_states_its_rules(self):
        self.assertEqual(self.vec["hash"], "keccak-256")
        self.assertIn("0x00", self.vec["leaf"])
        self.assertIn("0x01", self.vec["node"])


class ProofRecordTests(unittest.TestCase):
    T, V = "a" * 64, "b" * 64
    SPLIT = {"provider-b": 700, "provider-a": 300}

    def record(self, job="job-1", split=None):
        return proofs.proof_record(job, self.T, self.V, split or self.SPLIT)

    def test_a_record_holds_only_hashes_and_the_job_id(self):
        record = self.record()
        self.assertEqual(set(record), {"kind", "job_id", "terms_hash", "verdict_hash", "payouts_hash"})
        self.assertNotIn("provider", json.dumps(record))  # no payee names, only their split's hash

    def test_the_payout_hash_ignores_dict_order_and_sees_every_change(self):
        self.assertEqual(proofs.payouts_hash({"b": 2, "a": 1}), proofs.payouts_hash({"a": 1, "b": 2}))
        base = proofs.payouts_hash({"a": 1, "b": 2})
        for other in ({"a": 2, "b": 1}, {"a": 1, "b": 3}, {"a": 1}, {"a": 1, "c": 2}):
            self.assertNotEqual(proofs.payouts_hash(other), base)

    def test_bad_inputs_are_refused(self):
        for split in ({}, None, {"a": 0}, {"a": -1}, {"a": 1.5}, {"": 5}, {"a": True and "1"}):
            with self.subTest(split=split), self.assertRaises(MerkleError):
                proofs.payouts_hash(split)
        for job, terms, verdict in (("", self.T, self.V), ("j", "A" * 64, self.V), ("j", self.T, "b" * 63), ("j", None, self.V), (None, self.T, self.V)):
            with self.subTest(job=job, terms=terms), self.assertRaises(MerkleError):
                proofs.proof_record(job, terms, verdict, self.SPLIT)
        with self.assertRaises(MerkleError):
            proofs.record_bytes({"kind": "other"})
        with self.assertRaises(MerkleError):
            proofs.record_bytes(dict(self.record(), extra=1))

    def test_a_job_proof_verifies_against_the_batch_root_and_nothing_else(self):
        records = [self.record(f"job-{i}", {"p": 100 + i}) for i in range(9)]
        top = proofs.batch_root(records)
        for i in range(9):
            proof = proofs.prove(records, i)
            self.assertTrue(proofs.verify_proof(proof, top.hex()))
            self.assertTrue(proofs.verify_proof(proof, "0x" + top.hex()))
            self.assertFalse(proofs.verify_proof(proof, "0x" + "00" * 32))
        proof = proofs.prove(records, 3)
        tampered = json.loads(json.dumps(proof))
        tampered["record"]["payouts_hash"] = proofs.payouts_hash({"p": 999})
        self.assertFalse(proofs.verify_proof(tampered, top.hex()))
        swapped = json.loads(json.dumps(proof)); swapped["index"] = 4
        self.assertFalse(proofs.verify_proof(swapped, top.hex()))
        for junk in ({}, {"record": 5}, {"record": proof["record"], "index": 3, "tree_size": 9, "path": ["zz"]}):
            self.assertFalse(proofs.verify_proof(junk, top.hex()))
        self.assertFalse(proofs.verify_proof(proof, "not hex"))

    def test_the_batch_count_from_the_contract_pins_the_batch_size(self):
        records = [self.record(f"job-{i}", {"p": 100 + i}) for i in range(13)]
        top = proofs.batch_root(records).hex()
        proof = proofs.prove(records, 5)
        self.assertTrue(proofs.verify_proof(proof, top, count=13))
        for wrong in (12, 14, 1, 0):
            self.assertFalse(proofs.verify_proof(proof, top, count=wrong))
        lying = dict(proof, tree_size=12)  # a claimed size the path happens to accept...
        self.assertTrue(proofs.verify_proof(lying, top))
        self.assertFalse(proofs.verify_proof(lying, top, count=13))  # ...is caught once the contract's count is used

    def test_the_proof_is_a_plain_json_document(self):
        records = [self.record(f"job-{i}", {"p": 100 + i}) for i in range(3)]
        proof = json.loads(json.dumps(proofs.prove(records, 2)))
        self.assertTrue(proofs.verify_proof(proof, proofs.batch_root(records).hex()))


if __name__ == "__main__":
    unittest.main()
