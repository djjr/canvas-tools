"""Build a source-only distribution without reading local runtime data."""
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
# Exact files only: never recursively collect a directory or trust .gitignore.
FILES = (
    'app.py', 'canvas_core.py', 'canvas_api.py', 'fixtures.py', 'publishing_core.py',
    'publishing.py', 'quiz.py', 'quiz_routes.py', 'storage.py', 'web_core.py',
    'requirements.txt', 'requirements-dev.txt',
    'README.md', 'PROJECT.md', 'LLM_DESIGN.md', 'CANVAS_GRADER_HANDOFF.md', 'ASSIGNMENTS_DESIGN.md',
    'static/app.js', 'static/style.css',
    'templates/base.html', 'templates/index.html', 'templates/grade.html',
    'templates/publish.html', 'templates/activity.html', 'templates/reset_demo.html',
    'tests/test_grader.py', 'tests/test_publishing.py', 'tests/test_activity.py',
    'tests/test_demo_reset.py', 'tests/test_modes.py',
)
EXAMPLE_ENV = ('CANVAS_BASE_URL=https://your-university.instructure.com\n'
               'CANVAS_TOKEN=\n'
               '# Set to 0 only when you want to test confirmed uploads.\n'
               'CANVAS_SAFE_MODE=1\n')


def build_archive(root=ROOT, destination=None):
    root = Path(root).resolve()
    for name in FILES:
        path = root / name
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise ValueError('Missing or unsafe package file: ' + name)
    if destination is None:
        destination = root / 'dist' / ('canvas-quiz-grader-share-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.zip')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'x', ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(root / name, 'canvas-quiz-grader/' + name)
        # Never copy the user's .env or .env.example, even if it looks harmless.
        archive.writestr('canvas-quiz-grader/.env.example', EXAMPLE_ENV)
        archive.writestr('canvas-quiz-grader/.gitignore',
                         '.env\ninstance/\n.venv/\n__pycache__/\n.pytest_cache/\ndist/\n*.pyc\n')
    return destination


if __name__ == '__main__':
    print('Created: ' + str(build_archive()))
    print('Source and synthetic demo only. Credentials, runtime data, and exports excluded.')
