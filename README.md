# Canvas tools

Local tools for working with Canvas LMS.

## Quiz grader

[Margin — Classic Quiz Grader](quiz-grader/README.md) lets instructors grade
essay responses question by question, save drafts locally, and review and
publish explicitly confirmed grades and per-question feedback to Canvas.
It includes a synthetic demo, Safe Mode, reusable comment boards, and a local
audit trail.

Start with the [setup and user guide](quiz-grader/README.md).
For development, read the [coding-agent handoff](quiz-grader/LLM_DESIGN.md).

Keep credentials in `quiz-grader/.env`. Local student data belongs in
`quiz-grader/instance/`. Both are excluded from Git.
