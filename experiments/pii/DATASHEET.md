# PII test set

`pii-set.jsonl` is the labelled set used to measure Ekido's in-browser personal-data stripping (recall and precision per type). It is scored by `experiments/pii/score.py` (ticket A6).

## Source

Fully synthetic. Written for Ekido issue ekido-ai/ekido-internal#36 (A2). No real customer, employee or provider data was used, and none must ever be added.

**No identifier in this file can belong to a real person.** The set lives in a public repository, and a random but correctly shaped Aadhaar, mobile or PAN can easily be somebody's real one (about 1.4 billion Aadhaar numbers are issued; most Indians have a mobile). So every identifier is made in a form that is never issued, while keeping its shape (see the table). This was changed after Piyush's review of 20 Nov. The detector being scored must still recognise these forms; see "What this means for the detector" below.

## How it was made

`generate_pii_set.py` builds every line from hand-written sentence patterns (English, Roman Hinglish and Devanagari Hindi) by filling slots with made-up values, with a fixed seed (`20261117`). Running it again writes an identical file. Span offsets are computed while the text is built, so they always match the text.

| Value | How it is made up |
|---|---|
| NAME | A random first name plus surname from two short lists of common Indian names (Roman and Devanagari pairs) |
| PHONE | 10 digits **starting with 5**, a series India does not allocate (real mobile numbers start with 6 to 9), so none is anyone's number. Written as `+915xxxxxxxxx`, `+91 5xxxx xxxxx`, `05xxxxxxxxx` or `5xxxx-xxxxx`; never as a bare ten-digit string with no prefix or separator (about 18, 19, 19 and 17 of the 73 each) |
| EMAIL | `firstname.lastname` style local part at the reserved domains `example.com`, `example.org`, `example.net` |
| AADHAAR | 12 digits, **first digit 0 or 1** (UIDAI never issues a number starting with 0 or 1, so none is a real Aadhaar), last digit chosen so the Verhoeff check passes; written plain, with spaces or with hyphens |
| PAN | `AAAxA1234A` format: three letters, a **4th letter that is not a holder-type code** (the ten used are P, C, H, F, A, T, B, L, J, G; ours is one of D E K M N Q R S U V W X Y Z, so no real PAN has it), a letter, four digits, a letter. Not checked against any register |
| GSTIN | 2-digit state code, a PAN of the unused kind above, an entity digit, `Z` and a correct check character. The PAN inside it is unissuable, so the whole GSTIN is |
| UPI_ID | a made-up handle (`name`, `name12`, or a 10-digit number) at a real bank handle such as `okaxis` or `ybl`. Random, not checked against any bank |
| ADDRESS | house number, a generic locality name, a city and its main pincode. House numbers are random, so the addresses do not point at real homes |

Span convention: a span covers only the value. It leaves out trailing punctuation and the words around it ("PAN", "Aadhaar", "ph"). An address span runs from the house or flat word to the end of the pincode.

## Contents (measured on the committed file)

- 300 lines: 240 with at least one PII span, **60 with no PII at all**.
- 438 spans in total: NAME 101, PHONE 73, EMAIL 69, ADDRESS 47, PAN 44, GSTIN 41, UPI_ID 32, AADHAAR 31.
- 129 lines carry more than one span.
- Language mix by pattern: about 45% English, 40% Roman Hinglish, 15% Devanagari (45 lines contain Devanagari).
- Phone, Aadhaar and email values in Devanagari lines are written with ASCII digits and letters. Devanagari digits are not covered.

### The 60 lines with no PII

They measure false positives, and many are deliberately tricky:
- order numbers and invoice numbers (`ORD123456`, `INV-2026-12345`);
- 12 lines with a 10-digit tracking number (it starts with 5, like our phone numbers, so it is nobody's number either) that looks like a phone number;
- 6 lines with a 12-digit courier reference that fails the Verhoeff check, so it looks like an Aadhaar number but is not one;
- 6 lines with a coupon code shaped like a PAN (five letters, four digits, a letter, with the same unused 4th letter);
- prices, quantities, product and city names.

A detector that flags these has a false positive; one that ignores a real Aadhaar written with hyphens has a miss.

## What this means for the detector

The detector (the in-browser remover, ekido-web `pii/`) has to recognise these forms for the score to mean anything. Real Aadhaar numbers never start with 0 or 1, real mobiles never start with 5, and real PANs never carry these 4th letters, so a detector built only for real values would miss every one of them here. The remover therefore treats these shapes as personal details too (a Verhoeff-valid 12-digit number starting with 0 or 1; a 5-series mobile that has a `+91`, `91` or `0` prefix or a space or hyphen inside; a PAN-shaped code with another 4th letter when the word PAN is next to it). That makes it slightly broader than a detector for real values, and the scores on this set are for that broader detector. A real-world Aadhaar, mobile or PAN is covered by the same rules; the difference is only the extra shapes.

## Known limits

- **The unissuable forms are less natural than real values.** A bare ten-digit mobile with no prefix is the commonest real format, and this set does not contain one (an unallocated bare number cannot be told apart from any other ten digits), so recall on bare mobiles is not measured here. The unseen set and the unit tests use other shapes.

- Template-based: scores on this set will be higher than on real, messy customer text. Quote them as "on Ekido's synthetic test set", never as general accuracy.
- Only these 8 types. Bank account numbers, passport and driving-licence numbers, dates of birth and card numbers are not labelled.
- Names are common first-name and surname pairs; unusual names, single names and names that are also ordinary words are missing.
- Do not tune a detector by reading this set and then quote its score on the same set. Keep a second, unseen set for that.

## Licence and author

Contributed under the repository's licence. Written by Arvind (GitHub: arvindkushwaha55) with an AI coding assistant; the generator script is the source of record.

## How to check

```
python -I experiments/pii/validate_pii_set.py
python -I experiments/pii/generate_pii_set.py --out some/other/path.jsonl   # reproduces the same file
```
