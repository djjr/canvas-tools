import os
import json
import secrets
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
import bleach
from dotenv import load_dotenv
from flask import Response, stream_with_context, Flask, abort, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup
from canvas_api import CanvasClient, CanvasError, parse_quiz
from storage import Storage
from fixtures import demo
from publishing import Publisher

ROOT = Path(__file__).parent

def create_app(test_config=None):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), DATABASE=ROOT / 'instance/grader.sqlite', MAX_CONTENT_LENGTH=100_000, SESSION_COOKIE_SAMESITE='Strict', TRUSTED_HOSTS=['localhost', '127.0.0.1'])
    if test_config:
        app.config.update(test_config)
    storage = Storage(app.config['DATABASE'])
    app.extensions['storage'] = storage

    mutation_lock = threading.RLock()

    def safe_mode():
        return os.getenv('CANVAS_SAFE_MODE', '').lower() in ('1', 'true', 'yes') or session.get('safe', False)

    @app.context_processor
    def mode_context():
        return {'safe_mode': safe_mode()}

    @app.url_defaults
    def safe_links(endpoint, values):
        if safe_mode():
            values.setdefault('safe', '1')

    @app.before_request
    def mode_and_lock():
        if request.args.get('safe') in ('0', '1'):
            new_safe = request.args['safe'] == '1'
            if session.get('safe', False) != new_safe:
                storage.audit('mode.changed', before={'safe': session.get('safe', False)}, after={'safe': new_safe})
            session['safe'] = new_safe
        if request.method == 'POST':
            mutation_lock.acquire()
            from flask import g
            g.mutation_locked = True

    @app.teardown_request
    def unlock(error):
        from flask import g
        if g.pop('mutation_locked', False):
            mutation_lock.release()

    def publisher():
        factory = app.config.get('CANVAS_CLIENT_FACTORY')
        client = factory() if factory else CanvasClient(os.getenv('CANVAS_BASE_URL', ''), os.getenv('CANVAS_TOKEN', ''))
        return Publisher(storage, client)

    @app.template_filter('safe_canvas')
    def safe_canvas(value):
        return Markup(bleach.clean(str(value or ''), tags=['p', 'br', 'strong', 'em', 'b', 'i', 'u', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'sub', 'sup', 'table', 'thead', 'tbody', 'tr', 'th', 'td'], attributes={}, strip=True))

    @app.before_request
    def protect():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST' and not secrets.compare_digest(str(request.headers.get('X-CSRF-Token') or request.form.get('csrf', '')), session['csrf']):
            message = 'The app restarted or this form expired. Your request was not sent to Canvas. Please try loading the quiz again.'
            if request.path == '/load':
                return render_template('index.html', error=message), 403
            return jsonify(error='Your session expired after an app restart. Copy any unsaved feedback, then refresh the page and try again.'), 403

    @app.after_request
    def headers(response):
        if request.method == 'POST' and response.status_code >= 400:
            storage.audit('request.rejected', workspace=(request.view_args or {}).get('key'), after={'route': str(request.url_rule), 'status': response.status_code})
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'none'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.post('/load')
    def load():
        try:
            if request.form.get('mode') == 'demo':
                data = demo()
            else:
                client = CanvasClient(os.getenv('CANVAS_BASE_URL', ''), os.getenv('CANVAS_TOKEN', ''))
                course, quiz = parse_quiz(request.form.get('url', ''), request.form.get('course', ''), request.form.get('quiz', ''), client.base)
                data = client.load(course, quiz)
            key = storage.save_snapshot(data)
            return redirect(url_for('grade', key=key))
        except CanvasError as error:
            return render_template('index.html', error=str(error)), 400

    @app.get('/quiz/<key>')
    def grade(key):
        data = storage.snapshot(key)
        if not data:
            abort(404)
        questions = {}
        for r in data['records']:
            questions.setdefault(str(r['question']['id']), r['question'])
        selected = request.args.get('question', next(iter(questions), ''))
        if questions and selected not in questions:
            abort(404)
        records = sorted([r for r in data['records'] if str(r['question']['id']) == selected], key=lambda r: (r['name'].casefold(), r['attempt'], r['submission_id']))
        drafts = storage.drafts()
        for r in records:
            r['grading_status'] = r.get('grading_status', 'unknown')
            r['base_status'] = {'graded': 'Already Graded', 'ungraded': 'Not Graded'}.get(r['grading_status'], 'Status Unknown')
            r['default_score'] = r['question']['points_possible'] if r['grading_status'] == 'ungraded' else r['score'] if r['score'] is not None else ''
            r['draft'] = drafts.get(r['key'])
            r['stale'] = bool(r['draft'] and r['draft']['fingerprint'] != r['fingerprint'])
        ids = list(questions)
        pos = ids.index(selected) if ids else 0
        complete = sum(bool(r['draft'] and r['draft'].get('reviewed') and not r['stale']) for r in records if r['editable'])
        return render_template('grade.html', data=data, key=key, questions=questions, selected=selected, records=records, board=storage.board(key, selected), publish_history=storage.publish_history(key), complete=complete, total=sum(r['editable'] for r in records), previous=ids[pos-1] if pos else None, following=ids[pos+1] if pos+1<len(ids) else None)

    @app.post('/quiz/<key>/board/<question>')
    def update_board(key, question):
        data = storage.snapshot(key)
        if not data or not any(str(r['question']['id']) == question for r in data['records']):
            abort(404)
        payload = request.get_json(silent=True) or {}
        text = payload.get('text')
        slot = payload.get('slot')
        if not isinstance(text, str) or len(text) > 10000 or (slot is not None and (type(slot) is not int or not 1 <= slot <= 9)):
            return jsonify(error='Use text up to 10,000 characters and a slot from 1 to 9.'), 400
        if not text.strip() and slot is None:
            return jsonify(error='Write feedback before saving it to the board.'), 400
        try:
            storage.update_board(key, question, text.strip(), slot)
        except ValueError as error:
            return jsonify(error=str(error)), 409
        return jsonify(board=storage.board(key, question))

    @app.post('/quiz/<key>/draft/<record_key>')
    def save(key, record_key):
        data = storage.snapshot(key)
        record = next((r for r in (data or {}).get('records', []) if r['key'] == record_key), None)
        if not record:
            abort(404)
        payload = request.get_json(silent=True) or {}
        if not record['editable']:
            return jsonify(error='This response is not available for drafting.'), 409
        existing = storage.drafts().get(record_key)
        if payload.get('fingerprint') != record['fingerprint'] or (existing and existing['fingerprint'] != record['fingerprint']):
            return jsonify(error='Canvas data changed. The previous draft is preserved; review it before continuing.'), 409
        comment = payload.get('comment', '')
        if not isinstance(comment, str) or len(comment) > 10000:
            return jsonify(error='Feedback must be text of at most 10,000 characters.'), 400
        raw = payload.get('score')
        try:
            score = None if raw in (None, '') else Decimal(str(raw))
            maximum = Decimal(str(record['question']['points_possible'])) + 1
            if score is not None and (not score.is_finite() or score < 0 or score > maximum):
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            return jsonify(error='Enter a score between 0 and one point above the points possible.'), 400
        reviewed = payload.get('reviewed', False)
        if type(reviewed) is not bool or (reviewed and score is None):
            return jsonify(error='Enter a score before marking this response graded.'), 400
        storage.save_draft(record_key, record['fingerprint'], None if score is None else str(score), comment, reviewed)
        return jsonify(saved=True, complete=reviewed)

    @app.get('/activity')
    def activity_log():
        workspace = request.args.get('workspace', '')
        action = request.args.get('action', '')
        cursor = request.args.get('before', type=int)
        rows = storage.activity(workspace, action, cursor, 51)
        snapshots, actions = storage.activity_filters()
        workspaces = [{'key': r['id'], 'title': json.loads(r['data'])['title']} for r in snapshots]
        return render_template('activity.html', rows=rows[:50], next_cursor=rows[49]['id'] if len(rows)>50 else None, workspace=workspace, action=action, workspaces=workspaces, actions=actions)

    @app.get('/activity/export')
    def activity_export():
        workspace = request.args.get('workspace', '')
        action = request.args.get('action', '')
        # Cursor pagination exports all matching history without loading it all in memory.
        def generate():
            cursor = None
            yield '['
            first = True
            while True:
                rows = storage.activity(workspace, action, cursor, 200)
                if not rows:
                    break
                for row in rows:
                    row.pop('before_json'); row.pop('after_json')
                    yield ('' if first else ',') + json.dumps(row)
                    first = False
                cursor = rows[-1]['id']
            yield ']'
        return Response(stream_with_context(generate()), mimetype='application/json', headers={'Content-Disposition':'attachment; filename="canvas-grader-activity.json"'})

    @app.post('/quiz/<key>/publish-preview')
    def publish_preview(key):
        data = storage.snapshot(key)
        if not data:
            abort(404)
        if safe_mode() or data['source'] == 'demo':
            return render_template('publish.html', error='Safe Mode: publishing is disabled.', key=key), 403
        try:
            token = publisher().preview(key)
            return redirect(url_for('publish_review', token=token))
        except CanvasError as error:
            return render_template('publish.html', error=str(error), key=key), 409

    @app.get('/publish/<token>')
    def publish_review(token):
        batch = storage.publish_batch(token)
        if not batch:
            abort(404)
        return render_template('publish.html', batch=batch, token=token, key=batch['key'])

    @app.post('/publish/<token>/reconcile')
    def publish_reconcile(token):
        batch = storage.publish_batch(token)
        if not batch:
            abort(404)
        try:
            publisher().reconcile(token)
        except CanvasError as error:
            return render_template('publish.html', error=str(error), key=batch['key']), 409
        return redirect(url_for('publish_review', token=token))

    @app.post('/publish/<token>/confirm')
    def publish_confirm(token):
        batch = storage.publish_batch(token)
        if not batch:
            abort(404)
        if safe_mode() or batch['source'] == 'demo':
            return render_template('publish.html', error='Safe Mode: publishing is disabled.', key=batch['key']), 403
        if request.form.get('confirm') != 'yes':
            abort(400)
        try:
            publisher().run(token)
        except CanvasError as error:
            return render_template('publish.html', error=str(error), key=batch['key']), 409
        return redirect(url_for('publish_review', token=token))

    return app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5050, debug=False)
