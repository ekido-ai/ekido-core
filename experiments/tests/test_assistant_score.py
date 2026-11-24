import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'assistant' / 'score.py'
spec = importlib.util.spec_from_file_location('assistant_score', SCRIPT)
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)

DATASET = '0b8f6c1e-3d2a-4c55-9a47-1f6e2d9c7a10'


def proposal(recipe='review-sentiment', **extra):
    return {'proposal': {'recipe_id': recipe, 'next': 'quote', 'dataset_id': DATASET, 'labels': ['neutral', 'positive', 'negative']},
            'language': 'en', 'policy_status': 'model_screened_needs_review', 'cards_version': 'abc123def456', **extra}


ALLOWED = {'prompt': 'synthetic allowed', 'should_refuse': False,
           'expected': {'recipe': 'review-sentiment', 'language': 'en', 'labels': ['positive', 'negative', 'neutral']}}


class AssistantScore(unittest.TestCase):
    def test_scores_real_response_shapes_and_exposes_missed_refusals(self):
        cases = [ALLOWED, {'prompt': 'synthetic banned', 'should_refuse': True}, {'prompt': 'synthetic review', 'should_refuse': True},
                 {'prompt': 'synthetic unsafe', 'should_refuse': True}]
        replies = iter([proposal(), {'refused': 'refuse'}, {'refused': 'review'}, {'refused': 'refuse', 'proposal': {'recipe_id': 'review-sentiment'}}])
        result = score.evaluate(cases, {'review-sentiment': DATASET}, lambda _: (next(replies), 'a' * 64))
        self.assertTrue(result['complete'])
        self.assertEqual((result['valid_proposal_rate'], result['matched_rate']), (1, 1))
        self.assertFalse(result['all_refused'])
        self.assertEqual([row['result'] for row in result['records']], ['valid', 'refused', 'review', 'missed_refusal'])
        self.assertEqual(result['cards_versions'], ['abc123def456'])
        self.assertIsNotNone(result['latency_ms_p50'])
        self.assertNotIn('synthetic allowed', json.dumps(result))

    def test_a_proposal_is_not_valid_unless_it_reaches_the_quote_for_the_dataset_sent(self):
        wrong_recipe = proposal('ticket-sorter-hinglish')
        wrong_recipe['proposal']['next'] = 'upload'  # the dataset is for another recipe, so the assistant asks for an upload
        for label, reply in {'wrong recipe': wrong_recipe, 'a job spec comes back': proposal(job_spec={'x': 1}), 'refused': {'refused': 'refuse'},
                             'unsupported': {'unsupported': True, 'reply': 'not yet'}, 'no proposal': {'reply': 'which one?'},
                             'wrong dataset': {**proposal(), 'proposal': {**proposal()['proposal'], 'dataset_id': 'someone-else'}},
                             'not screened': {k: v for k, v in proposal().items() if k != 'policy_status'}}.items():
            with self.subTest(label):
                result = score.evaluate([ALLOWED], {'review-sentiment': DATASET}, lambda _, r=reply: (r, 'a' * 64))
                self.assertEqual(result['valid_proposals'], 0)
                self.assertFalse(result['valid_proposal_target_met'])

    def test_a_valid_proposal_in_the_wrong_language_or_with_other_labels_does_not_match(self):
        for label, reply in {'language': {**proposal(), 'language': 'hi'}, 'labels': {**proposal(), 'proposal': {**proposal()['proposal'], 'labels': ['a', 'b']}}}.items():
            with self.subTest(label):
                result = score.evaluate([ALLOWED], {'review-sentiment': DATASET}, lambda _, r=reply: (r, 'a' * 64))
                self.assertEqual((result['valid_proposals'], result['matched_expected']), (1, 0))

    def test_missing_mappings_and_transport_failures_do_not_claim_success(self):
        calls = []
        with self.assertRaises(ValueError):
            score.evaluate([ALLOWED], {}, lambda body: calls.append(body))
        with self.assertRaises(ValueError):
            score.evaluate([ALLOWED], {'review-sentiment': 'not a dataset id'}, lambda body: calls.append(body))
        self.assertEqual(calls, [])

        def fail(_):
            raise OSError('offline')
        result = score.evaluate([ALLOWED], {'review-sentiment': DATASET}, fail)
        self.assertFalse(result['complete'])
        self.assertIsNone(result['valid_proposal_rate'])
        self.assertIsNone(result['all_refused'])

    def test_both_dataset_id_forms_are_accepted(self):
        for dataset in (DATASET, 'ds_test'):
            with self.subTest(dataset):
                result = score.evaluate([ALLOWED], {'review-sentiment': dataset}, lambda body: (proposal(), 'a' * 64))
                self.assertTrue(result['complete'])

    def test_http_requires_loopback_and_no_credentials(self):
        self.assertTrue(score.endpoint('http://127.0.0.1:8010').endswith('/v1/assistant/messages'))
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com?q=key'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                score.endpoint(url)


if __name__ == '__main__':
    unittest.main()
