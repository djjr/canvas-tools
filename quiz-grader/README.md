# Margin — Canvas Classic Quiz Grader

A local Flask app for reading essay responses question by question and saving grading drafts in SQLite. Canvas retrieval uses GET requests. An explicit review-and-confirm flow can publish Newly Graded items. Demo data and Safe Mode cannot publish.

## Run

To prepare a source-only ZIP for colleagues, double-click `make-share-zip.bat`
on Windows with Python 3 installed. On macOS or Linux, run
`python3 make_share_zip.py`. The ZIP appears in `dist/`.
These packaging tools are available in the development checkout and are not
included in the sharing ZIP.
The packager includes only explicitly listed source, test, and documentation
files and generates a fresh placeholder `.env.example` with Safe Mode enabled.
It excludes `.env`, `instance/` (student data and audit history), Git history,
virtual environments, caches, exports, and backups. If you add source files,
update `FILES` in the packager. Source and documentation are included as-is;
do not put private data or credentials in those files.

Python 3.12 or newer is recommended. Dependencies and a virtual environment are already installed in this checkout.

```sh
cd canvas-tools/quiz-grader
.venv/bin/python app.py
```

Open http://127.0.0.1:5050 and choose **Explore the demo**. No credentials are required for the demo.

For a fresh checkout:

```sh
cd canvas-tools/quiz-grader
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python app.py
```

Alternatively use `uv venv --python 3.12` and `uv pip install --python .venv/bin/python -r requirements-dev.txt`.

## Connect Canvas

1. Copy `.env.example` to `.env` locally.
2. Open `.env` in your editor. Set `CANVAS_BASE_URL` to your school's HTTPS Canvas origin and enter your token as `CANVAS_TOKEN`. Never paste the token into chat.
3. Restart the app after changing `.env`.
4. Paste a Classic Quiz URL, or enter course and quiz IDs, then choose **Load from Canvas**.

Use an instructor account with permission to view grades in the course. The app keeps the token on the server, refuses redirects and pagination to other origins, and never includes Canvas response bodies or connection exceptions in displayed errors. `.env`, the virtual environment, and `instance/` are ignored by Git.

## Grade locally

Select a question in the sidebar. Each returned attempt is a separate, labeled student card. Read the answer, check any existing Canvas score and feedback, then enter a draft score and comment. Changes autosave after a brief pause; **Save draft** also saves immediately. Wait for **Saved locally** before leaving. The completion count measures locally scored responses, not grades published to Canvas.

New draft score fields use points possible only for a confirmed ungraded question. Otherwise they retain the returned Canvas score, including zero, or stay blank if no score is available; this default is saved only when you edit the draft or click Save draft. Existing drafts retain their saved scores, including a cleared score. The incrementer moves in 0.25-point steps. Scores can include decimals and must be between zero and one point above that attempt's points possible. The displayed denominator remains the original points possible. Clearing a draft score leaves the response incomplete. Blank submitted answers, unanswered questions, and unavailable answers have different labels. Unavailable, in-progress, and excused responses cannot be edited.

Bookmark a quiz workspace URL to reopen its saved snapshot after restarting. Loading the same quiz refreshes its snapshot while retaining drafts. If question content, an answer, or Canvas grading changed, the old draft remains visible and editing pauses rather than silently attaching it to changed data. This prototype does not yet offer an in-app conflict resolution flow.

All student data and drafts are stored locally in `instance/grader.sqlite`. Back up this file while the app is stopped. This is a single-user localhost app, not a shared or publicly hosted service. The local database is not encrypted.

## Validation

```sh
.venv/bin/python -m pytest -q
```

Tests use synthetic data only. They cover persistence, decimal validation, CSRF, stale drafts, attempt isolation, sanitization, pagination, origin protection, partial retrieval, and matching answer history. The demo was also checked in the browser for layout, saving, and refresh persistence.

## Current limits

- Classic Quiz `essay_question` only; New Quizzes and other question types are outside version 1.
- Canvas may omit answers or per-question grades/comments. The UI says **Not returned** or **Answer unavailable** rather than inventing values. Real institutional Canvas behavior still needs verification with your credentials.
- The submission question endpoint's attempt parameter is confirmed in official Canvas source, but is not described in its public parameter table. See `PROJECT.md`.
- Roster coverage depends on the quiz's assignment. A quiz without an assignment cannot list students with no quiz submission.
- Large classes load synchronously with per-request timeouts. Partial per-student failures are listed; loading the quiz again retries retrieval.
- No automated grading, historical-attempt selector, export UI, or draft conflict resolution yet. All attempts returned by Canvas are shown with labels.

## Question-specific comment board

Use **Save feedback to board** beneath a response to keep its feedback as a reusable comment. Each Canvas site/course/quiz/question has its own nine numbered slots, persisted in SQLite. Changing questions changes boards. Duplicate text is skipped; new comments fill the first empty slot without moving existing shortcuts. Edit or remove a slot when the board is full.

