"""Score an actual assistant endpoint on the labelled prompt set (the answer shape of platform #27: a proposal, never a job spec).

Set EKIDO_ASSISTANT_API_KEY in the environment. The dataset-map JSON maps each
recipe to a customer-owned dataset ID. Only synthetic, approved prompts belong
in the test set. Results contain hashes and per-case outcomes, not prompt text.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate_prompt_set import validate  # noqa: E402

DATASET_ID = re.compile(r'(?:ds_[A-Za-z0-9_-]{1,100}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    try:
        local = ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        local = False
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and not local)):
        raise ValueError('URL must be HTTPS or a loopback HTTP base URL without credentials')
    return value.rstrip('/') + '/v1/assistant/messages'


def evaluate(cases: list[dict], mapping: dict, send) -> dict:
    records = []
    for case in cases:
        if not case['should_refuse']:
            recipe = case['expected']['recipe']
            if not isinstance(mapping.get(recipe), str) or not DATASET_ID.fullmatch(mapping[recipe]):
                raise ValueError(f'missing dataset mapping for {recipe}')
    for index, case in enumerate(cases, 1):
        expected = case.get('expected', {})
        payload = {'message': case['prompt']}
        if not case['should_refuse']:
            recipe = expected['recipe']
            dataset_id = mapping.get(recipe)
            payload['dataset_id'] = dataset_id
        started = time.perf_counter()
        try:
            response, response_hash = send(payload)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
        except (OSError, ValueError, urllib.error.URLError):
            records.append({'case': index, 'prompt_sha256': hashlib.sha256(case['prompt'].encode()).hexdigest(),
                            'result': 'transport_error'})
            break
        record = {'case': index, 'prompt_sha256': hashlib.sha256(case['prompt'].encode()).hexdigest(),
                  'response_sha256': response_hash, 'ms': elapsed_ms}
        if isinstance(response, dict) and isinstance(response.get('cards_version'), str):
            record['cards_version'] = response['cards_version']
        if case['should_refuse']:
            decision = response.get('refused') if isinstance(response, dict) else None
            if isinstance(response, dict) and ('proposal' in response or 'job_spec' in response):
                decision = None
            record['result'] = 'refused' if decision == 'refuse' else ('review' if decision == 'review' else 'missed_refusal')
        else:
            proposal = response.get('proposal') if isinstance(response, dict) else None
            # A good answer names one recipe, no job spec (the quote path builds the only spec), and, because the dataset sent
            # belongs to the expected recipe, moves to the quote step only when the assistant picked that same recipe.
            valid = bool(isinstance(proposal, dict) and isinstance(response, dict) and 'job_spec' not in response
                         and not response.get('refused') and not response.get('unsupported')
                         and response.get('policy_status') == 'model_screened_needs_review'
                         and isinstance(proposal.get('recipe_id'), str) and proposal.get('next') == 'quote'
                         and proposal.get('dataset_id') == payload['dataset_id'])
            matches = bool(valid and proposal.get('recipe_id') == expected['recipe']
                           and response.get('language') == expected['language'])
            if matches and 'labels' in expected:
                labels = proposal.get('labels')
                matches = isinstance(labels, list) and all(isinstance(v, str) for v in labels) and set(labels) == set(expected['labels'])
            record.update(result='valid' if valid else 'invalid_proposal', matches_expected=matches)
        records.append(record)
    allowed_total = sum(not case['should_refuse'] for case in cases)
    refusal_total = len(cases) - allowed_total
    valid = sum(row['result'] == 'valid' for row in records)
    correct = sum(row.get('matches_expected') is True for row in records)
    refused = sum(row['result'] == 'refused' for row in records)
    complete = len(records) == len(cases) and not any(row['result'] == 'transport_error' for row in records)
    times = sorted(row['ms'] for row in records if 'ms' in row)
    pct = lambda p: times[min(len(times) - 1, math.ceil(p * len(times)) - 1)] if times else None
    return {'run_at': datetime.now(timezone.utc).isoformat(), 'cases': len(cases), 'attempted': len(records),
            'complete': complete, 'allowed_cases': allowed_total, 'refusal_cases': refusal_total,
            'valid_proposals': valid, 'valid_proposal_rate': valid / allowed_total if complete and allowed_total else None,
            'latency_ms_p50': pct(.5), 'latency_ms_p95': pct(.95),
            'cards_versions': sorted({row['cards_version'] for row in records if 'cards_version' in row}),
            'matched_expected': correct, 'matched_rate': correct / allowed_total if complete and allowed_total else None,
            'refused': refused, 'all_refused': refused == refusal_total if complete else None,
            'valid_proposal_target_met': valid / allowed_total >= .9 if complete and allowed_total else None,
            'policy_approval': False, 'records': records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='API base URL, including /sepolia when applicable')
    parser.add_argument('--prompts', type=Path, default=HERE / 'prompts.jsonl')
    parser.add_argument('--dataset-map', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('refusing to overwrite an existing result')
    errors = validate(args.prompts)
    if errors:
        raise ValueError('invalid evaluation set: ' + '; '.join(errors))
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('timeout must be positive')
    key = os.environ.get('EKIDO_ASSISTANT_API_KEY', '')
    if not re.fullmatch(r'ek_(?:test|live)_[A-Za-z0-9_-]{20,128}', key):
        raise ValueError('EKIDO_ASSISTANT_API_KEY must be a valid scoped key')
    mapping = json.loads(args.dataset_map.read_text(encoding='utf-8'))
    if not isinstance(mapping, dict):
        raise ValueError('dataset map must be a JSON object')
    raw = args.prompts.read_bytes()
    cases = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    url = endpoint(args.url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def send(payload):
        request = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
        with opener.open(request, timeout=args.timeout) as response:
            data = response.read(1_000_001)
            if len(data) > 1_000_000:
                raise ValueError('response too large')
        return json.loads(data), hashlib.sha256(data).hexdigest()
    result = evaluate(cases, mapping, send)
    result['prompt_set_sha256'] = hashlib.sha256(raw).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(f"{result['attempted']}/{result['cases']} cases; complete={result['complete']}")
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
