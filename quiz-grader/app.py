"""App shell shared by every grading mode: security, Safe Mode, activity log, and upload review.
Each mode registers its own blueprint of grading pages."""
import json
import secrets
import threading
from pathlib import Path
import bleach
from dotenv import load_dotenv
from flask import Response, stream_with_context, Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup
from canvas_api import CanvasError
from storage import Storage
import quiz_routes
from web_core import publisher, safe_mode, workspace_url

ROOT = Path(__file__).parent

def create_app(test_config=None):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), DATABASE=ROOT / 'instance/grader.sqlite', MAX_CONTENT_LENGTH=100_000, SESSION_COOKIE_SAMESITE='Strict', TRUSTED_HOSTS=['localhost', '127.0.0.1'])
    if test_config:
        app.config.update(test_config)
    storage = Storage(app.config['DATABASE'])
    app.extensions['storage'] = storage
    app.register_blueprint(quiz_routes.bp)

    mutation_lock = threading.RLock()

    @app.context_processor
    def mode_context():
        return {'safe_mode': safe_mode(), 'workspace_url': workspace_url}

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
            g.mutation_locked = True

    @app.teardown_request
    def unlock(error):
        if g.pop('mutation_locked', False):
            mutation_lock.release()

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

    @app.route('/demo/reset', methods=['GET', 'POST'])
    def reset_demo():
        if request.method == 'POST':
            key = storage.reset_demo()
            return redirect(url_for('quiz.grade', key=key))
        return render_template('reset_demo.html')

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
            publisher(batch.get('kind')).reconcile(token)
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
            publisher(batch.get('kind')).run(token)
        except CanvasError as error:
            return render_template('publish.html', error=str(error), key=batch['key']), 409
        return redirect(url_for('publish_review', token=token))

    return app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5050, debug=False)
