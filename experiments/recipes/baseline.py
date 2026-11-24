"""Scores an untrained base model on a recipe's test set: the number a fine-tuned model has to beat.

    python experiments/recipes/baseline.py experiments/recipes/ticket-sorter-hinglish --model Qwen/Qwen2.5-0.5B-Instruct
    python experiments/recipes/baseline.py <folder> --model Qwen/Qwen2.5-1.5B-Instruct --device cuda

It uses exactly what a job uses: the recipe's prompt (ekido_core.recipes), greedy generation one prompt at a time
(ekido_runtime.llm.generate_answers) and the recipe's pass rule. The base model gets the same plain prompt a
fine-tuned one is trained on, not a chat template, so the two scores are comparable.

Writes experiments/results/baselines/<recipe>-<model>.json with the pass rate, the mean metric score, the number of
examples, the model's pinned commit and the date. Run validate_dataset.py on the folder first.
Needs torch and transformers, and downloads the model on first use. Ask before running it on a laptop.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "packages" / "ekido_core"), str(ROOT / "workers" / "runtime")]

from ekido_core.job_spec import LLM_BASES  # noqa: E402
from ekido_core.recipes import eval_set_hash, passes, recipe, score  # noqa: E402


def read_test(folder: Path) -> list[dict]:
    with (folder / "test.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def source_sha256(function) -> str:
    """Hash the underlying implementation, including for decorated functions."""
    return hashlib.sha256(Path(inspect.getfile(inspect.unwrap(function))).read_bytes()).hexdigest()


def summarise(recipe_id: str, rows: list[dict], answers: list[str]) -> dict:
    """The result for a set of answers. Separate from the model so it can be tested without one."""
    r = recipe(recipe_id)
    references = [row[r.columns[1]] for row in rows]
    passed = [passes(recipe_id, a, ref) for a, ref in zip(answers, references)]
    return {
        "recipe_id": recipe_id,
        "metric": r.metric,
        "pass_rate": sum(passed) / len(passed),
        "score": score(recipe_id, answers, references),
        "examples": len(rows),
        "eval_set_hash": eval_set_hash(recipe_id, rows),
        "samples": [{"reference": ref, "answer": a, "passed": p} for ref, a, p in list(zip(references, answers, passed))[:10]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="experiments/recipes/<recipe>, holding test.csv")
    parser.add_argument("--model", required=True, choices=LLM_BASES)
    parser.add_argument("--revision", help="the model's commit; the current one is looked up and recorded if omitted")
    parser.add_argument("--runtime-path", type=Path, help="path to ekido-workers/runtime after the repository split")
    parser.add_argument("--device", default=None, help="cuda or cpu; cuda is used when available")
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--out", type=Path, default=ROOT / "experiments" / "results" / "baselines")
    args = parser.parse_args(argv)

    if args.runtime_path is not None:
        runtime_path = args.runtime_path.resolve()
        if not (runtime_path / "ekido_runtime" / "llm.py").is_file():
            parser.error(f"--runtime-path must contain ekido_runtime/llm.py: {runtime_path}")
        sys.path.insert(0, str(runtime_path))

    import torch
    from huggingface_hub import HfApi
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from ekido_runtime.llm import generate_answers

    r = recipe(args.folder.name)
    rows = read_test(args.folder)
    revision = args.revision or HfApi().model_info(args.model).sha
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=revision)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=revision, torch_dtype=torch.float32).to(device)

    started = time.perf_counter()
    prompts = [r.prompt(row[r.columns[0]]) for row in rows]
    answers = generate_answers(model, tokenizer, prompts, max_new_tokens=r.max_answer_tokens,
                               max_prompt_tokens=args.max_seq_length - r.max_answer_tokens, device=device)
    result = summarise(r.recipe_id, rows, answers)
    result.update(model=args.model, model_revision=revision, device=device, seconds=round(time.perf_counter() - started, 1),
                  run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), max_seq_length=args.max_seq_length,
                  code_sha256={"baseline": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               "recipes": hashlib.sha256(Path(inspect.getfile(recipe)).read_bytes()).hexdigest(),
                               "runtime": source_sha256(generate_answers)})

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{r.recipe_id}-{args.model.split('/')[-1].lower()}.json"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"{r.recipe_id} on {args.model}: {result['pass_rate']:.1%} of {result['examples']} passed (mean {r.metric} {result['score']:.3f})")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
