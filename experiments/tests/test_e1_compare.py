import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

PATH = Path(__file__).resolve().parents[1] / 'e1' / 'compare.py'
spec = importlib.util.spec_from_file_location('e1_compare', PATH)
e1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e1)


class E1Comparison(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = [{'text': 'good product', 'label': 'positive'}, {'text': 'poor service', 'label': 'negative'}]
        self.dataset = self.root / 'test.jsonl'
        self.train = self.root / 'train.jsonl'
        self.review = self.root / 'review.json'
        self.dataset.write_text(''.join(json.dumps(row) + '\n' for row in self.rows), encoding='utf-8', newline='\n')
        self.train.write_text(json.dumps({'text': 'different example', 'label': 'neutral'}) + '\n', encoding='utf-8')
        self.digest = e1.sha(self.dataset.read_bytes())
        self.review.write_text(json.dumps({'recipe_id': 'review-sentiment', 'dataset_sha256': self.digest,
                                           'confirmed': True, 'reviewer': 'test reviewer',
                                           'evidence': 'test-only attestation'}), encoding='utf-8')
        self.runs = {}
        self.contents = {}
        for role in e1.ROLES:
            self.runs[role] = self.root / (role + '.json')
            self.contents[role] = {'role': role, 'dataset_sha256': self.digest, 'model': role,
                'model_revision': 'synthetic-test-version',
                'records': [{'input_sha256': e1.sha(row['text'].encode()), 'answer': row['label'],
                             'input_tokens': 100, 'output_tokens': 10} for row in self.rows],
                'price': {'kind': 'tokens', 'currency': 'USD', 'source_url': 'https://example.org/pricing',
                          'date': '2026-11-24', 'assumptions': 'synthetic unit test',
                          'input_usd_per_million': '1', 'output_usd_per_million': '2'}}
        self.save_runs()

    def save_runs(self):
        for role in e1.ROLES:
            self.runs[role].write_text(json.dumps(self.contents[role]), encoding='utf-8')

    def compare(self):
        return e1.compare(self.dataset, self.train, self.review, self.runs)

    def test_results_and_token_cost_derive_from_matched_records(self):
        self.contents['student']['records'][1]['answer'] = 'positive'
        self.save_runs()
        result = self.compare()
        self.assertEqual(result['runs']['student']['passed'], 1)
        self.assertEqual(result['runs']['student']['pass_rate'], .5)
        self.assertEqual(result['runs']['api']['passed'], 2)
        self.assertEqual(result['runs']['api']['cost']['estimated_usd_per_1000'], '0.12000')
        self.assertEqual(result['runs']['api']['cost']['rates']['input_usd_per_million'], '1')
        self.assertFalse(result['review_attestation']['independently_authenticated'])

    def test_rejects_unreviewed_or_changed_data(self):
        self.review.write_text(json.dumps({'recipe_id': 'review-sentiment', 'dataset_sha256': self.digest,
                                           'confirmed': False, 'reviewer': 'x', 'evidence': 'x'}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'attestation'):
            self.compare()
        self.review.write_text(json.dumps({'recipe_id': 'review-sentiment', 'dataset_sha256': '0' * 64,
                                           'confirmed': True, 'reviewer': 'x', 'evidence': 'x'}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exact dataset hash'):
            self.compare()

    def test_rejects_train_overlap_missing_swapped_or_duplicate_results(self):
        self.train.write_text(json.dumps(self.rows[0]) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'training-overlapping'):
            self.compare()
        self.train.write_text(json.dumps({'text': 'other', 'label': 'neutral'}) + '\n', encoding='utf-8')
        self.contents['base']['records'].reverse()
        self.save_runs()
        with self.assertRaisesRegex(ValueError, 'match the frozen inputs'):
            self.compare()
        self.contents['base']['records'] = self.contents['base']['records'][:1]
        self.save_runs()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.compare()
        self.contents['base']['records'] = [self.contents['base']['records'][0]] * 2
        self.save_runs()
        with self.assertRaisesRegex(ValueError, 'match the frozen inputs'):
            self.compare()

    def test_rejects_bad_pricing_and_preserves_gpu_estimate_scope(self):
        self.contents['api']['price']['source_url'] = 'https://secret@example.org/prices'
        self.save_runs()
        with self.assertRaisesRegex(ValueError, 'HTTPS source'):
            self.compare()
        self.contents['api']['price']['source_url'] = 'https://example.org/pricing'
        self.contents['api']['records'][0]['input_tokens'] = -1
        self.save_runs()
        with self.assertRaisesRegex(ValueError, 'usage'):
            self.compare()
        self.contents['api']['records'][0]['input_tokens'] = 100
        self.contents['api']['records'][0]['output_tokens'] = 0
        self.contents['api']['records'][1]['output_tokens'] = 0
        self.contents['api']['records'][0]['input_tokens'] = 0
        self.contents['api']['records'][1]['input_tokens'] = 0
        self.save_runs()
        with self.assertRaisesRegex(ValueError, 'nonzero measured usage'):
            self.compare()
        self.contents['api']['records'][0]['input_tokens'] = 100
        self.contents['api']['records'][1]['input_tokens'] = 100
        self.contents['student']['price'] = {'kind': 'gpu_time', 'currency': 'USD',
            'source_url': 'https://example.org/gpu', 'date': '2026-11-24', 'assumptions': 'GPU only',
            'observed_seconds': '3.6', 'usd_per_hour': '0.35'}
        self.save_runs()
        cost = self.compare()['runs']['student']['cost']
        self.assertEqual(cost['kind'], 'gpu_time')
        self.assertEqual(cost['estimated_usd_per_1000'], '0.17500')
        self.assertEqual(cost['assumptions'], 'GPU only')

    def test_atomic_publish_does_not_overwrite_or_leave_partial_output(self):
        out = self.root / 'result.json'
        with mock.patch.object(e1.os, 'link', side_effect=OSError('publish failed')):
            with self.assertRaises(OSError):
                e1.write_new(out, self.compare())
        self.assertFalse(out.exists())
        self.assertEqual(list(self.root.glob('.e1-*')), [])
        e1.write_new(out, self.compare())
        initial = out.read_bytes()
        with self.assertRaises(FileExistsError):
            e1.write_new(out, self.compare())
        self.assertEqual(out.read_bytes(), initial)

    def test_cli_writes_a_complete_synthetic_result(self):
        out = self.root / 'cli-result.json'
        command = [sys.executable, str(PATH), '--dataset', str(self.dataset), '--train', str(self.train),
                   '--review', str(self.review), '--base', str(self.runs['base']),
                   '--student', str(self.runs['student']), '--api', str(self.runs['api']), '--out', str(out)]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result['examples'], 2)
        self.assertEqual(result['runs']['api']['passed'], 2)

    def test_comparison_does_not_make_network_calls_or_include_environment(self):
        with mock.patch('socket.socket', side_effect=AssertionError('unexpected network')), \
             mock.patch.dict(os.environ, {'E1_TEST_SECRET': 'synthetic-secret-must-not-appear'}):
            output = json.dumps(self.compare())
        self.assertNotIn('synthetic-secret-must-not-appear', output)

    def test_invoice_target_requires_all_fields(self):
        rows = [{'text': 'invoice A', 'json': '{}'}]
        self.dataset.write_text(json.dumps(rows[0]) + '\n', encoding='utf-8')
        self.train.write_text(json.dumps({'text': 'invoice B', 'json': '{}'}) + '\n', encoding='utf-8')
        digest = e1.sha(self.dataset.read_bytes())
        self.review.write_text(json.dumps({'recipe_id': 'invoice-fields', 'dataset_sha256': digest,
            'confirmed': True, 'reviewer': 'x', 'evidence': 'x'}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'required fields'):
            self.compare()

    def test_invoice_comparison_uses_recipe_fields(self):
        target = json.dumps({'vendor': 'Acme', 'invoice_no': 'INV-1', 'date': '2026-01-02',
                             'total': '42.00', 'gstin': 'ABC123'})
        row = {'text': 'invoice A', 'json': target}
        self.dataset.write_text(json.dumps(row) + '\n', encoding='utf-8', newline='\n')
        self.train.write_text(json.dumps({'text': 'invoice B', 'json': target}) + '\n', encoding='utf-8')
        digest = e1.sha(self.dataset.read_bytes())
        self.review.write_text(json.dumps({'recipe_id': 'invoice-fields', 'dataset_sha256': digest,
            'confirmed': True, 'reviewer': 'x', 'evidence': 'x'}), encoding='utf-8')
        for role in e1.ROLES:
            self.contents[role]['dataset_sha256'] = digest
            self.contents[role]['records'] = [{'input_sha256': e1.sha(row['text'].encode()), 'answer': target,
                                               'input_tokens': 10, 'output_tokens': 5}]
        self.contents['student']['records'][0]['answer'] = target.replace('42.00', '43.00')
        self.save_runs()
        result = self.compare()
        self.assertEqual(result['runs']['base']['passed'], 1)
        self.assertEqual(result['runs']['student']['passed'], 0)
        self.assertAlmostEqual(result['runs']['student']['results'][0]['score'], .8)


if __name__ == '__main__':
    main()
