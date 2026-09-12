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
