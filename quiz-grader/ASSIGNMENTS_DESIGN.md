# Assignment grading mode: design

Status: agreed design, not yet implemented (September 30, 2026).

Margin gains a second grading mode for Canvas assignments submitted as online
text entry. It lives in the same app as the Classic Quiz grader: same server,
`.env`, SQLite database, audit log, Safe Mode, and launcher. Assignments are
graded **student by student**, not question by question.

## Scope for version 1

In scope:

- Assignments whose `submission_types` include `online_text_entry`.
- `grading_type` of `points` only.
- One score and one new submission comment per student.
- Hidden student names and random ordering while grading.
- Rubrics displayed read-only for reference, if the assignment has one.

Refused with a clear message when the assignment loads:

- Any grading type other than points.
- Anonymous or moderated grading.
- Group assignments not graded individually.

Shown read-only, and never written:

- **Resubmissions.** Any student whose current submission is attempt 2 or
  later shows **Resubmitted: grade in Canvas**. These are handled in Canvas.
- Submissions that are not text entry (file uploads and so on), which show
  **Not a text submission**.
- Excused, missing, and unsubmitted students, listed as in quiz mode.

Out of scope for now: rubric scoring, other grading types, annotations, and
selecting an earlier attempt.

## Screen

- **Sidebar:** the student list (instead of questions), with a status per
  student: Not Graded, Already Graded, Newly Graded, Late, Missing, Excused,
  Resubmitted, and Not a text submission. **Show only ungraded** filters this
  list.
- **Main area:** the sanitized submission body in a readable column, with a
  side-by-side grading panel (score, the new comment, the Newly Graded toggle,
  and a save status). The resizable divider runs vertically here.
- The student's existing comment thread appears read-only above the draft
  comment.
- The rubric, if any, sits in a collapsible read-only panel.
- Up/Down arrows move between students, as in quiz mode.
- There is one comment board per assignment (nine slots, the same
  shortcuts as quiz mode).

## Hidden names and ordering

- Students appear in a random order. The order is generated once per
  assignment workspace and stored, so reloading does not reshuffle it and
  navigation stays predictable.
- **Hide names** is on by default and remembered per assignment. When it is
  on, students appear as "Student 1…N" (their position in the random order).
  This covers the sidebar, the page header, and author names in the existing
  comment thread.
- Submission text is not altered, so students who sign their work are still
  identifiable. The UI should say so once.
- The upload review screen always shows real names, because confirming a write
  requires knowing who it goes to. The audit log records real identities, as
  it does now.

## Scores

- Decimal points, stepping by 0.25, from 0 to one point above
  `points_possible`, matching quiz mode.
- By default the field shows the current Canvas score if there is one;
  otherwise it is blank. Unlike quiz mode, it does not default to full
  points.

## Drafts and change detection

- A draft's identity is the Canvas origin, course, assignment, student ID, and
  attempt.
- Its fingerprint covers the submission body, submitted time, attempt, current
  score, `workflow_state`, and the IDs of the existing comments.
- If the fingerprint changes on reload (new text, a grade entered in Canvas, a
  resubmission), the draft is kept, frozen, and marked stale, exactly as in quiz
  mode. A resubmission additionally switches the student to the read-only
  **Resubmitted** state.
- Autosave, the Newly Graded toggle, and the rule that editing clears
  readiness all work as in quiz mode.

## Canvas API

All endpoints and parameters below must be checked against the official
documentation and controller source before implementation, and recorded in
`PROJECT.md` as was done for quizzes.

Reads:

- `GET /api/v1/courses/:course_id/assignments/:id`: `grading_type`,
  `points_possible`, `submission_types`, `anonymous_grading`,
  `moderated_grading`, `group_category_id`,
  `grade_group_students_individually`, `post_manually`, and `rubric`.
- `GET /api/v1/courses/:course_id/assignments/:id/submissions` with
  `include[]=user`, `include[]=submission_comments`, and
  `include[]=submission_history`, paginated.
- `GET /api/v1/courses/:course_id/assignments/:id/submissions/:user_id` with
  the same includes, to check a single student before and after a write.
- `GET /api/v1/users/self`, to recognize the instructor's own comments.

Write:

- `PUT /api/v1/courses/:course_id/assignments/:id/submissions/:user_id` with
  `submission[posted_grade]` (the score) and, if the draft comment is not
  empty, `comment[text_comment]`.

## Publishing

This reuses the existing review → confirm → journal → read-back flow, Safe
Mode, and demo lock. Differences from quiz mode:

- **Comments append.** Re-sending a comment gives the student a duplicate.
  After a write, verification requires the expected score *and* a comment
  written by the instructor, with the exact draft text, that was not in the
  thread before the write. An uncertain result is never retried automatically;
  reconciliation looks for that comment without writing.
- **Grade posting policy.** If `post_manually` is false, Canvas shows grades
  to students as soon as they are written. The review screen says so plainly
  before confirmation.
- **Before each write,** the check refetches the student's submission. It
  blocks the write if the attempt, body, score, or comments changed since
  review.

## Build order

1. **Done (September 30, 2026). Refactor, with no change in behavior.** Separate the shared core (the
   Canvas connection and its origin and pagination checks, the audit log,
   upload journals, Safe Mode, sanitization, CSRF, and comment boards) from
   the quiz-specific code. Quiz routes become one module (a Flask blueprint).
   All existing tests stay green. Along the way, fix the known gaps:
   `load_submission` swallowing roster errors, and `preview()` aborting the
   whole review on one item's error.
2. **Read-only viewer.** Load an assignment, list its students with their
   statuses, show submission bodies, and apply hidden names and random order.
   Add a synthetic demo assignment.
3. **Local drafts.** Score, comment, readiness, autosave, the comment board,
   and change detection.
4. **Publishing.** Verify the write endpoint against official sources, then
   implement it with mocked-write tests before any live test on a disposable
   assignment.
