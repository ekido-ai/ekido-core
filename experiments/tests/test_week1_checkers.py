"""The week-1 data checkers: recipe datasets, the PII test set and the assistant prompt set."""
import csv
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def load(relative: str):
    spec = importlib.util.spec_from_file_location(relative.replace("/", "_"), HERE / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


datasets = load("recipes/validate_dataset.py")
pii = load("pii/validate_pii_set.py")
prompts = load("assistant/validate_prompt_set.py")
pii_generator = load("pii/generate_pii_set.py")

SHEET = "\n".join(f"## {s}\ntext" for s in datasets.DATASHEET_SECTIONS)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def make_recipe(root: Path, name="review-sentiment", train=500, test=100, label="positive", sheet=SHEET) -> Path:
    folder = root / name
    folder.mkdir()
    write_csv(folder / "train.csv", ["text", "label"], [[f"train review {i}", label] for i in range(train)])
    write_csv(folder / "test.csv", ["text", "label"], [[f"test review {i}", label] for i in range(test)])
    if sheet is not None:
        (folder / "DATASHEET.md").write_text(sheet, encoding="utf-8")
    return folder


class RecipeDatasets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_good_dataset_passes(self):
        errors, _ = datasets.validate(make_recipe(self.root))
        self.assertEqual(errors, [])

    def test_unknown_recipe_and_missing_files(self):
        (self.root / "nope").mkdir()
        self.assertIn("unknown recipe", datasets.validate(self.root / "nope")[0][0])

    def test_too_few_rows_bad_labels_and_no_datasheet(self):
        errors, _ = datasets.validate(make_recipe(self.root, train=10, label="meh", sheet=None))
        joined = "\n".join(errors)
        self.assertIn("needs at least 500", joined)
        self.assertIn("label 'meh'", joined)
        self.assertIn("DATASHEET.md: missing", joined)

    def test_train_test_overlap_and_duplicates(self):
        folder = make_recipe(self.root)
        write_csv(folder / "test.csv", ["text", "label"], [["Train Review 1", "positive"]] * 100)
        joined = "\n".join(datasets.validate(folder)[0])
        self.assertIn("also appear in train", joined)
        self.assertIn("duplicated inputs", joined)

    def test_hinglish_needs_some_devanagari(self):
        folder = self.root / "ticket-sorter-hinglish"
        folder.mkdir()
        write_csv(folder / "train.csv", ["text", "label"], [[f"order kab aayega {i}", "order"] for i in range(500)])
        write_csv(folder / "test.csv", ["text", "label"], [[f"refund chahiye {i}", "refund"] for i in range(100)])
        (folder / "DATASHEET.md").write_text(SHEET, encoding="utf-8")
        self.assertIn("Devanagari", "\n".join(datasets.validate(folder)[0]))

    def test_invoice_json_must_have_every_field(self):
        folder = self.root / "invoice-fields"
        folder.mkdir()
        good = json.dumps({"vendor": "A", "invoice_no": "1", "date": "2026-01-01", "total": "10", "gstin": "x"})
        write_csv(folder / "train.csv", ["text", "json"], [[f"invoice {i}", good] for i in range(200)])
        write_csv(folder / "test.csv", ["text", "json"], [[f"bill {i}", '{"vendor": "A"}'] for i in range(50)])
        (folder / "DATASHEET.md").write_text(SHEET, encoding="utf-8")
        self.assertIn("json is missing", "\n".join(datasets.validate(folder)[0]))

    def test_personal_data_is_a_warning(self):
        folder = make_recipe(self.root)
        write_csv(folder / "train.csv", ["text", "label"], [[f"call me on 98765432{i:02d}", "positive"] for i in range(500)])
        errors, warnings = datasets.validate(folder)
        self.assertEqual(errors, [])
        self.assertTrue(any("phone" in w for w in warnings))


def aadhaar() -> str:
    """A made-up 12-digit number that passes the Verhoeff check and starts with 0 (UIDAI never issues those)."""
    base = "01234123412"
    for last in "0123456789":
        if pii.verhoeff_ok(base + last):
            return base + last
    raise AssertionError("no check digit found")


def pii_lines(clean=60) -> list[dict]:
    samples = {
        "NAME": "Ravi Kumar", "PHONE": "+91 54321 09876", "EMAIL": "ravi@example.com", "AADHAAR": aadhaar(),
        "PAN": "ABCDE1234F", "GSTIN": "27ABCDE1234F1Z5", "UPI_ID": "ravi@okbank", "ADDRESS": "12 MG Road, Pune",
    }
    lines = []
    for i in range(300 - clean):
        kind = sorted(samples)[i % len(samples)]
        prefix = f"case {i}: "
        lines.append({"text": prefix + samples[kind], "spans": [{"start": len(prefix), "end": len(prefix) + len(samples[kind]), "type": kind}]})
    lines += [{"text": f"order number 4521{i} is delayed", "spans": []} for i in range(clean)]
    return lines


class PiiSet(unittest.TestCase):
    def write(self, lines: list[dict], datasheet=True) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "pii-set.jsonl"
        path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
        if datasheet:
            (path.parent / "DATASHEET.md").write_text("ok", encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)
        return path

    def test_a_good_set_passes(self):
        self.assertEqual(pii.validate(self.write(pii_lines())), [])

    def test_bad_spans_types_and_checksums(self):
        lines = pii_lines()
        lines[0]["spans"][0]["end"] = 999
        lines[1]["spans"][0]["type"] = "SSN"
        bad = {"text": "aadhaar 0123 4123 4120", "spans": [{"start": 8, "end": 22, "type": "AADHAAR"}]}
        lines.append(bad if not pii.verhoeff_ok("012341234120") else {"text": "x", "spans": []})
        joined = "\n".join(pii.validate(self.write(lines)))
        self.assertIn("outside the text", joined)
        self.assertIn("'SSN'", joined)
        self.assertIn("Verhoeff", joined)

    def test_identifiers_that_could_belong_to_a_real_person_are_refused(self):
        real_aadhaar = next("2341234123" + d + c for d in "0123456789" for c in "0" if pii.verhoeff_ok("2341234123" + d + c))
        shapes = {
            "AADHAAR": real_aadhaar,                  # starts with 2: a number UIDAI could have issued
            "PAN": "ABCPE1234F",                      # 4th letter P: an individual's PAN
            "PHONE": "9876543210",                    # a mobile series that is allocated
        }
        for kind, value in shapes.items():
            with self.subTest(kind):
                lines = pii_lines()
                lines.append({"text": f"x {value}", "spans": [{"start": 2, "end": 2 + len(value), "type": kind}]})
                joined = "\n".join(pii.validate(self.write(lines)))
                self.assertTrue(any(word in joined for word in ("cannot issue", "holder-type", "unallocated")), joined)

    def test_every_identifier_in_the_committed_set_is_one_that_cannot_be_issued(self):
        path = HERE / "pii" / "pii-set.jsonl"
        self.assertEqual(pii.validate(path), [])
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        seen = {"AADHAAR": 0, "PAN": 0, "PHONE": 0, "GSTIN": 0}
        for row in rows:
            for span in row["spans"]:
                value = row["text"][span["start"]:span["end"]]
                kind = span["type"]
                if kind == "AADHAAR":
                    self.assertIn(value.replace(" ", "").replace("-", "")[0], "01", value)
                elif kind == "PAN":
                    self.assertNotIn(value[3], "PCHFATBLJG", value)
                elif kind == "PHONE":
                    self.assertEqual(re.sub(r"[^0-9]", "", value)[-10:][0], "5", value)
                elif kind == "GSTIN":
                    self.assertNotIn(value[5], "PCHFATBLJG", value)  # the PAN inside a GSTIN is an unissuable one
                else:
                    continue
                seen[kind] += 1
        self.assertTrue(all(count >= 10 for count in seen.values()), seen)  # not vacuous

    def test_the_committed_set_is_exactly_what_the_seeded_generator_writes(self):
        expected = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in pii_generator.build())
        self.assertEqual((HERE / "pii" / "pii-set.jsonl").read_text(encoding="utf-8").replace("\r\n", "\n"), expected)

    def test_look_alike_numbers_on_clean_lines_are_not_labelled(self):
        rows = [json.loads(line) for line in (HERE / "pii" / "pii-set.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(sum(1 for r in rows if not r["spans"]), 60)

    def test_needs_clean_lines_and_a_datasheet(self):
        joined = "\n".join(pii.validate(self.write(pii_lines(clean=5), datasheet=False)))
        self.assertIn("with no PII", joined)
        self.assertIn("DATASHEET.md", joined)

    def test_verhoeff(self):
        self.assertTrue(pii.verhoeff_ok("2363"))  # the textbook example: 236 with check digit 3
        self.assertFalse(pii.verhoeff_ok("2364"))


class PromptSet(unittest.TestCase):
    def write(self, lines: list[dict]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "prompts.jsonl"
        path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
        return path

    def good(self) -> list[dict]:
        allowed = [{"prompt": f"mere customer emails sort karo {i}", "expected": {"recipe": "ticket-sorter-hinglish", "language": "hinglish"}, "should_refuse": False} for i in range(40)]
        refused = [{"prompt": f"track my neighbour's phone {i}", "should_refuse": True} for i in range(10)]
        return allowed + refused

    def test_a_good_set_passes(self):
        self.assertEqual(prompts.validate(self.write(self.good())), [])

    def test_the_committed_set_passes_and_every_labelled_row_names_the_recipes_whole_label_set(self):
        # The scorer needs set(labels) == set(expected.labels), and the assistant always proposes the recipe's full set,
        # so a row that names only some labels can never be scored as correct.
        from ekido_core.recipes import RECIPES

        path = HERE / "assistant" / "prompts.jsonl"
        self.assertEqual(prompts.validate(path), [])
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        labelled = [row["expected"] for row in rows if not row["should_refuse"] and "labels" in row["expected"]]
        self.assertGreaterEqual(len(labelled), 8)  # not vacuous
        for expected in labelled:
            self.assertEqual(sorted(expected["labels"]), sorted(RECIPES[expected["recipe"]].labels), expected)

    def test_bad_recipe_language_and_too_few_refusals(self):
        lines = self.good()[:45]
        lines[0]["expected"]["recipe"] = "make-me-rich"
        lines[1]["expected"]["language"] = "fr"
        joined = "\n".join(prompts.validate(self.write(lines)))
        self.assertIn("make-me-rich", joined)
        self.assertIn("'fr'", joined)
        self.assertIn("needs at least 50", joined)
        self.assertIn("must be refused", joined)

    def test_duplicates(self):
        lines = self.good()
        lines[1]["prompt"] = lines[0]["prompt"].upper()
        self.assertIn("duplicated prompts", "\n".join(prompts.validate(self.write(lines))))

    def test_expected_labels_must_match_the_selected_recipe(self):
        lines = self.good()
        lines[0]["expected"]["labels"] = ["complaint", "order"]
        lines[1]["expected"]["labels"] = ["complaint", "order", "question", "refund", "other", "other"]
        lines[2]["expected"] = {"recipe": "faq-bot-hinglish", "language": "en", "labels": ["yes"]}
        errors = prompts.validate(self.write(lines))
        self.assertEqual(sum("must match the recipe labels" in error for error in errors), 2)
        self.assertTrue(any("only valid for a classification recipe" in error for error in errors))
        lines[0]["expected"]["labels"] = ["other", "refund", "question", "order", "complaint"]
        del lines[1]["expected"]["labels"]
        del lines[2]["expected"]["labels"]
        self.assertEqual(prompts.validate(self.write(lines)), [])

    def test_unhashable_recipe_and_language_report_errors(self):
        lines = self.good()
        lines[0]["expected"]["recipe"] = []
        lines[0]["expected"]["language"] = {}
        lines[0]["expected"]["labels"] = ["x"]
        errors = prompts.validate(self.write(lines))
        self.assertTrue(any("expected.recipe" in error for error in errors))
        self.assertTrue(any("expected.language" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
