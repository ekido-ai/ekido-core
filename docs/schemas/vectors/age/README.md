# age test vectors (per-job encryption)

`age_vectors.json` is the shared check for per-job encryption in the standard [age](https://age-encryption.org/v1) format. Every implementation must pass it:

| Implementation | Library | Where it is tested |
|---|---|---|
| Python (`ekido_core.jobkeys`) | `pyrage` | `packages/ekido_core/tests/test_jobkeys.py` |
| Browser upload (ticket A14) | `age-encryption` (npm) | the web app's tests |
| Provider agent in Rust (after 26 Nov) | the Rust `age` crate | the agent's tests |

For each case: decrypt `ciphertext_base64` with `test_identity` and the SHA-256 of the result must equal `plaintext_sha256`; the plaintext is also rebuildable (`byte i = (i * 7 + 3) mod 256`). Decrypting with `wrong_identity`, or decrypting `tampered_ciphertext_base64`, must fail.

The keys in this file are **test keys, published on purpose**. They protect nothing. Never use them for real data and never copy a real key into this folder.

age makes fresh randomness each time it encrypts, so regenerating the file (`python packages/ekido_core/tests/generate_age_vectors.py`) writes different, equally valid ciphertexts. Only regenerate when the format changes, and update every implementation together.