Focus a student's feedback field, then click a board comment or press **Control + Shift + 1–9** (Control, not Command, on Mac). The text replaces any selected text or inserts at the cursor, and ordinary draft autosave follows. Edit and Remove affect only the board, not feedback already inserted into student drafts. On narrow windows the board appears below the responses.


Grading status is determined per question and exact attempt: `correct: "undefined"` means ungraded; boolean `correct` or `"defined"` means graded. Missing, unrecognized, or conflicting markers mean unknown, with an explicit UI label. The quiz-wide pending-review state is not used to classify individual questions. Old cached workspaces lack this metadata: load the quiz again from Canvas. Existing local drafts retain precedence; changed grading status participates in draft conflict detection.

## Grading status and readiness

The score toggle shows **Not Graded** for confirmed ungraded Canvas responses, **Already Graded** for existing Canvas grades, and **Status Unknown** when evidence is missing. Clicking it marks your draft **✓ Newly Graded**, meaning ready for a future upload. Newly graded scores are bold and green with a green card border.

Toggling off preserves the score and comments exactly and returns to the underlying Canvas status. It only clears upload readiness. Editing score or feedback also clears readiness. Autosave and Save draft preserve work without confirming it. The completion count counts newly graded responses only. Existing drafts start unconfirmed. Wait for **Saved locally · ready for upload** before leaving. Publishing selects only confirmed, non-stale drafts after explicit review and confirmation.


## Upload grades

1. Finish a response and toggle it to **Newly Graded**. Wait until saved.
2. Click **Send newly graded items to Canvas**. This reviews confirmed items across all questions in the current quiz.
3. Review student, question, attempt, old/new score, and Additional Comments. Nonempty draft feedback replaces that question’s Additional Comments; empty feedback leaves Canvas’s comment unchanged. Clearing a Canvas comment is not supported. Submission-wide comments are never written.
4. Click **Confirm and send N items to Canvas**. Canvas data is checked again before each individual update. Changed or unavailable items are blocked.
5. Inspect results. Verified successes become Already Graded. Other drafts remain saved. Create a new review to retry blocked items after resolving their cause. Successful items are excluded automatically.

If a request times out or verification fails, its outcome is **uncertain** and another write for that item is blocked. Use **Check uncertain results (read-only)** to verify without resending. If verification still fails, inspect Canvas and resolve the discrepancy before proceeding; the app deliberately does not automatically retry ambiguous requests. Upload journals persist in SQLite and are linked from the grading page. A process interruption may leave a journal marked running; its uncertain items can still be checked.

**Safe Mode:** open `http://127.0.0.1:5050/?safe=1`. It persists in the browser session and is carried through generated navigation links. `?safe=0` exits it. For a session-independent lock (including demos), set `CANVAS_SAFE_MODE=1` in `.env` and restart; a URL cannot override that setting. Synthetic demo workspaces always reject uploads. Safe Mode allows local editing but blocks both preview creation and upload confirmation on the server, including previously opened confirmation pages.

Use a single local server process. In-process locking prevents concurrent app changes during an upload. Canvas provides no conditional version check for this grading endpoint, so an external edit in the brief interval between our check and write cannot be eliminated; avoid grading the same responses elsewhere while publishing.

Live publishing has not been exercised by the agent. Start with one response in a test quiz and verify the score and Additional Comments in Canvas.

## Local audit trail

Open **Activity log** in the header, or **View this quiz’s activity** in a quiz sidebar. Filter by quiz and event type, inspect before/after details, browse older entries, or export matching history as JSON. Timestamps are UTC. The append-only `activity` table lives in the same ignored SQLite database as drafts. Database triggers reject UPDATE/DELETE of audit rows; application mutations and their audit entries commit together. This is not cryptographically tamper-proof against someone with filesystem/database administration access.

Recorded events include saved draft versions (scores, comments, readiness, student/question/attempt identity), quiz snapshots, board changes, upload review/state transitions, verified outcomes, session Safe Mode changes, and rejected local POST requests (route/status only). Upload requests are journaled before they are sent. Credentials, request headers, CSRF values, and raw error bodies are not recorded. Unsent keystrokes, activity outside this app, and historical actions before audit activation cannot be reconstructed. Older upload journals remain available separately. Actor is the local instructor session, not a verified individual identity.

History has no automatic deletion. Back up `instance/grader.sqlite` while the app is stopped to retain the full audit trail; exports contain student data and feedback. Deleting the database removes history. Auditing preserves each autosaved version, so database size grows with use.

While an upload is running, the confirmation button changes to **Sending to Canvas… Ns** and a live message explains that Canvas may take a moment. Do not submit again. The browser only adds a local timer; it does not add Canvas traffic. Per-item server progress remains a follow-up improvement if uploads routinely take long enough to need it.
