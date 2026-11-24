"""A13: GPCK/2, checkpoints whose files are also stored encrypted to the job's age key. GPCK/1 must keep working."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import torch
from jsonschema import Draft202012Validator

from ekido_core import gpck, jobkeys
from ekido_core.checkpoint_files import checkpoint_files
from ekido_core.gpck import CheckpointError

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "docs" / "schemas" / "gpck_manifest.schema.json").read_text(encoding="utf-8"))
SHAPES = {"w": (2, 3), "b": (3,)}


def tensors():
    return {"w": torch.arange(6, dtype=torch.float32).reshape(2, 3), "b": torch.tensor([1.0, 2.0, 3.0])}


def optimizer_tensors():
    return {"w.exp_avg": torch.ones(2, 3), "w.exp_avg_sq": torch.ones(2, 3), "w.step": torch.tensor([3.0])}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.key = jobkeys.create_job_key()

    def write(self, name="ck", recipient="default"):
        recipient = self.key.recipient if recipient == "default" else recipient
        return gpck.write_checkpoint(self.tmp / name, tensors(), optimizer_tensors(), {"job_id": "j", "logical_step": 3}, recipient=recipient)


class WriteTests(Base):
    def test_without_a_recipient_the_checkpoint_is_exactly_gpck_1(self):
        manifest = self.write("v1", recipient=None)
        self.assertEqual(manifest["format"], "GPCK/1")
        for entry in manifest["files"].values():
            self.assertEqual(set(entry), {"sha256", "bytes"})
        self.assertEqual(sorted(p.name for p in (self.tmp / "v1").iterdir()), ["manifest.json", "optimizer.safetensors", "trainable.safetensors"])
        manifest_loaded, trainable, _ = gpck.load_checkpoint(self.tmp / "v1", SHAPES)
        self.assertTrue(torch.equal(trainable["w"], tensors()["w"]))
        self.assertEqual(checkpoint_files(manifest_loaded).keys(), manifest["files"].keys())

    def test_with_a_recipient_the_blobs_are_age_files_and_the_manifest_describes_both_forms(self):
        manifest = self.write()
        self.assertEqual(manifest["format"], "GPCK/2")
        folder = self.tmp / "ck"
        for name, entry in manifest["files"].items():
            blob = folder / gpck.ciphertext_name(name)
            plain = folder / name
            self.assertTrue(jobkeys.is_age_ciphertext(blob.read_bytes()))  # objects in S3 will begin "age-encryption.org/v1"
            self.assertEqual((entry["sha256"], entry["bytes"]), (gpck.sha256_file(blob), blob.stat().st_size))  # the blob's name is its own hash
            self.assertEqual((entry["plaintext_sha256"], entry["plaintext_bytes"]), (gpck.sha256_file(plain), plain.stat().st_size))
            self.assertEqual(entry["encryption"], "age-v1")
            self.assertNotEqual(entry["sha256"], entry["plaintext_sha256"])
        self.assertEqual(gpck.read_manifest(folder), manifest)

    def test_no_plaintext_tensor_appears_inside_a_blob(self):
        self.write()
        raw = (self.tmp / "ck" / "trainable.safetensors").read_bytes()
        blob = (self.tmp / "ck" / "trainable.safetensors.age").read_bytes()
        self.assertNotIn(raw[8:40], blob)
        self.assertNotIn(b"safetensors", blob[:200])

    def test_the_manifest_hash_is_that_of_the_encrypted_description(self):
        a, b = self.write("a"), self.write("b")
        self.assertNotEqual(gpck.manifest_hash(a), gpck.manifest_hash(b))  # encryption is random: encrypt once and keep the files

    def test_the_schema_accepts_both_file_shapes_and_requires_the_plaintext_fields_in_v2(self):
        validator = Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": "#/$defs/file"})
        encrypted = Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": "#/$defs/encryptedFile"})
        v2 = self.write()["files"]["trainable.safetensors"]
        v1 = self.write("v1", recipient=None)["files"]["trainable.safetensors"]
        self.assertEqual(list(validator.iter_errors(v1)) + list(validator.iter_errors(v2)), [])
        self.assertEqual(list(encrypted.iter_errors(v2)), [])
        self.assertTrue(list(encrypted.iter_errors(v1)))  # a v1-shaped entry is not acceptable in a GPCK/2 manifest
        self.assertTrue(list(validator.iter_errors(dict(v2, encryption="rot13"))))
        self.assertEqual(SCHEMA["properties"]["format"]["enum"], ["GPCK/1", "GPCK/2"])


class TorchFreeTests(unittest.TestCase):
    def test_the_agent_and_verifier_helpers_do_not_import_torch(self):
        import os
        import subprocess
        import sys

        code = "import sys; import ekido_core.checkpoint_crypto, ekido_core.checkpoint_files, ekido_core.jobkeys; assert 'torch' not in sys.modules, 'torch was imported'"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_gpck_still_exposes_the_same_names(self):
        for name in ("CheckpointError", "sha256_file", "ciphertext_name", "decrypt_checkpoint_files", "check_stored_blob", "write_checkpoint", "load_checkpoint"):
            self.assertTrue(hasattr(gpck, name), name)
        from ekido_core import checkpoint_crypto

        self.assertIs(gpck.CheckpointError, checkpoint_crypto.CheckpointError)  # one error class, wherever it is imported from


class ReadTests(Base):
    def test_checkpoint_files_reads_v1_and_v2_and_refuses_bad_entries(self):
        v2 = self.write()
        self.assertEqual(set(checkpoint_files(v2)), {"trainable.safetensors", "optimizer.safetensors"})
        bad = json.loads(json.dumps(v2))
        for change in (lambda m: m["files"]["trainable.safetensors"].pop("plaintext_sha256"), lambda m: m["files"]["trainable.safetensors"].pop("encryption"),
                       lambda m: m["files"]["trainable.safetensors"].update(encryption="none"), lambda m: m["files"]["optimizer.safetensors"].update(plaintext_bytes=0),
                       lambda m: m["files"]["optimizer.safetensors"].update(plaintext_sha256="XYZ"), lambda m: m.update(format="GPCK/3"),
                       lambda m: m["files"].update({"extra.safetensors": m["files"]["trainable.safetensors"]})):
            candidate = json.loads(json.dumps(bad))
            change(candidate)
            with self.subTest(), self.assertRaises(ValueError):
                checkpoint_files(candidate)
        v1 = self.write("v1", recipient=None)
        smuggled = json.loads(json.dumps(v1))
        smuggled["files"]["trainable.safetensors"]["encryption"] = "age-v1"
        with self.assertRaises(ValueError):
            checkpoint_files(smuggled)  # a v1 manifest cannot quietly gain encryption fields

    def test_loading_the_plaintext_of_a_v2_checkpoint_checks_the_plaintext_hashes(self):
        self.write()
        folder = self.tmp / "ck"
        damaged = self.tmp / "damaged"  # a copy, made before loading (Windows will not rewrite a file that is memory-mapped)
        shutil.copytree(folder, damaged)
        manifest, trainable, _ = gpck.load_checkpoint(folder, SHAPES)
        self.assertEqual(manifest["format"], "GPCK/2")
        self.assertTrue(torch.equal(trainable["b"], tensors()["b"]))
        folder = damaged
        raw = bytearray((folder / "trainable.safetensors").read_bytes())
        raw[-1] ^= 1
        (folder / "trainable.safetensors").write_bytes(bytes(raw))
        with self.assertRaises(CheckpointError) as caught:
            gpck.load_checkpoint(folder, SHAPES)
        self.assertEqual(caught.exception.code, "HASH_MISMATCH")


class DecryptTests(Base):
    def only_blobs(self, name="ck"):
        """What a device or a verifier actually receives from storage: the encrypted blobs and the manifest, no plaintext."""
        src = Path(tempfile.mkdtemp(dir=self.tmp))  # a fresh folder each time
        for blob in (self.tmp / name).glob("*.age"):
            shutil.copy(blob, src / blob.name)
        return src

    def test_the_key_holder_gets_back_exactly_the_tensors(self):
        manifest = self.write()
        out = gpck.decrypt_checkpoint_files(self.only_blobs(), manifest, self.key.identity, self.tmp / "plain")
        self.assertEqual({p.name for p in out.values()}, {"trainable.safetensors", "optimizer.safetensors"})
        for name, path in out.items():
            self.assertEqual(path.read_bytes(), (self.tmp / "ck" / name).read_bytes())
        shutil.copy(self.tmp / "ck" / "manifest.json", self.tmp / "plain" / "manifest.json")
        _, trainable, optimizer = gpck.load_checkpoint(self.tmp / "plain", SHAPES)  # and it loads as a normal checkpoint
        self.assertTrue(torch.equal(trainable["w"], tensors()["w"]))
        self.assertEqual(set(optimizer), set(optimizer_tensors()))

    def test_a_wrong_key_is_refused_and_leaves_nothing_behind(self):
        manifest = self.write()
        with self.assertRaises(CheckpointError) as caught:
            gpck.decrypt_checkpoint_files(self.only_blobs(), manifest, jobkeys.create_job_key().identity, self.tmp / "plain")
        self.assertEqual(caught.exception.code, "DECRYPT_FAILED")
        self.assertEqual(list((self.tmp / "plain").iterdir()), [])

    def test_a_damaged_or_swapped_blob_is_refused_before_it_is_decrypted(self):
        manifest = self.write()
        src = self.only_blobs()
        blob = src / "trainable.safetensors.age"
        raw = bytearray(blob.read_bytes())
        raw[len(raw) // 2] ^= 1
        blob.write_bytes(bytes(raw))
        with self.assertRaises(CheckpointError) as caught:
            gpck.decrypt_checkpoint_files(src, manifest, self.key.identity, self.tmp / "plain")
        self.assertEqual(caught.exception.code, "HASH_MISMATCH")
        other = self.write("other")  # a valid blob of another checkpoint, put in place of this one
        src2 = self.only_blobs("ck")
        shutil.copy(self.tmp / "other" / "trainable.safetensors.age", src2 / "trainable.safetensors.age")
        with self.assertRaises(CheckpointError):
            gpck.decrypt_checkpoint_files(src2, manifest, self.key.identity, self.tmp / "plain2")
        self.assertIsNotNone(other)
        self.assertEqual(list((self.tmp / "plain2").iterdir()), [])

    def test_a_manifest_that_lies_about_the_plaintext_is_refused_after_decrypting(self):
        manifest = self.write()
        lying = json.loads(json.dumps(manifest))
        lying["files"]["optimizer.safetensors"]["plaintext_sha256"] = "0" * 64
        with self.assertRaises(CheckpointError) as caught:
            gpck.decrypt_checkpoint_files(self.only_blobs(), lying, self.key.identity, self.tmp / "plain")
        self.assertEqual(caught.exception.code, "HASH_MISMATCH")
        self.assertEqual(list((self.tmp / "plain").iterdir()), [])  # the first file that was fine is removed too

    def test_a_file_not_marked_as_encrypted_is_refused(self):
        manifest = self.write()
        unmarked = json.loads(json.dumps(manifest))
        unmarked["files"]["trainable.safetensors"]["encryption"] = "none"
        with self.assertRaises(CheckpointError) as caught:
            gpck.decrypt_checkpoint_files(self.only_blobs(), unmarked, self.key.identity, self.tmp / "plain")
        self.assertEqual(caught.exception.code, "MALFORMED_CHECKPOINT")
        self.assertEqual(list((self.tmp / "plain").iterdir()), [])

    def test_a_missing_blob_a_v1_manifest_and_a_truncated_blob_are_refused(self):
        manifest = self.write()
        src = self.only_blobs()
        (src / "optimizer.safetensors.age").unlink()
        with self.assertRaises(CheckpointError):
            gpck.decrypt_checkpoint_files(src, manifest, self.key.identity, self.tmp / "p1")
        v1 = self.write("v1", recipient=None)
        with self.assertRaises(CheckpointError):
            gpck.decrypt_checkpoint_files(self.tmp / "v1", v1, self.key.identity, self.tmp / "p2")
        src2 = self.only_blobs()
        blob = src2 / "trainable.safetensors.age"
        blob.write_bytes(blob.read_bytes()[:-30])
        with self.assertRaises(CheckpointError):
            gpck.decrypt_checkpoint_files(src2, manifest, self.key.identity, self.tmp / "p3")

    def test_the_identity_never_reaches_a_message_or_a_file(self):
        manifest = self.write()
        try:
            gpck.decrypt_checkpoint_files(self.only_blobs(), manifest, jobkeys.create_job_key().identity, self.tmp / "plain")
        except CheckpointError as exc:
            self.assertNotIn("AGE-SECRET-KEY", str(exc))
        for path in self.tmp.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"AGE-SECRET-KEY", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
