# Canvas Classic Quiz Grader — Project Handoff

> **Historical:** the original September 2026 brief, kept for context. Its version-1 read-only rule no longer applies. For current state, read `LLM_DESIGN.md` (code, invariants, next work) and `PROJECT.md` (dated decisions and verified API behavior).

## Purpose

Build a small local web application that provides a faster, more comfortable interface for grading open-ended responses submitted through **Canvas LMS Classic Quizzes**.

Canvas remains the system of record. The application should retrieve quiz submissions and, in a later deliberately enabled phase, send per-question scores and feedback back to Canvas.

## User and grading workflow

The user is a university instructor who frequently grades short, open-ended pre-class responses. Canvas's standard grading interface is slower and less well matched to this workflow than a compact question-centered interface.

The preferred orientation is:

1. Select or paste the URL of a Classic Quiz.
2. Choose an open-ended question.
3. Scroll through every student's response to that question.
4. Enter a numeric score and short feedback directly beneath each response.
5. Save drafts locally and continuously.
6. Publish the staged scores and comments to Canvas only after an explicit review-and-confirm action.

Question-by-question grading is more important than reproducing SpeedGrader's student-by-student layout.

## Safety and credential constraints

- Never ask the user to paste a Canvas API token into chat.
- Read `CANVAS_BASE_URL` and `CANVAS_TOKEN` from a local `.env` file.
- Include `.env` in `.gitignore` and provide only `.env.example` in the project.
- Do not log, display, commit, or include the token in error reports.
- Begin in **read-only mode**. Version 1 must make no Canvas write requests.
- Later write-back must be a staged, explicit **Publish to Canvas** operation, not an automatic update on each keystroke.
- Before implementing write-back, verify the current Classic Quiz grading endpoint, payload shape, question identifiers, attempt handling, and permissions against the official Canvas API documentation.
- Support a dry-run preview showing exactly which submissions, scores, and comments would be changed.

## Proposed version 1

Build the smallest useful read-only prototype in Python. A lightweight Flask application is a good default because it allows a durable custom interface without imposing Streamlit's interaction model. A different choice is acceptable if there is a concrete advantage.

Version 1 should:

- Accept a Canvas Classic Quiz URL and extract the course and quiz IDs, while also allowing IDs to be entered manually.
- Retrieve all quiz submissions with student information.
- Retrieve each submission's questions, submitted answers, existing scores, and existing comments when Canvas returns them.
- Handle Canvas pagination on every list endpoint.
- Initially show only essay/free-response questions, while preserving enough metadata to support other manually graded types later.
- Present one selected question followed by all student responses in a clean scrolling view.
- Clearly distinguish the question prompt, student name, submitted answer, points possible, existing score, and existing feedback.
- Store draft scores and comments locally, preferably in SQLite. Drafts should survive browser refreshes and application restarts.
- Provide previous/next question navigation and a student-response completion indicator.
- Escape or sanitize Canvas-provided HTML safely while preserving reasonable formatting in prompts and answers.
- Make no Canvas write requests.

## Likely Classic Quiz API sequence

Treat these as starting points and confirm them against the current official Canvas documentation while implementing:

1. Retrieve submissions:

   `GET /api/v1/courses/:course_id/quizzes/:quiz_id/submissions`

   Request associated user information if supported.

2. For each `quiz_submission_id`, retrieve submitted questions:

   `GET /api/v1/quiz_submissions/:quiz_submission_id/questions`

   Request the associated quiz-question object if supported so the UI can show `question_name`, `question_text`, `question_type`, and points possible.

3. A later phase is expected to use the Classic Quiz manual-grading endpoint for per-question `score` and `comment`, approximately:

   `PUT /api/v1/courses/:course_id/quizzes/:quiz_id/submissions/:submission_id`

   Do not rely on this approximate description without confirming the exact current payload and whether `submission_id`, `quiz_submission_id`, question ID, and `attempt` have the meanings assumed here.

## Important cases to design for

- Multiple attempts: display the selected attempt explicitly and never silently grade the wrong one.
- Submitted, pending-review, missing, and excused students.
- Blank answers versus unanswered questions.
- Canvas pagination and partial API failures.
- Rate limits, timeouts, expired tokens, and permission errors with useful but credential-safe messages.
- Existing grades/comments: do not overwrite them invisibly.
- HTML in question text and student answers.
- Decimal scores.
- Quiz changes after drafts were saved: identify drafts using stable Canvas IDs and detect mismatches.

## Later features

After read-only retrieval and local drafts are verified:

- Dry-run change summary.
- Explicit write-back of per-question scores and comments.
- Confirmation before publishing and a result log for each attempted change.
- Safe retry of failed changes without duplicating successful ones.
- A comment palette with customizable reusable comments and keyboard shortcuts.
- Filters for ungraded, partially graded, missing, or flagged responses.
- Keyboard-first grading and automatic movement to the next response after saving.
- Optional local export/backup of grading drafts.

## Suggested project structure

```text
canvas-grader/
├── app.py
├── canvas_api.py
├── storage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── PROJECT.md
├── templates/
├── static/
├── tests/
└── instance/             # ignored local database and runtime data
```

The implementation may simplify this structure if the first prototype does not need every component.

## Recommended first task for the new Codex session

Read this handoff, inspect the empty/local project folder, and then:

1. Confirm the implementation plan and any assumptions that materially affect the UI or Canvas API behavior.
2. Verify the current official Canvas Classic Quiz read endpoints.
3. Scaffold the local Flask project with `.env.example`, `.gitignore`, and clear setup instructions.
4. Implement API pagination and read-only retrieval.
5. Build the question-centered scrolling interface using mock fixture data first.
6. Add tests that do not require a real Canvas token.
7. Explain how the user should create `.env` locally and run the app.

Do not implement or enable Canvas write-back in this first task.

## First-session prompt

Use this after opening the `canvas-grader` folder in the desktop app:

> Read `CANVAS_GRADER_HANDOFF.md` and build the version 1 read-only prototype described there. Use mock data for UI development and tests. Do not ask me to paste my Canvas token, do not make Canvas write requests, and do not enable grade publishing yet. Verify the current Classic Quiz read endpoints in the official Canvas API documentation before relying on them.

