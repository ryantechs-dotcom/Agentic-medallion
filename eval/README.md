# eval/

- `questions_template.csv` - schema with six EXAMPLE rows (one per question type and source).
- `questions.csv` - the real evaluation set. **Frozen v1, 2026-11-02: 132 questions, 77 dev /
  55 test** (sha256 and history in `docs/DECISIONS.md` D11). Copied once from the reviewed
  draft at Ryan's decision; never generated or overwritten by a script.
- `qa_eval.jsonl` - the same frozen set in the tracker's question / answer / source format.
- `generated_overrides.csv` - reviewed fixes to generated lookups (question, field, value),
  applied by the draft script.
- `independent_review2_2026-11-02.md` - second review (67 new or reworded rows).

## Draft workflow (P1, tracker task #11)
- `handwritten_draft.csv` - hand-written multihop / conflict / unanswerable questions (input),
  with `expect` (substring the SQL result must contain) and `check_terms` (unanswerable rows:
  `;`-separated terms that must NOT appear in the corpus; `mimic/term` limits to one folder).
- `python scripts/draft_eval_questions.py` adds seeded lookup questions generated from the
  codebooks/docs, runs every check, and writes:
  - `questions_draft.csv` (template schema, `author = Claude (draft)`)
  - `qa_eval_draft.jsonl` (question/answer/source format named in the tracker)
  - `review_draft.md` (doc excerpt + SQL result per question; failed checks listed first)
- Review in `review_draft.md`, edit, fill `reviewed_by`, and save the kept rows as
  `questions.csv`. The dev/test split in the draft is a proposal: freeze it before any results.
- `independent_review_2026-11-01.md` - independent Claude review of the first 122-question
  draft (qids there refer to that version). Its recommendations were accepted and applied: see
  `docs/DECISIONS.md` D11 "Revision".
- Tag columns (`subtype`, `gold_evidence`, `needs_data`, `guessable`, `cluster`) are defined in
  `docs/PROBLEM1_PLAN.md` "Evaluation set".

Column definitions, question types (lookup / multihop / conflict / unanswerable) and the
~60/40 dev/test split rule are in `docs/PROBLEM1_PLAN.md` ("Evaluation set").
Integrity rules are in `eval/CLAUDE.md`.

This folder is synced to Google Drive by `scripts/sync_drive.py` (see README "Syncing").
