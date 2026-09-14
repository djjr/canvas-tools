# Margin: LLM coding handoff

The app lives in `quiz-grader/` within `djjr/canvas-tools`. Run commands from
this directory. In the original local checkout at
`/Users/danryan/Documents/GitHub/canvas-quiz-grader/quiz-grader`, the existing
virtual environment remains one directory above: use `../.venv/bin/python`.
New checkouts can create `.venv` inside `quiz-grader/` as the README describes.
Credentials, saved student data, and distribution ZIPs are local ignored files
under this app directory; the repository root contains the tools index README.

## Product

Margin is a single-user localhost Flask app for grading Canvas Classic Quiz essay responses question by question. Canvas is the source of truth. SQLite stores snapshots, drafts, comment-board entries, audit events, and upload journals.

## Current behavior

The app loads a Classic Quiz URL or course/quiz IDs, retrieves paginated submissions and attempt-specific questions, and supplements missing answers with assignment submission history. Only `essay_question` records are displayed. HTML is sanitized with an allowlist. Students sort alphabetically, then by attempt. The question prompt/upload controls are sticky above a scrollable response pane.

Scores default to a confirmed Canvas score, otherwise points possible for an ungraded question. Scores allow decimals and up to one extra point. Existing Canvas Additional Comments prefill the feedback box. Quiz-wide comments are never touched.

Draft readiness is separate from saving: Not Graded, Already Graded, Status Unknown, and Newly Graded. Newly Graded means explicitly ready for upload. Toggling it off preserves score/comment and only clears readiness. Editing clears readiness. Comment boards are per site/course/quiz/question with nine stable slots.

## Upload contract

`Publisher.preview()` includes only reviewed, non-stale drafts and rechecks Canvas. `Publisher.run()` performs one PUT per question using `/api/v1/courses/:course_id/quizzes/:quiz_id/submissions/:submission_id`, with `attempt` and `questions[question_id] = {score, comment}`. Empty comment leaves Canvas Additional Comments unchanged. Submission-wide comments and fudge points are excluded. Each write is journaled before network I/O and read back afterward. Success clears readiness; blocked/uncertain items remain. Uncertain writes are never automatically retried; reconcile is read-only.

Rechecking Canvas (before and after each write) goes through `Publisher.refresh()` → `CanvasClient.load_submission()`, which fetches only the one submission being verified. Do not change this back to `CanvasClient.load()` (a full quiz reload) for a lookup — that was the original implementation and made publishing a handful of items take minutes on a real class, since it re-fetched every other student to check one identity. See `PROJECT.md`'s "Verification performance" entry for what was verified and what was deliberately left unrefetched (quiz-submission `workflow_state`).

Demo workspaces and Safe Mode (`?safe=1` or `CANVAS_SAFE_MODE=1`) reject preview/confirm server-side. A browser timer keeps the upload button visibly active; uploads are currently synchronous. One reviewed snapshot is reused for preflight; post-write verification refreshes Canvas.

## Data and safety invariants

Never log tokens, headers, CSRF values, raw Canvas errors, or credentials. Refuse unsafe origins, redirects, and non-API pagination URLs. Draft identity includes origin, course, quiz, submission, user, attempt, and question. Fingerprints cover question, answer, existing score/comment, and grading status. Audit rows are append-only via SQLite triggers. All POSTs require same-session CSRF.

## Tests and commands

Run `.venv/bin/python -m pytest -q` (currently 36 passing tests) and `.venv/bin/python -m compileall -q app.py canvas_api.py publishing.py storage.py`. Start with `.venv/bin/python app.py` on port 5050.

## Known gaps / next work

Implement an actual background upload job with persisted per-item progress and polling (the current browser timer is cosmetic). Add explicit stale-draft resolution (“keep my draft” / “use Canvas values”), historical attempt selection, non-essay types, and export/backup UX. Test further live updates on a disposable quiz before wider use.

Do not remove Safe Mode, conflict checks, uncertainty handling, audit journaling, or the distinction between saving a draft and marking it Newly Graded.
