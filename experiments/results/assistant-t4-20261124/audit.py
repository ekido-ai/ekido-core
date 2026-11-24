"""Audit the saved assistant evaluation and its corrected prompt set."""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
result = json.loads((HERE / 'summary.json').read_text(encoding='utf-8'))
# Git can check out text as CRLF on Windows; the run hashed LF source bytes.
original = (HERE / 'original-prompts.jsonl').read_bytes().replace(b'\r\n', b'\n')
corrected = (HERE / 'corrected-prompts.jsonl').read_bytes().replace(b'\r\n', b'\n')
assert hashlib.sha256(original).hexdigest() == result['original_prompt_sha256']
assert hashlib.sha256(corrected).hexdigest() == result['prompt_set_sha256']
before = [json.loads(line) for line in original.decode('utf-8').splitlines() if line.strip()]
after = [json.loads(line) for line in corrected.decode('utf-8').splitlines() if line.strip()]
assert len(before) == len(after) == 50
changed = []
for index, (old, new) in enumerate(zip(before, after), 1):
    if old != new:
        changed.append(index)
        old_copy, new_copy = copy.deepcopy(old), copy.deepcopy(new)
        old_copy['expected'].pop('labels'); new_copy['expected'].pop('labels')
        assert old_copy == new_copy
assert changed == result['corrected_label_cases'] == [1, 2, 3, 6, 8, 36]
tree = ast.parse((HERE / 'run.py').read_text(encoding='utf-8'))
values = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in {'PAYLOAD', 'SOURCE_HASH', 'PROMPTS', 'PROMPT_HASH', 'CORE', 'PLATFORM'}:
            values[node.targets[0].id] = ast.literal_eval(node.value)
assert hashlib.sha256(base64.b64decode(values['PAYLOAD'])).hexdigest() == values['SOURCE_HASH']
assert base64.b64decode(values['PROMPTS']) == corrected
assert values['PROMPT_HASH'] == result['prompt_set_sha256']
assert values['CORE'] == result['core_commit'] and values['PLATFORM'] == result['platform_commit']
records = result['records']
assert result['cases'] == result['attempted'] == len(records) == 50 and result['complete']
for index, (case, row) in enumerate(zip(after, records), 1):
    assert row['case'] == index
    assert row['prompt_sha256'] == hashlib.sha256(case['prompt'].encode()).hexdigest()
    assert len(row['response_sha256']) == 64
    assert row['result'] == ('refused' if case['should_refuse'] else 'invalid_spec')
allowed = sum(not row['should_refuse'] for row in after)
refused = sum(row['result'] == 'refused' for row in records)
valid = sum(row['result'] == 'valid' for row in records)
matched = sum(row.get('matches_expected') is True for row in records)
assert (allowed, refused, valid, matched) == (40, 10, 0, 0)
assert result['valid_spec_rate'] == valid / allowed and result['matched_rate'] == matched / allowed
assert result['all_refused'] and not result['valid_spec_target_met']
print('PASS: prompt hashes, six label corrections, source archive and 50 recorded outcomes')
