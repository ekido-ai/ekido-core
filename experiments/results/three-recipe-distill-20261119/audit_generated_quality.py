"""Count literal target mismatches and answer echoes in the stored generated rows."""
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_train(name):
    path = ROOT / name / 'student_dataset.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return [row for row in rows if row['split'] == 'train']


def normalise(value):
    return ' '.join(str(value).casefold().split())


def audit():
    invoice = read_train('invoice-fields')
    missing = collections.Counter()
    for row in invoice:
        target = json.loads(row['json'])
        text = normalise(row['text'])
        absent = [key for key, value in target.items() if normalise(value) not in text]
        missing['missing_any_target_value'] += bool(absent)
        for key in absent:
            missing['missing_' + key] += 1
    faq = read_train('faq-bot-hinglish')
    counts = collections.Counter()
    for row in faq:
        question, answer = normalise(row['question']), normalise(row['answer'])
        counts['answer_verbatim_in_question'] += bool(answer and answer in question)
        counts['new_question_marker'] += bool(re.search(r'\bnew\s+question\s*:', question))
    return {'invoice': {'rows': len(invoice), **missing}, 'faq': {'rows': len(faq), **counts}}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, ensure_ascii=False))
