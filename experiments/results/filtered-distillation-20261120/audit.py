"""Check saved rows, checkpoint lineage and independently re-run predictions."""
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'packages' / 'ekido_core'))
from ekido_core.canonical import document_hash  # noqa: E402
from ekido_core.recipes import eval_set_hash, passes, recipe, score  # noqa: E402


def normalise(value):
    return ' '.join(str(value).casefold().split())


for name in ('invoice-fields', 'faq-bot-hinglish'):
    folder = HERE / name
    spec = json.loads((folder / 'student_spec.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder / 'student/checkpoints/step-50/manifest.json').read_text(encoding='utf-8'))
    trainer = json.loads((folder / 'student/evidence.json').read_text(encoding='utf-8'))
    rerun = json.loads((HERE / 'reevaluation' / (name + '.json')).read_text(encoding='utf-8'))
    blob = (folder / 'student_dataset.jsonl').read_bytes()
    assert hashlib.sha256(blob).hexdigest() == spec['dataset']['sha256'] == manifest['dataset_sha256']
    assert len(blob) == spec['dataset']['bytes']
    assert manifest['logical_step'] == 50 and manifest['immutable_hash'] == document_hash(spec)
    records = [json.loads(line) for line in blob.decode('utf-8').splitlines() if line.strip()]
    training = [row for row in records if row['split'] == 'train']
    test = [row for row in records if row['split'] == 'test']
    seeds = json.loads((folder / 'seeds.json').read_text(encoding='utf-8'))
    r = recipe(name)
    source, target = r.columns
    inputs = [normalise(row[source]) for row in training]
    assert len(seeds) == 30 and len(inputs) == len(set(inputs))
    assert not set(inputs) & {normalise(row[source]) for row in seeds + test}
    for row in training:
        if name == 'invoice-fields':
            expected = json.loads(row[target])
            assert not re.search(r'["\'](?:vendor|invoice_no|date|total|gstin)["\']\s*:', row[source], re.IGNORECASE)
            for key in ('vendor', 'invoice_no', 'date', 'total', 'gstin'):
                value = normalise(expected[key])
                assert value and re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', normalise(row[source]))
        else:
            assert normalise(row[target]) not in normalise(row[source])
            assert not re.search(r'\bnew\s+question\s*:', row[source], re.IGNORECASE)
    assert eval_set_hash(name, test) == trainer['eval']['eval_set_hash'] == rerun['eval_set_hash']
    outputs = rerun['predictions']
    assert len(outputs) == len(test) == rerun['examples']
    for row, prediction in zip(test, outputs):
        assert (prediction['input'], prediction['reference']) == (row[source], row[target])
        assert prediction['passed'] == passes(name, prediction['answer'], prediction['reference'])
    rate = sum(x['passed'] for x in outputs) / len(outputs)
    mean = score(name, [x['answer'] for x in outputs], [x['reference'] for x in outputs])
    assert rate == trainer['eval']['pass_rate'] == rerun['rerun_pass_rate'] == rerun['trainer_pass_rate']
    assert math.isclose(mean, trainer['eval']['score'], abs_tol=1e-6)
    assert math.isclose(mean, rerun['rerun_score'], abs_tol=1e-6)
    print(f'{name}: {sum(x["passed"] for x in outputs)}/{len(outputs)}; dataset, filters and checkpoint lineage verified')
