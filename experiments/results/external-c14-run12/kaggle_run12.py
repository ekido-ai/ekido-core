#!/usr/bin/env python3
"""Ekido C14 (issue #18) run12 - PR #15 code, no full-data judge, Unicode-aware audit.

Changes vs run11/run11b, per Vaibhav + Codex review (2026-11-19):
- Code: ekido-workers PR #15 commit 558e8713be853447615a50306d8fc6567de5bf06
  (Devanagari punctuation + title-case trailing-label fix). The runner
  asserts the sha256 of the distill.py it imports. Core package pinned to
  ekido-core v0.4.2 (the version the workers repo pins), whose job_spec now
  carries the pinned model revisions - the student revision comes from
  there, not from a live lookup.
- NO C6 judge: that checkpoint was trained on the full labelled training
  set, so filtering with it would add labelled supervision beyond the 30
  seeds and break the 30-seed claim. Label verification in this run is the
  teacher's self-consistency only, reported as agreement, not proof.
- Generated-data cleaning: replacement-character rows dropped; a language
  screen (length, Unicode letter ratio, token-repetition) applied as a
  heuristic filter and reported as exactly that - a screen, not proof of
  language quality; removed rows are saved with their reasons.
- Duplicate/overlap checks use a Unicode-category tokenizer (letters,
  marks, numbers) so Devanagari words stay whole; no ASCII-only tokenizing.
- The 'other' class collapsed under verification in run11 (teacher
  self-agreement 0.167). The six 'other' seeds therefore get a larger
  generation budget (50 total vs 20) - still only 30 seeds, disclosed in
  the settings. Bad rows are never oversampled; only rows that pass every
  filter enter training.
- Ambiguity screen: seller-registration style rows in the evaluation sets
  are flagged and listed. Their labels are NOT changed; scores use the
  original labels, and the best model's accuracy on the flagged test rows
  is additionally reported on its own.
- Selection on validation only; the recipe test set is a historical
  comparison (used across v4-v12). No new approved held-out set exists;
  independent verification is pending.
"""
import csv, hashlib, json, os, random, re, shutil, subprocess, sys, threading, time, unicodedata
from collections import Counter
from pathlib import Path

SRC = next(p for p in [Path("/kaggle/input/ekido-core-verify-v12/src"),
                       Path("/kaggle/input/datasets/vaibhavparmar7002/ekido-core-verify-v12/src"),
                       Path("/kaggle/input/ekido-core-verify-v12/src")] if (p / "runtime").exists())
