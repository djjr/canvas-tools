# Implementation notes

Version 1 implemented September 12, 2026. Flask + SQLite, vanilla JavaScript/CSS. Canvas writes are available only through explicit review and confirmation. No live write was performed during development.

## Verified API behavior and sources

- [Quiz Submissions](https://developerdocs.instructure.com/services/canvas/resources/quiz_submissions): `GET /api/v1/courses/:course_id/quizzes/:quiz_id/submissions`, with `include[]=user` and `include[]=submission`. Quiz submission ID differs from assignment submission ID. Returned records carry attempt numbers; Canvas may return only an in-progress submission or multiple completed attempts.
- [Quiz Questions](https://developerdocs.instructure.com/services/canvas/resources/quiz_questions): `GET /api/v1/courses/:course_id/quizzes/:quiz_id/questions` supports paired `quiz_submission_id` and `quiz_submission_attempt`, used here to obtain the question version for the exact attempt.
- [Quiz Submission Questions](https://developerdocs.instructure.com/services/canvas/resources/quiz_submission_questions): `GET /api/v1/quiz_submissions/:quiz_submission_id/questions`, with `include[]=quiz_question`.
- [Official controller source](https://github.com/instructure/canvas-lms/blob/master/app/controllers/quizzes/quiz_submission_questions_controller.rb): the GET handler supports `quiz_submission_attempt`, although the documentation's parameter table omits it.
- [Official serialization source](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/quiz_submission_question.rb): completed submissions may omit the submitted answer in this endpoint. Do not interpret an omitted field as an empty student answer.
- [Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions): assignment submission list supports `include[]=user` and `include[]=submission_history`. This supplies roster status and, when returned, attempt-matched `submission_data`. The app uses `question_id`, `text`, `points`, and `more_comments` from that data when present; those fields must be validated against institutional responses before relying on complete coverage.

Every list follows Link-header pagination, including quiz submissions, assignment submissions, attempt questions, and submitted questions. Redirects are rejected, and all requests stay at the configured HTTPS origin under `/api/v1/`.

## Storage and UI

Snapshots contain normalized records, not full API responses. Draft identity includes Canvas origin, course, quiz, quiz submission, user, attempt, and question IDs. A content fingerprint detects changes in question metadata, response, and existing Canvas grading. Conflict drafts are preserved and frozen pending a future review workflow.

Canvas HTML uses a formatting-only allowlist; scripts, event attributes, remote images, embedded content, and links are removed. Student names and ordinary text use template escaping. Browser mutations are same-session CSRF protected; localhost Host validation, CSP, and no-store headers are applied. Autosave serializes requests per response and warns before navigating away with unsaved changes.

## Next session

Connect to one instructor-owned Classic Quiz locally and validate answer and attempt coverage. Inspect credential-redacted schema summaries only, not raw student data in logs. Then consider conflict resolution, faster loading, draft backup/export, and grading workflow refinements. Publishing remains a separate phase requiring endpoint/payload review and explicit user authorization.


## Grading-status validation

Verified official `Quizzes::QuizSubmission.update_scores` source: clearing a question score sets points to zero and correct to "undefined"; assigning a score changes "undefined" to "defined". Source: https://github.com/instructure/canvas-lms/blob/master/app/models/quizzes/quiz_submission.rb . JHU quiz read-only aggregate inspection confirmed two `undefined` zero records and one boolean-false zero record. No student names or answers were output. Classifier and UI default tests cover graded zeros, ungraded zeros, missing/null/unknown/conflicting markers, and saved-draft precedence. No Canvas writes were made.


## Explicit publishing phase

Added a separate Publisher service, persistent review/result journals, and server-enforced demo/Safe Mode blocks. Verified the official Quiz Submissions manual-grading API: PUT /api/v1/courses/:course_id/quizzes/:quiz_id/submissions/:id uses the QuizSubmission id (not its assignment submission_id), an explicit completed attempt, and questions keyed by question id with score/comment values. Requires instructor grading permission. No fudge points or submission-wide comment endpoints are used. Reference: https://developerdocs.instructure.com/services/canvas/resources/quiz_submissions . Payload, conflict handling, replay rejection, uncertainty, and mode guards are tested with mocked writes. No live writes were performed. New authorization from the user explicitly enables implementing this phase; original handoff's version-1 write prohibition no longer describes the current feature set.


## Verification performance

Live use showed publishing even a few items could take a minute or more. Cause: `Publisher.preview()`/`run()`/`reconcile()` verified each item by calling `CanvasClient.load()`, a full quiz reload (every submission, the full roster with submission history, two more calls per student) — repeated once per item in `run()`'s post-write check, plus once more up front in each of `preview()` and `run()`. Cost scaled with class size regardless of how many items were actually being graded, and none of the callers ever used more than one identity's worth of the result.

Replaced with `CanvasClient.load_submission(course, quiz, assignment, submission, attempt, user_id)`, scoped to one submission (2-3 calls, independent of class size):
- New endpoint verified: [Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions) `GET /api/v1/courses/:course_id/assignments/:assignment_id/submissions/:user_id` with `include[]=user,submission_history`. Confirmed against the official Submissions resource docs and `SubmissionsApiController#show` source: it renders a bare submission object via the same `submission_json` serializer as the index action already in use, so field shapes (`excused`, `submission_history`, `user`) match what `load()` already consumed from the roster list.
- The existing per-submission `Quiz Questions` and `Quiz Submission Questions` calls are reused as-is; they were already scoped to one submission and were never the bottleneck.
- Deliberately not refetched: the quiz submission's own `workflow_state` (there is a documented `GET .../quizzes/:quiz_id/submissions/:id` show endpoint, but it takes an optional `attempt` param whose effect on the serialized `attempt`/`workflow_state` fields for a non-latest attempt is not confirmed in the docs or controller source, so it was not relied on). A manual grade write only ever moves that value between `pending_review` and `complete`, both already treated as editable, and the one transition that would matter — the submission becoming excused or its answer disappearing — is independently caught by the freshly-refetched `excused` flag and `available` flag. Recorded here as a scope decision, not an oversight; revisit if verification needs to catch a broader class of concurrent Canvas-side edits than it does today.

Publisher tests assert `CanvasClient.load` is never called during preview/run/reconcile, and a dedicated test pins `load_submission` to exactly its three expected endpoint calls, to keep the full-reload behavior from silently coming back.


## Shared core for grading modes

September 30, 2026, on the `assignments` branch. The quiz grader was split into a shared core (`canvas_core`, `publishing_core`, `storage`, `web_core`, `app`) and a quiz mode (`quiz`, `canvas_api`, `publishing`, `quiz_routes`), in preparation for assignment grading (`ASSIGNMENTS_DESIGN.md`).

No user-visible change was intended, and this was verified against a copy of the real local database (6 quiz workspaces, 419 responses, 203 drafts, 16 upload journals). Every stored workspace key, record key, and fingerprint recomputes identically. All 41 grading, activity, and upload review pages render byte-identical HTML to `main`, apart from per-session CSRF tokens. The copy was deleted afterward, and no student data was output.

Two publishing fixes were made during the split:
- `load_submission` now raises if the per-student roster lookup fails, instead of continuing without the `excused` flag that verification relies on. Before a write this blocks the item; after a write, the item stays uncertain.
- `preview()` and `reconcile()` handle Canvas errors per item. One unreachable student blocks only that item instead of aborting the whole review or reconciliation.

Upload batches now record `kind`. Batches saved earlier have none and are treated as quiz batches.
