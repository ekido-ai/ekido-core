"""Audit the saved gateway benchmark without rerunning a GPU model."""
import ast
import base64
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
result = json.loads((HERE / 'results.json').read_text(encoding='utf-8'))
tree = ast.parse((HERE / 'run.py').read_text(encoding='utf-8'))
values = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in {'GATEWAY_ARCHIVES', 'GATEWAY_HASHES', 'GATEWAY_REVISIONS'}:
            values[node.targets[0].id] = ast.literal_eval(node.value)
assert values['GATEWAY_REVISIONS'] == result['source_revisions']
assert values['GATEWAY_HASHES'] == result['source_archive_sha256']
for name, encoded in values['GATEWAY_ARCHIVES'].items():
    assert hashlib.sha256(base64.b64decode(encoded)).hexdigest() == values['GATEWAY_HASHES'][name]
assert result['gpu'] == 'Tesla T4' and result['concurrency'] == 1
assert result['warmup_requests'] == 5 and result['usage_records_verified'] == 45
samples = result['samples']
assert len(samples) == result['requests'] == 40
for sample in samples:
    assert math.isfinite(sample['latency_ms']) and sample['latency_ms'] > 0
    usage = sample['usage']
    assert usage['prompt_tokens'] >= 0 and usage['completion_tokens'] >= 0
    assert usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']
latencies = sorted(sample['latency_ms'] for sample in samples)
assert math.isclose(result['latency_ms_p95_nearest_rank'], latencies[math.ceil(.95 * len(latencies)) - 1], rel_tol=1e-12)
assert math.isclose(result['latency_ms_mean'], sum(latencies) / len(latencies), rel_tol=1e-12)
print(f"PASS: {len(samples)} latencies, token counts, p95, mean and embedded source hashes")
