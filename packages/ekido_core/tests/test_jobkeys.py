import base64
import hashlib
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from ekido_core import jobkeys
from ekido_core.jobkeys import JobKeyError

import generate_age_vectors as vectors

VECTOR_FILE = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "vectors" / "age" / "age_vectors.json"
SIZES = [0, 1, 64 * 1024, 64 * 1024 + 1]


class FakeKms:
    """Behaves like the two boto3 KMS calls we use. It binds a blob to its encryption context and key id, as the
    real service does, and it records every call so tests can see exactly what was sent."""

    def __init__(self) -> None:
        self.blobs: dict[bytes, tuple[bytes, dict, str]] = {}
        self.calls: list[tuple[str, dict]] = []

    def encrypt(self, **kw):
        self.calls.append(("encrypt", {k: v for k, v in kw.items() if k != "Plaintext"}))
        blob = b"fake-kms:" + os.urandom(16)
        self.blobs[blob] = (kw["Plaintext"], dict(kw["EncryptionContext"]), kw["KeyId"])
        return {"CiphertextBlob": blob}

    def decrypt(self, **kw):
        self.calls.append(("decrypt", dict(kw)))
        plaintext, context, key_id = self.blobs[kw["CiphertextBlob"]]
        if kw["EncryptionContext"] != context or kw.get("KeyId") != key_id:
            raise RuntimeError("InvalidCiphertextException")
        return {"Plaintext": plaintext}


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.key = jobkeys.create_job_key()

    def test_round_trip_at_the_required_sizes(self):
        for size in SIZES:
            with self.subTest(size=size):
                data = vectors.plaintext(size)
                blob = jobkeys.encrypt_bytes(data, self.key.recipient)
                self.assertTrue(jobkeys.is_age_ciphertext(blob))
                if size >= 32:
                    self.assertNotIn(data[:32], blob)  # the plaintext is not sitting in the ciphertext
                self.assertEqual(jobkeys.decrypt_bytes(blob, self.key.identity), data)

    def test_200_mib_round_trip_streams_through_files(self):
        size, chunk = 200 * 1024 * 1024, 4 * 1024 * 1024
        digest_in = hashlib.sha256()
        with tempfile.TemporaryDirectory() as tmp:
            plain, sealed, back = (Path(tmp) / n for n in ("plain", "sealed", "back"))
            block = vectors.plaintext(chunk)
            with plain.open("wb") as handle:
                for _ in range(size // chunk):
                    handle.write(block)
                    digest_in.update(block)
            with plain.open("rb") as reader, sealed.open("wb") as writer:
                jobkeys.encrypt_stream(reader, writer, self.key.recipient)
            with sealed.open("rb") as handle:
                self.assertEqual(handle.read(22), jobkeys.AGE_HEADER)
            self.assertGreater(sealed.stat().st_size, size)
            with sealed.open("rb") as reader, back.open("wb") as writer:
                jobkeys.decrypt_stream(reader, writer, self.key.identity)
            self.assertEqual(back.stat().st_size, size)
            digest_out = hashlib.sha256()
            with back.open("rb") as handle:
                while piece := handle.read(chunk):
                    digest_out.update(piece)
        self.assertEqual(digest_out.hexdigest(), digest_in.hexdigest())

    def test_streams_match_bytes_for_small_input(self):
        data = vectors.plaintext(5000)
        sealed = io.BytesIO()
        jobkeys.encrypt_stream(io.BytesIO(data), sealed, self.key.recipient)
        self.assertEqual(jobkeys.decrypt_bytes(sealed.getvalue(), self.key.identity), data)

    def test_each_job_gets_a_different_key_and_each_encryption_differs(self):
        other = jobkeys.create_job_key()
        self.assertNotEqual((self.key.recipient, self.key.identity), (other.recipient, other.identity))
        data = b"same data"
        self.assertNotEqual(jobkeys.encrypt_bytes(data, self.key.recipient), jobkeys.encrypt_bytes(data, self.key.recipient))


class FailureTests(unittest.TestCase):
    def setUp(self):
        self.key = jobkeys.create_job_key()
        self.data = vectors.plaintext(70_000)
        self.blob = jobkeys.encrypt_bytes(self.data, self.key.recipient)

    def test_a_wrong_identity_fails(self):
        wrong = jobkeys.create_job_key()
        with self.assertRaises(JobKeyError):
            jobkeys.decrypt_bytes(self.blob, wrong.identity)
        with self.assertRaises(JobKeyError):
            jobkeys.decrypt_stream(io.BytesIO(self.blob), io.BytesIO(), wrong.identity)

    def test_a_tampered_ciphertext_fails_wherever_it_is_changed(self):
        for position in (0, 30, len(self.blob) // 2, len(self.blob) - 1):
            with self.subTest(position=position):
                damaged = bytearray(self.blob)
                damaged[position] ^= 0x01
                with self.assertRaises(JobKeyError):
                    jobkeys.decrypt_bytes(bytes(damaged), self.key.identity)

    def test_a_truncated_ciphertext_fails(self):
        with self.assertRaises(JobKeyError):
            jobkeys.decrypt_bytes(self.blob[:-20], self.key.identity)
        with self.assertRaises(JobKeyError):
            jobkeys.decrypt_stream(io.BytesIO(self.blob[: len(self.blob) // 2]), io.BytesIO(), self.key.identity)

    def test_malformed_keys_fail_with_our_error(self):
        for bad in ("", "age1nope", "AGE-SECRET-KEY-1NOPE", None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(JobKeyError):
                    jobkeys.encrypt_bytes(b"x", bad)
                with self.assertRaises(JobKeyError):
                    jobkeys.decrypt_bytes(self.blob, bad)

    def test_the_secret_half_never_appears_in_text_form_or_errors(self):
        secret = self.key.identity
        for text in (repr(self.key), str(self.key), f"{self.key}", f"{self.key!r}"):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret.split("-1", 1)[1], text)
        with self.assertRaises(JobKeyError) as caught:
            jobkeys.decrypt_bytes(b"not age", secret)
        self.assertNotIn(secret, str(caught.exception))
        with self.assertRaises(JobKeyError) as caught:
            jobkeys.decrypt_bytes(self.blob, secret[:-3] + "xyz")
        self.assertNotIn(secret[:-3], str(caught.exception))


class WrappingTests(unittest.TestCase):
    def setUp(self):
        self.key = jobkeys.create_job_key()

    def test_kms_wrap_and_unwrap_with_the_job_id_as_context(self):
        kms = FakeKms()
        wrapper = jobkeys.KmsWrapper(kms)
        wrapped = jobkeys.wrap_job_key(self.key, "job-1", wrapper)
        self.assertNotIn(self.key.identity.encode(), wrapped)
        restored = jobkeys.unwrap_job_key(wrapped, "job-1", wrapper)
        self.assertEqual((restored.recipient, restored.identity), (self.key.recipient, self.key.identity))
        sent = [call for name, call in kms.calls]
        self.assertTrue(all(call["EncryptionContext"] == {"job_id": "job-1"} for call in sent))
        self.assertTrue(all(call["KeyId"] == "alias/ekido-data" for call in sent))

    def test_a_wrapped_identity_cannot_be_unwrapped_for_another_job(self):
        wrapper = jobkeys.KmsWrapper(FakeKms())
        wrapped = jobkeys.wrap_job_key(self.key, "job-1", wrapper)
        with self.assertRaises(JobKeyError):
            jobkeys.unwrap_job_key(wrapped, "job-2", wrapper)

    def test_unwrapping_with_another_key_id_or_garbage_fails(self):
        kms = FakeKms()
        wrapped = jobkeys.wrap_job_key(self.key, "job-1", jobkeys.KmsWrapper(kms))
        with self.assertRaises(JobKeyError):
            jobkeys.unwrap_job_key(wrapped, "job-1", jobkeys.KmsWrapper(kms, key_id="alias/other"))
        with self.assertRaises(JobKeyError):
            jobkeys.unwrap_job_key(b"garbage", "job-1", jobkeys.KmsWrapper(kms))

    def test_kms_refuses_to_wrap_something_that_is_not_an_identity(self):
        with self.assertRaises(JobKeyError):
            jobkeys.KmsWrapper(FakeKms()).wrap("not a key", "job-1")

    def test_an_empty_job_id_is_refused(self):
        for wrapper in (jobkeys.KmsWrapper(FakeKms()), jobkeys.LocalWrapper()):
            with self.assertRaises(JobKeyError):
                wrapper.wrap(self.key.identity, "")

    def test_local_wrapper_round_trip_and_job_binding(self):
        wrapper = jobkeys.LocalWrapper()
        wrapped = jobkeys.wrap_job_key(self.key, "job-9", wrapper)
        self.assertNotIn(self.key.identity.encode(), wrapped)
        self.assertEqual(jobkeys.unwrap_job_key(wrapped, "job-9", wrapper).identity, self.key.identity)
        with self.assertRaises(JobKeyError):
            jobkeys.unwrap_job_key(wrapped, "job-10", wrapper)
        with self.assertRaises(JobKeyError):
            jobkeys.unwrap_job_key(wrapped, "job-9", jobkeys.LocalWrapper())  # a different local key

    def test_a_damaged_local_wrapped_payload_always_raises_the_one_error_type(self):
        # age-encrypt to the wrapper's own key so decryption succeeds and the damage is inside: only JobKeyError may escape.
        local = str(jobkeys.x25519.Identity.generate())
        wrapper = jobkeys.LocalWrapper(local)
        recipient = str(jobkeys.x25519.Identity.from_str(local).to_public())
        good = self.key.identity
        payloads = {
            "not json": b"this is not json",
            "not utf-8": b"\xff\xfe\x00",
            "a list": b"[1, 2, 3]",
            "a string": b'"just text"',
            "no identity field": json.dumps({"job_id": "job-1"}).encode(),
            "identity is a number": json.dumps({"job_id": "job-1", "identity": 7}).encode(),
            "identity is not a key": json.dumps({"job_id": "job-1", "identity": "not a key"}).encode(),
            "null": b"null",
        }
        for name, plain in payloads.items():
            with self.subTest(name):
                with self.assertRaises(JobKeyError):
                    wrapper.unwrap(jobkeys.encrypt_bytes(plain, recipient), "job-1")
        # and the good payload still works, so the checks above are about the damage and not about the helper
        ok = json.dumps({"job_id": "job-1", "identity": good}).encode()
        self.assertEqual(wrapper.unwrap(jobkeys.encrypt_bytes(ok, recipient), "job-1"), good)

    def test_the_module_does_not_promise_that_an_identity_is_erased_from_memory(self):
        self.assertIn("never written down", jobkeys.__doc__)
        self.assertIn("cannot be wiped", jobkeys.__doc__)

    def test_wrapping_logs_nothing_secret(self):
        with self.assertLogs(level="DEBUG") as captured:
            logging.getLogger("probe").debug("start")
            wrapper = jobkeys.KmsWrapper(FakeKms())
            wrapped = jobkeys.wrap_job_key(self.key, "job-1", wrapper)
            jobkeys.unwrap_job_key(wrapped, "job-1", wrapper)
        self.assertNotIn(self.key.identity, "\n".join(captured.output))


class SharedVectorTests(unittest.TestCase):
    """The published vectors (docs/schemas/vectors/age/) that the browser and the Rust agent must also pass."""

    @classmethod
    def setUpClass(cls):
        cls.vec = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))

    def test_the_vector_file_has_the_required_cases(self):
        names = {case["name"] for case in self.vec["cases"]}
        self.assertEqual(names, {"empty", "one_byte", "64kib", "64kib_plus_1"})
        self.assertIn("TEST KEYS", self.vec["warning"])

    def test_every_vector_decrypts_to_the_expected_hash(self):
        for case in self.vec["cases"]:
            with self.subTest(case=case["name"]):
                blob = base64.b64decode(case["ciphertext_base64"])
                self.assertTrue(jobkeys.is_age_ciphertext(blob))
                plain = jobkeys.decrypt_bytes(blob, self.vec["test_identity"])
                self.assertEqual(len(plain), case["plaintext_length"])
                self.assertEqual(hashlib.sha256(plain).hexdigest(), case["plaintext_sha256"])
                self.assertEqual(plain, vectors.plaintext(case["plaintext_length"]))

    def test_the_vector_recipient_matches_its_identity(self):
        derived = str(jobkeys._identity(self.vec["test_identity"]).to_public())
        self.assertEqual(derived, self.vec["recipient"])

    def test_wrong_identity_and_tampered_ciphertext_fail_on_every_vector(self):
        for case in self.vec["cases"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(JobKeyError):
                    jobkeys.decrypt_bytes(base64.b64decode(case["ciphertext_base64"]), self.vec["wrong_identity"])
                with self.assertRaises(JobKeyError):
                    jobkeys.decrypt_bytes(base64.b64decode(case["tampered_ciphertext_base64"]), self.vec["test_identity"])


if __name__ == "__main__":
    unittest.main()