for _p in (str(SRC / "runtime"), str(SRC / "packages" / "ekido_core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
OUT = Path("/kaggle/working/out12"); OUT.mkdir(parents=True, exist_ok=True)
DATA = SRC / "data"
DEVICE = "cuda"
RECIPE_ID = "ticket-sorter-hinglish"
STUDENT_ID = "Qwen/Qwen2.5-1.5B-Instruct"
WORKERS_COMMIT = "558e8713be853447615a50306d8fc6567de5bf06"
CORE_COMMIT = "1d874ae48343e29a71e9729331fdd55ba1cfd75c (ekido-core v0.4.2)"
EXPECTED_SHA256 = {
    "runtime/ekido_runtime/distill.py": "cdb17d6d3596d6b25f5f50d20344a79d378413a55ea910d22595ee7b15bae633",
    "runtime/ekido_runtime/llm.py": "e3cb02a2cfad62dcf99484dd7759756897a1fe7239ea1e8bf880e6c63869bf6a",
    "runtime/ekido_runtime/train.py": "abb9153518e16bf43b399c0605bfac72970de67409035199f103e8d9e44e7178",
    "packages/ekido_core/ekido_core/recipes.py": "1c1a77ac39015a0e5f7700dd65a9cc3d890c82a3feebe22e566fc4650f607e80",
    "packages/ekido_core/ekido_core/job_spec.py": "a69557983f43a73bb15413011bc0d9b07f7c15d8e8174f3bf9fadfc0e15c6459",
}
T0 = time.time()

def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)

def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def norm_text(s):
    return re.sub(r"\s+", " ", str(s).strip().casefold())

def uni_tokens(s):
    """Unicode-category tokenizer: letters/marks/numbers form tokens, so
    Devanagari words (with combining marks) stay whole."""
    toks, cur = set(), []
    for ch in str(s).casefold():
        if unicodedata.category(ch)[0] in "LMN":
            cur.append(ch)
        else:
            if cur:
                toks.add("".join(cur)); cur = []
    if cur:
        toks.add("".join(cur))
    return toks

def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0

def letterish_ratio(t):
    if not t:
        return 0.0
    return sum(1 for c in t if unicodedata.category(c)[0] in "LMN") / len(t)

def language_screen(text):
    """Heuristic screen only - returns a list of failed rules (empty = pass)."""
    fails = []
    if "�" in text:
        fails.append("replacement_char")
    if len(text) < 10:
        fails.append("too_short")
    if len(text) > 600:
        fails.append("too_long")
    if letterish_ratio(text) < 0.5:
        fails.append("low_letter_ratio")
    words = text.split()
    if words and Counter(words).most_common(1)[0][1] >= 6:
        fails.append("token_repetition")
    return fails

LEAK_PATTERNS = [
    ("correct_category_phrase", re.compile(r"(?:the\s+)?correct\s+(?:category|label|answer|sentiment)\b", re.I)),
    ("should_be_categorized", re.compile(r"should\s+be\s+(?:categorized|categorised|classified)\b", re.I)),
    ("categorized_as", re.compile(r"(?:categorized|categorised|classified)\s+as\b", re.I)),
    ("category_for_this_ticket_is", re.compile(r"category\s+for\s+this\s+(?:ticket|review|text)\s+is\b", re.I)),
    ("belongs_to_category", re.compile(r"belongs\s+to\s+the\s+category\b", re.I)),
    ("this_ticket_should_be", re.compile(r"this\s+(?:ticket|review|text)\s+should\s+be\b", re.I)),
    ("category_word_present", re.compile(r"\bcategor(?:y|ies|iz(?:e|ed|ing)|is(?:e|ed|ing))\b|\bclassif(?:y|ied|ication|ying)\b", re.I)),
]

def leakage_hits(text, labels):
    hits = [name for name, rx in LEAK_PATTERNS if rx.search(text)]
    from ekido_runtime.distill import _trailing_label, _residual_classification_text
    if _trailing_label(text, tuple(labels)):
        hits.append("standalone_label_sentence")
    if _residual_classification_text(text, tuple(labels)):
        hits.append("residual_classification_text")
    return hits

SELLER_RX = re.compile(r"seller|vendor|register|registration|बेच|विक्रेता|रजिस्टर|दुकान\s*(?:जोड़|खोल|बना|लग)|sell\s+on\b", re.I)

def overlap_report(rows_texts, ref_texts, ref_words):
    exact = 0; ge85 = 0; ge60 = 0; worst = 0.0
    ref_set = {norm_text(t) for t in ref_texts}
    for t in rows_texts:
        if norm_text(t) in ref_set:
            exact += 1
        w = uni_tokens(t)
        m = max((jaccard(w, rw) for rw in ref_words), default=0.0)
        worst = max(worst, m)
        if m >= 0.85: ge85 += 1
        if m >= 0.60: ge60 += 1
    return {"exact_matches": exact, "rows_with_near_dup_ge_0.85": ge85,
            "rows_with_near_dup_ge_0.60": ge60, "max_jaccard": round(worst, 3)}

def confusion_and_per_label(records, labels):
    cols = list(labels) + [""]
    matrix = {g: {c: 0 for c in cols} for g in labels}
    for gold, pred in records:
        matrix[gold][pred] += 1
    per = {}
    for lab in labels:
        tp = matrix[lab][lab]
        total = sum(matrix[lab].values())
        per[lab] = {"support": total, "correct": tp,
                    "accuracy": round(tp / total, 4) if total else None}
    return {"matrix_gold_rows_x_pred_cols": matrix, "per_label": per}

def main():
    log("RUN12 START - provenance first")
    provenance = {"workers_commit": WORKERS_COMMIT, "core_commit": CORE_COMMIT,
                  "code_sha256": {}, "data_sha256": {}}
    for rel, want in EXPECTED_SHA256.items():
        got = sha256_file(SRC / rel)
        provenance["code_sha256"][rel] = got
        if got != want:
            raise RuntimeError(f"CODE MISMATCH {rel}: got {got}, want {want} - refusing to run on unverified code")
    log("code provenance verified: PR #15 distill.py + core v0.4.2 hashes match")

    import torch
    from ekido_core.job_spec import MODEL_REVISIONS
    from ekido_core.recipes import recipe, passes, eval_set_hash, _first_label
    from ekido_runtime import distill, train as tm
    from ekido_runtime.llm import load_model, load_tokenizer, generate_answers
    r = recipe(RECIPE_ID)
    SRC_COL, TGT_COL = r.columns
    LABELS = list(r.labels)
    student_revision = MODEL_REVISIONS[STUDENT_ID]
    teacher_revision = distill.TEACHER_REVISION
    provenance["models"] = {"teacher": {"id": distill.TEACHER_MODEL, "revision": teacher_revision, "load": "4-bit"},
                            "student": {"id": STUDENT_ID, "revision": student_revision,
                                        "source": "pinned in ekido-core v0.4.2 job_spec.MODEL_REVISIONS"},
                            "judge": "none - no full-labelled-data judge used in this run (30-seed claim)"}
    log("GPU:", torch.cuda.get_device_name(0), "| recipe:", RECIPE_ID, "| floor:", r.floor)
    log("student revision (pinned):", student_revision)

    def read_csv(p):
        with open(p, encoding="utf-8") as f:
            return [{SRC_COL: row[SRC_COL], TGT_COL: row[TGT_COL]} for row in csv.DictReader(f)]
    train_rows = read_csv(DATA / "train.csv")
    test_rows = read_csv(DATA / "test.csv")
    provenance["data_sha256"] = {"train.csv": sha256_file(DATA / "train.csv"),
                                 "test.csv": sha256_file(DATA / "test.csv")}
    provenance["test_eval_set_hash"] = eval_set_hash(RECIPE_ID, test_rows)

    rng = random.Random(42)
    by_label = {lab: [row for row in train_rows if row[TGT_COL] == lab] for lab in LABELS}
    seeds, seed_idx = [], set()
    for lab in LABELS:
        for row in rng.sample(by_label[lab], 6):
            seeds.append(row); seed_idx.add(train_rows.index(row))
    non_seed = [row for i, row in enumerate(train_rows) if i not in seed_idx]
    val_rows = random.Random(123).sample(non_seed, 100)
    val_identity = {"rule": "Random(123).sample of 100 rows from the 470 non-seed train.csv rows (same validation set as run11/run11b)",
                    "train_csv_sha256": provenance["data_sha256"]["train.csv"],
                    "eval_set_hash": eval_set_hash(RECIPE_ID, val_rows),
                    "rows": val_rows}
    (OUT / "val_rows.json").write_text(json.dumps(val_identity, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"seeds 30 (6/label), validation 100 rows, val eval_set_hash {val_identity['eval_set_hash'][:12]}...")

    # ambiguity screen on the evaluation sets (labels untouched)
    flags = {"test": [], "validation": []}
    for name, rows in (("test", test_rows), ("validation", val_rows)):
        for i, row in enumerate(rows):
            if SELLER_RX.search(row[SRC_COL]):
                flags[name].append({"row_index": i, "label": row[TGT_COL], "text": row[SRC_COL]})
    (OUT / "ambiguity_flags.json").write_text(json.dumps(flags, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"ambiguity screen: test {len(flags['test'])} flagged ({Counter(f['label'] for f in flags['test'])}), "
        f"validation {len(flags['validation'])} flagged ({Counter(f['label'] for f in flags['validation'])})")

    # ---------- teacher: real-row accuracy + generation ----------
    t_tok = load_tokenizer(distill.TEACHER_MODEL, teacher_revision)
    teacher = load_model(distill.TEACHER_MODEL, teacher_revision, device=DEVICE, load_in_4bit=True)
    prompts = [r.prompt(row[SRC_COL]) for row in non_seed]
    answers = generate_answers(teacher, t_tok, prompts, max_new_tokens=r.max_answer_tokens,
                               max_prompt_tokens=508, device=DEVICE)
    per = {}
    for lab in LABELS:
        sel = [(a, row) for a, row in zip(answers, non_seed) if row[TGT_COL] == lab]
        per[lab] = round(sum(1 for a, row in sel if passes(RECIPE_ID, a, row[TGT_COL])) / len(sel), 4)
    teacher_real = {"overall": round(sum(1 for a, row in zip(answers, non_seed)
                                          if passes(RECIPE_ID, a, row[TGT_COL])) / len(non_seed), 4),
                    "per_label": per, "rows": len(non_seed)}
    log("teacher on 470 real non-seed rows:", teacher_real)

    fc_main = {"trailing_label_rows_dropped": 0, "answer_annotations_removed": 0,
               "classification_text_rows_dropped": 0}
    pool = distill.generate_rows(teacher, t_tok, RECIPE_ID, seeds, per_seed=20,
                                 device=DEVICE, filter_counts=fc_main)
    log(f"generation main (30 seeds x 20): {len(pool)} rows; filter counts {fc_main}")
    other_seeds = [s for s in seeds if s[TGT_COL] == "other"]
    fc_other = {"trailing_label_rows_dropped": 0, "answer_annotations_removed": 0,
                "classification_text_rows_dropped": 0}
    pool_other = distill.generate_rows(teacher, t_tok, RECIPE_ID, other_seeds, per_seed=30,
                                       device=DEVICE, filter_counts=fc_other)
    log(f"generation extra (6 'other' seeds x 30): {len(pool_other)} rows; filter counts {fc_other}")
    pool = pool + pool_other
    val_norm = {norm_text(x[SRC_COL]) for x in val_rows}
    test_norm = {norm_text(x[SRC_COL]) for x in test_rows}
    kept, dropped_eval_overlap = [], 0
    for row in pool:
        if norm_text(row[SRC_COL]) in val_norm or norm_text(row[SRC_COL]) in test_norm:
            dropped_eval_overlap += 1
        else:
            kept.append(row)
    pool = kept
    log(f"dropped {dropped_eval_overlap} generated rows matching validation/test inputs; pool now {len(pool)}")
    with open(OUT / "pool_raw.jsonl", "w", encoding="utf-8") as f:
        for row in pool:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---------- audit ----------
    audit = {"generation_filter_counts_main": fc_main, "generation_filter_counts_other_extra": fc_other,
             "generated_rows_matching_validation_or_test_inputs_dropped": dropped_eval_overlap,
             "teacher_on_real_rows": teacher_real,
             "judge": "none (see header: a full-labelled-data judge would break the 30-seed claim)"}
    annotated, removed = [], []
    leak_counter, screen_counter = Counter(), Counter()
    for row in pool:
        text = row[SRC_COL]
        hits = leakage_hits(text, LABELS)
        for h in hits:
            leak_counter[h] += 1
        fails = language_screen(text)
        for x in fails:
            screen_counter[x] += 1
        rec = {"text": text, "intended_label": row[TGT_COL], "leakage_hits": hits,
               "language_screen_fails": fails}
        if hits or fails:
            removed.append(rec)
        annotated.append(rec)
    audit["leakage_pattern_counts_in_pool"] = dict(leak_counter)
    audit["language_screen_fail_counts"] = dict(screen_counter)
    audit["rows_removed_by_leakage_or_screen"] = len(removed)
    seen_norm = {}
    exact_dupes = 0
    for a in annotated:
        k = norm_text(a["text"])
        if k in seen_norm:
            exact_dupes += 1
            a["exact_duplicate"] = True
        else:
            seen_norm[k] = a
            a["exact_duplicate"] = False
    audit["exact_duplicates_within_pool"] = exact_dupes
    words = [uni_tokens(a["text"]) for a in annotated]
    near_pairs = 0; near_flag = [False] * len(annotated)
    for i in range(len(annotated)):
        for j in range(i + 1, len(annotated)):
            if jaccard(words[i], words[j]) >= 0.85:
                near_pairs += 1
                near_flag[j] = True
    for a, f in zip(annotated, near_flag):
        a["near_duplicate_of_earlier_row"] = bool(f)
    audit["near_duplicate_pairs_jaccard_ge_0.85_within_pool"] = near_pairs
    audit["near_duplicate_rows_dropped"] = int(sum(near_flag))
    log(f"audit stage 1: leakage {dict(leak_counter)}, screen {dict(screen_counter)}, "
        f"exact dupes {exact_dupes}, near-dup pairs {near_pairs}")

    pool_prompts = [r.prompt(a["text"]) for a in annotated]
    self_answers = generate_answers(teacher, t_tok, pool_prompts, max_new_tokens=r.max_answer_tokens,
                                    max_prompt_tokens=508, device=DEVICE)
    for a, ans in zip(annotated, self_answers):
        a["teacher_self_label"] = _first_label(ans, tuple(LABELS))
    del teacher; torch.cuda.empty_cache()
    log("teacher self-classification done; teacher freed")

    def agree_stats():
        per_lab = {}
        for lab in LABELS:
            sel = [a for a in annotated if a["intended_label"] == lab]
            per_lab[lab] = round(sum(1 for a in sel if a["teacher_self_label"] == lab) / len(sel), 4) if sel else None
        overall = round(sum(1 for a in annotated if a["teacher_self_label"] == a["intended_label"]) / len(annotated), 4)
        return {"overall": overall, "per_label": per_lab}
    audit["teacher_self_agreement"] = agree_stats()
    for a in annotated:
        a["clean"] = (not a["leakage_hits"] and not a["language_screen_fails"]
                      and not a["exact_duplicate"] and not a["near_duplicate_of_earlier_row"])
        a["in_verified"] = bool(a["clean"] and a["teacher_self_label"] == a["intended_label"])
    def counts(rows):
        return dict(Counter(x["intended_label"] for x in rows))
    audit["pool_rows"] = len(annotated)
    audit["pool_per_label"] = counts(annotated)
    audit["clean_rows"] = sum(1 for a in annotated if a["clean"])
    audit["clean_per_label"] = counts([a for a in annotated if a["clean"]])
    audit["verified_rows"] = sum(1 for a in annotated if a["in_verified"])
    audit["verified_per_label"] = counts([a for a in annotated if a["in_verified"]])
    seed_words = [uni_tokens(x[SRC_COL]) for x in seeds]
    val_words = [uni_tokens(x[SRC_COL]) for x in val_rows]
    test_words = [uni_tokens(x[SRC_COL]) for x in test_rows]
    pool_texts = [a["text"] for a in annotated]
    audit["overlap_vs_seeds"] = overlap_report(pool_texts, [x[SRC_COL] for x in seeds], seed_words)
    audit["overlap_vs_validation"] = overlap_report(pool_texts, [x[SRC_COL] for x in val_rows], val_words)
    audit["overlap_vs_test"] = overlap_report(pool_texts, [x[SRC_COL] for x in test_rows], test_words)
    with open(OUT / "pool_annotated.jsonl", "w", encoding="utf-8") as f:
        for a in annotated:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    with open(OUT / "removed_rows.jsonl", "w", encoding="utf-8") as f:
        for a in removed:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    (OUT / "audit12.json").write_text(json.dumps(audit, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"audit done: clean {audit['clean_rows']} {audit['clean_per_label']}; verified {audit['verified_rows']} {audit['verified_per_label']}")
    log("AUDIT SAVED - pool_annotated.jsonl + audit12.json + removed_rows.jsonl")

    # ---------- training arms (validation-selected) ----------
    EXEC = {"micro_batch": 2, "accumulation": 4, "amp": "fp16", "grad_checkpointing": True,
            "attention_impl": "sdpa", "loader_workers": 0}
    STEPS, SEG = 400, 80
    arms = {}
    base_val_rate = None
    for arm_name, flag in (("verified", "in_verified"), ("clean", "clean")):
        rows = [{SRC_COL: a["text"], TGT_COL: a["intended_label"]} for a in annotated if a[flag]]
        with open(OUT / f"student_dataset_{arm_name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        blob = OUT / f"dataset_{arm_name}.jsonl"
        digest, nbytes = tm.write_dataset(blob, rows, val_rows)
        spec = distill.build_student_spec(RECIPE_ID, student_model=STUDENT_ID,
                                          student_revision=student_revision, digest=digest,
                                          nbytes=nbytes, train_rows=len(rows),
                                          test_rows=len(val_rows), steps=STEPS)
        spec["optimizer"]["lr"] = 3e-4
        spec["checkpoint_every_steps"] = SEG
        arm_out = OUT / f"train_{arm_name}"
        curve = {}
        prev = None
        for seg_i in range(STEPS // SEG):
            ev = tm.run_training(spec, blob, arm_out, device=DEVICE, exec_config=EXEC,
                                 eval_before=(seg_i == 0), stop_after=SEG, resume=prev)
            curve[ev["completed_step"]] = ev["eval"]["pass_rate"]
            prev = Path(ev["checkpoints"][-1])
            if seg_i == 0 and ev.get("base_eval"):
                if base_val_rate is None:
                    base_val_rate = ev["base_eval"]["pass_rate"]
                log(f"base student on validation: {ev['base_eval']['pass_rate']}")
            log(f"arm {arm_name}: step {ev['completed_step']} validation {ev['eval']['pass_rate']}")
        arms[arm_name] = {"rows": len(rows), "spec": spec, "validation_curve": curve}
        log(f"ARM {arm_name} DONE: {curve}")

    best = None
    for arm_name in ("verified", "clean"):
        for step, rate in arms[arm_name]["validation_curve"].items():
            cand = (rate, arm_name == "verified", -step, arm_name, step)
            if best is None or cand > best[0]:
                best = (cand, arm_name, step)
    _, best_arm, best_step = best
    best_rate = arms[best_arm]["validation_curve"][best_step]
    best_ckpt = OUT / f"train_{best_arm}" / "checkpoints" / f"step-{best_step}"
    log(f"SELECTED (validation only): arm {best_arm} step {best_step} @ {best_rate}")

    # ---------- detailed evaluation ----------
    def detailed_eval(model, tok, rows):
        prompts = [r.prompt(row[SRC_COL]) for row in rows]
        answers = generate_answers(model, tok, prompts, max_new_tokens=r.max_answer_tokens,
                                   max_prompt_tokens=508, device=DEVICE)
        records, pairs = [], []
        for row, ans in zip(rows, answers):
            pred = _first_label(ans, tuple(LABELS))
            records.append({"text": row[SRC_COL], "gold": row[TGT_COL], "answer": ans,
                            "predicted_label": pred,
                            "passed": passes(RECIPE_ID, ans, row[TGT_COL])})
            pairs.append((row[TGT_COL], pred))
        rate = round(sum(1 for x in records if x["passed"]) / len(records), 4)
        return rate, records, confusion_and_per_label(pairs, LABELS)

    s_tok = load_tokenizer(STUDENT_ID, student_revision)
    base_model = load_model(STUDENT_ID, student_revision, device=DEVICE, dtype=torch.float16)
    base_val = detailed_eval(base_model, s_tok, val_rows)
    base_test = detailed_eval(base_model, s_tok, test_rows)
    del base_model; torch.cuda.empty_cache()
    log(f"base detailed: validation {base_val[0]}, historical test {base_test[0]}")

    from safetensors.torch import load_file as _lf
    t_base = load_model(STUDENT_ID, student_revision, device=DEVICE, dtype=torch.float16)
    trained = tm.apply_lora(t_base, arms[best_arm]["spec"])
    state = _lf(str(best_ckpt / "trainable.safetensors"))
    missing, unexpected = trained.load_state_dict(state, strict=False)
    lora_missing = [k for k in missing if "lora_" in k]
    if lora_missing or unexpected:
        raise RuntimeError(f"best checkpoint load problem: missing lora {len(lora_missing)}, unexpected {len(unexpected)}")
    trained.eval()
    best_val = detailed_eval(trained, s_tok, val_rows)
    best_test = detailed_eval(trained, s_tok, test_rows)
    log(f"best detailed: validation {best_val[0]}, historical test {best_test[0]}")
    with open(OUT / "per_example_validation.jsonl", "w", encoding="utf-8") as f:
        for b, t in zip(base_val[1], best_val[1]):
            f.write(json.dumps({"text": b["text"], "gold": b["gold"],
                                "base_answer": b["answer"], "base_predicted": b["predicted_label"], "base_passed": b["passed"],
                                "trained_answer": t["answer"], "trained_predicted": t["predicted_label"], "trained_passed": t["passed"]},
                               ensure_ascii=False) + "\n")
    with open(OUT / "per_example_test_historical.jsonl", "w", encoding="utf-8") as f:
        for b, t in zip(base_test[1], best_test[1]):
            f.write(json.dumps({"text": b["text"], "gold": b["gold"],
                                "base_answer": b["answer"], "base_predicted": b["predicted_label"], "base_passed": b["passed"],
                                "trained_answer": t["answer"], "trained_predicted": t["predicted_label"], "trained_passed": t["passed"]},
                               ensure_ascii=False) + "\n")

    flagged_idx = [f["row_index"] for f in flags["test"]]
    flagged_eval = None
    if flagged_idx:
        sub = [best_test[1][i] for i in flagged_idx]
        flagged_eval = {"rows": len(sub),
                        "note": "Seller-registration style test rows flagged by a text screen. Labels are the ORIGINAL dataset labels, unchanged. Reported separately for transparency; the headline scores use all 100 rows with original labels.",
                        "base_pass_rate_on_flagged": round(sum(1 for i in flagged_idx if base_test[1][i]["passed"]) / len(sub), 4),
                        "trained_pass_rate_on_flagged": round(sum(1 for x in sub if x["passed"]) / len(sub), 4),
                        "trained_predictions": [{"gold": x["gold"], "predicted": x["predicted_label"], "text": x["text"]} for x in sub]}
        log(f"flagged test rows: {flagged_eval['rows']}, trained pass rate on them {flagged_eval['trained_pass_rate_on_flagged']}")

    shutil.copytree(best_ckpt, OUT / "best_checkpoint")
    summary = {
        "run": "run12", "recipe_id": RECIPE_ID, "floor": r.floor,
        "provenance": provenance,
        "settings": {"seeds": 30, "per_seed_main": 20, "per_seed_other_extra": 30,
                     "generation_budget_note": "the six 'other' seeds received 50 total generations vs 20 for other labels, to counter the verified collapse of the 'other' class; still only 30 labelled seeds",
                     "generation": "distill.generate_rows @ workers PR #15 commit (temperature 0.8, top_p 0.95, max_new_tokens 96, attempts 3)",
                     "label_verification": "teacher self-consistency only; no full-labelled-data judge (30-seed claim)",
                     "arms": {k: {"rows": v["rows"], "validation_curve": v["validation_curve"]} for k, v in arms.items()},
                     "spec_overrides": "build_student_spec with optimizer.lr=3e-4, checkpoint_every_steps=80, total steps 400, segments of 80 via stop_after/resume",
                     "exec_config": EXEC, "selection_rule": "highest validation pass rate; ties -> verified arm, then earlier step"},
        "audit_file": "audit12.json",
        "ambiguity_flags_file": "ambiguity_flags.json",
        "base_student_validation": base_val_rate,
        "selection": {"arm": best_arm, "step": best_step, "validation_pass_rate": best_rate,
                      "checkpoint": str(best_ckpt)},
        "validation_detailed": {
            "base": {"pass_rate": base_val[0], **base_val[2]},
            "best_trained": {"pass_rate": best_val[0], **best_val[2]}},
        "historical_test_comparison": {
            "note": "The recipe test.csv was used repeatedly in this experiment series (v4-v12), including checkpoint selection in early runs. These numbers are a historical comparison only, NOT an untouched independent test. No new approved held-out set exists; independent verification is pending.",
            "base": {"pass_rate": base_test[0], **base_test[2]},
            "best_trained": {"pass_rate": best_test[0], **best_test[2]}},
        "flagged_ambiguous_test_rows": flagged_eval,
        "floor_verdict": {
            "on_validation": {"score": best_val[0], "floor": r.floor, "meets_floor": bool(best_val[0] >= r.floor)},
            "on_historical_test": {"score": best_test[0], "floor": r.floor, "meets_floor": bool(best_test[0] >= r.floor)}},
    }
    (OUT / "SUMMARY12.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    log("SUMMARY12:", json.dumps(summary["floor_verdict"], ensure_ascii=False))
    log("RUN12_DONE")

if __name__ == "__main__":
    def _beat():
        while True:
            time.sleep(240); log("heartbeat - run12 alive")
    threading.Thread(target=_beat, daemon=True).start()
    try:
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "torchao"],
                       capture_output=True, timeout=300)
        log("torchao removed (or was absent)")
    except Exception as e:
        log("torchao uninstall note:", e)
    try:
        import bitsandbytes  # noqa: F401
        log("bitsandbytes present")
    except Exception:
        log("bitsandbytes missing - installing")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "bitsandbytes"], timeout=900)
    main()
