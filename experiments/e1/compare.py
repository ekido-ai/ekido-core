"""Compare saved E1 outputs on a frozen, attested set without network access."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/ekido_core'))
from ekido_core.recipes import passes, recipe, score_one  # noqa: E402

ROLES = ('base', 'student', 'api')
RECIPES = {'review-sentiment', 'invoice-fields'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise(text: str) -> str:
    return ' '.join(text.casefold().split())


def read_bounded(path: Path, limit: int) -> bytes:
    with Path(path).open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('input file exceeds size limit')
    return data


def amount(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be an exact decimal string')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f'invalid {name}') from None
    if not number.is_finite() or number < 0 or number > Decimal('1000000000') or number.as_tuple().exponent < -12:
        raise ValueError(f'invalid {name}')
    return number


def price_observation(price: dict, records: list[dict]) -> dict:
    """Compute an explicitly estimated cost; metadata does not prove prices genuine."""
    if not isinstance(price, dict) or price.get('currency') != 'USD':
        raise ValueError('price must specify USD')
    url = price.get('source_url')
    parsed = urlparse(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError('price needs an HTTPS source')
    try:
        checked = date.fromisoformat(price['date']).isoformat()
    except (KeyError, ValueError, TypeError):
        raise ValueError('price needs an ISO date') from None
    if not isinstance(price.get('assumptions'), str) or not price['assumptions'].strip():
        raise ValueError('price assumptions are required')
    with localcontext() as context:
        context.prec = 50
        if price.get('kind') == 'tokens':
            inp = sum(row['input_tokens'] for row in records)
            out = sum(row['output_tokens'] for row in records)
            if inp + out == 0:
                raise ValueError('token-priced run needs nonzero measured usage')
            input_rate = amount(price.get('input_usd_per_million'), 'input price')
            output_rate = amount(price.get('output_usd_per_million'), 'output price')
            total = (Decimal(inp) * input_rate + Decimal(out) * output_rate) / 1_000_000
            inputs = {'input_tokens': inp, 'output_tokens': out}
            rates = {'input_usd_per_million': str(input_rate), 'output_usd_per_million': str(output_rate)}
        elif price.get('kind') == 'gpu_time':
            seconds = amount(price.get('observed_seconds'), 'observed seconds')
            if seconds <= 0:
                raise ValueError('observed seconds must be positive')
            hourly_rate = amount(price.get('usd_per_hour'), 'hourly price')
            total = seconds * hourly_rate / 3600
            inputs = {'observed_seconds': str(seconds)}
            rates = {'usd_per_hour': str(hourly_rate)}
        else:
            raise ValueError('price kind must be tokens or gpu_time')
        per_1000 = total * 1000 / len(records)
    return {'kind': price['kind'], 'currency': 'USD', 'price_source_url': url, 'price_date': checked,
            'assumptions': price['assumptions'], 'usage': inputs, 'rates': rates, 'estimated_total_usd': str(total),
            'estimated_usd_per_1000': str(per_1000)}


def compare(dataset_file: Path, train_file: Path, review_file: Path, run_files: dict[str, Path]) -> dict:
    """Compare complete saved outputs; human review is recorded, not independently authenticated."""
    if set(run_files) != set(ROLES):
        raise ValueError('exactly base, student and api runs are required')
    raw = read_bounded(dataset_file, 20_000_000)
    dataset_hash = sha(raw)
    review_raw = read_bounded(review_file, 1_000_000)
    review = json.loads(review_raw)
    if not isinstance(review, dict):
        raise ValueError('expected review JSON object')
    name = review.get('recipe_id')
    if not isinstance(name, str) or name not in RECIPES or review.get('dataset_sha256') != dataset_hash:
        raise ValueError('review must name an allowed recipe and exact dataset hash')
    if (review.get('confirmed') is not True or not isinstance(review.get('reviewer'), str)
            or not review['reviewer'].strip() or not isinstance(review.get('evidence'), str)
            or not review['evidence'].strip()):
        raise ValueError('a recorded human-review attestation and evidence are required')
    r = recipe(name)
    source, target = r.columns
    train_raw = read_bounded(train_file, 50_000_000)
    try:
        rows = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        training = [json.loads(line) for line in train_raw.decode('utf-8').splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('invalid JSONL data') from None
    if not 1 <= len(rows) <= 1000 or not 1 <= len(training) <= 100_000:
        raise ValueError('need held-out and training rows')
    for row in rows + training:
        if (not isinstance(row, dict) or not isinstance(row.get(source), str) or not row[source].strip()
                or len(row[source]) > 20_000 or not isinstance(row.get(target), str)
                or not row[target].strip() or len(row[target]) > 20_000):
            raise ValueError('invalid dataset row')
        if r.labels and row[target].strip().casefold() not in r.labels:
            raise ValueError('invalid classification target')
        if name == 'invoice-fields':
            try:
                fields = json.loads(row[target])
            except (TypeError, ValueError):
                raise ValueError('invalid invoice target') from None
            required = ('vendor', 'invoice_no', 'date', 'total', 'gstin')
            if not isinstance(fields, dict) or any(not isinstance(fields.get(k), str) or not fields[k].strip() for k in required):
                raise ValueError('invoice target must have all required fields')
    heldout = [normalise(row[source]) for row in rows]
    if len(set(heldout)) != len(heldout) or set(heldout) & {normalise(row[source]) for row in training}:
        raise ValueError('duplicate or training-overlapping held-out input')
    expected_ids = [sha(row[source].encode('utf-8')) for row in rows]
    result = {'recipe_id': name, 'dataset_sha256': dataset_hash, 'metric': r.metric, 'floor': r.floor,
              'training_sha256': sha(train_raw), 'examples': len(rows),
              'review_attestation': {'reviewer': review['reviewer'], 'evidence': review['evidence'],
                                     'sha256': sha(review_raw), 'independently_authenticated': False}, 'runs': {}}
    for role in ROLES:
        run_bytes = read_bounded(run_files[role], 20_000_000)
        run = json.loads(run_bytes)
        if (not isinstance(run, dict) or run.get('role') != role or run.get('dataset_sha256') != dataset_hash
                or not isinstance(run.get('model'), str) or not run['model'].strip()
                or not isinstance(run.get('model_revision'), str) or not run['model_revision'].strip()):
            raise ValueError(f'{role}: run metadata does not match the frozen set')
        records = run.get('records')
        if not isinstance(records, list) or len(records) != len(rows):
            raise ValueError(f'{role}: incomplete records')
        items = []
        for expected, ref, record in zip(expected_ids, rows, records):
            if (not isinstance(record, dict) or record.get('input_sha256') != expected
                    or not isinstance(record.get('answer'), str) or len(record['answer']) > 100_000
                    or type(record.get('input_tokens')) is not int or not 0 <= record['input_tokens'] <= 1_000_000_000
                    or type(record.get('output_tokens')) is not int or not 0 <= record['output_tokens'] <= 1_000_000_000):
                raise ValueError(f'{role}: records must match the frozen inputs in order and include usage')
            answer = record['answer']
            items.append({'input_sha256': expected, 'answer': answer, 'reference': ref[target],
                          'score': score_one(name, answer, ref[target]), 'passed': passes(name, answer, ref[target])})
        result['runs'][role] = {'model': run['model'], 'model_revision': run['model_revision'], 'source_sha256': sha(run_bytes),
                                'passed': sum(item['passed'] for item in items),
                                'pass_rate': sum(item['passed'] for item in items) / len(items),
                                'cost': price_observation(run.get('price'), records), 'results': items}
    return result


def write_new(path: Path, result: dict) -> None:
    """Publish only complete output, without overwriting another writer's file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.e1-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write((json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(name, path)  # atomic create, fails rather than replacing an existing result
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset', 'train', 'review', 'base', 'student', 'api', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args(argv)
    result = compare(args.dataset, args.train, args.review, {name: getattr(args, name) for name in ROLES})
    write_new(args.out, result)
    print(f"Compared {result['examples']} examples on {result['recipe_id']}; result: {args.out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
