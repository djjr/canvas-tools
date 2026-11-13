"""Classic Quiz grading pages: load, grade question by question, drafts, comment boards, publish preview."""
from decimal import Decimal, InvalidOperation
from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, url_for
import markdown_export
from canvas_api import CanvasError, parse_quiz
from fixtures import demo
from web_core import canvas_client, publisher, safe_mode, storage

bp = Blueprint('quiz', __name__)


@bp.post('/load')
def load():
    try:
        if request.form.get('mode') == 'demo':
            data = demo()
        else:
            client = canvas_client()
            course, quiz = parse_quiz(request.form.get('url', ''), request.form.get('course', ''), request.form.get('quiz', ''), client.base)
            data = client.load(course, quiz)
        key = storage().save_snapshot(data)
        return redirect(url_for('quiz.grade', key=key))
    except CanvasError as error:
        return render_template('index.html', error=str(error)), 400


@bp.get('/quiz/<key>')
def grade(key):
    data = storage().snapshot(key)
    if not data:
        abort(404)
    questions = {}
    for r in data['records']:
        questions.setdefault(str(r['question']['id']), r['question'])
    selected = request.args.get('question', next(iter(questions), ''))
    if questions and selected not in questions:
        abort(404)
    records = sorted([r for r in data['records'] if str(r['question']['id']) == selected], key=lambda r: (r['name'].casefold(), r['attempt'], r['submission_id']))
    drafts = storage().drafts()
    for r in records:
        r['grading_status'] = r.get('grading_status', 'unknown')
        r['base_status'] = {'graded': 'Already Graded', 'ungraded': 'Not Graded'}.get(r['grading_status'], 'Status Unknown')
        r['default_score'] = r['question']['points_possible'] if r['grading_status'] == 'ungraded' else r['score'] if r['score'] is not None else ''
        r['draft'] = drafts.get(r['key'])
        r['stale'] = bool(r['draft'] and r['draft']['fingerprint'] != r['fingerprint'])
    ids = list(questions)
    pos = ids.index(selected) if ids else 0
    complete = sum(bool(r['draft'] and r['draft'].get('reviewed') and not r['stale']) for r in records if r['editable'])
    return render_template('grade.html', data=data, key=key, questions=questions, selected=selected, records=records, board=storage().board(key, selected), publish_history=storage().publish_history(key), complete=complete, total=sum(r['editable'] for r in records), previous=ids[pos-1] if pos else None, following=ids[pos+1] if pos+1<len(ids) else None)


def _download(text, name):
    return Response(text, mimetype='text/markdown', headers={'Content-Disposition': f'attachment; filename="{name}"'})


@bp.get('/quiz/<key>/export/<question>')
def export_question(key, question):
    """Latest-attempt responses to one question as Markdown. Anonymized unless ?names=1."""
    data = storage().snapshot(key)
    records = [r for r in (data or {}).get('records', []) if str(r['question']['id']) == question]
    if not records:
        abort(404)
    names = request.args.get('names') == '1'
    labels = markdown_export.pseudonyms(key, (r['user_id'] for r in data['records']))
    prompt = records[0]['question']
    text = markdown_export.question_markdown(data['title'], prompt, records, labels, names)
    storage().audit('quiz.exported', key, question, after={'question_id': question, 'names': names, 'students': len(markdown_export.latest_attempts(records))})
    return _download(text, markdown_export.filename(data['title'], prompt.get('question_name'), 'names' if names else 'anonymized'))


@bp.get('/quiz/<key>/export-key')
def export_key(key):
    """Private pseudonym -> name table for this quiz's anonymized exports."""
    data = storage().snapshot(key)
    if not data:
        abort(404)
    labels = markdown_export.pseudonyms(key, (r['user_id'] for r in data['records']))
    names = {r['user_id']: r['name'] for r in data['records']}
    storage().audit('quiz.exported', key, after={'name_key': True, 'students': len(labels)})
    return _download(markdown_export.key_markdown(data['title'], labels, names), markdown_export.filename(data['title'], 'name key'))


@bp.post('/quiz/<key>/board/<question>')
def update_board(key, question):
    data = storage().snapshot(key)
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
        storage().update_board(key, question, text.strip(), slot)
    except ValueError as error:
        return jsonify(error=str(error)), 409
    return jsonify(board=storage().board(key, question))


@bp.post('/quiz/<key>/draft/<record_key>')
def save(key, record_key):
    data = storage().snapshot(key)
    record = next((r for r in (data or {}).get('records', []) if r['key'] == record_key), None)
    if not record:
        abort(404)
    payload = request.get_json(silent=True) or {}
    if not record['editable']:
        return jsonify(error='This response is not available for drafting.'), 409
    existing = storage().drafts().get(record_key)
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
    storage().save_draft(record_key, record['fingerprint'], None if score is None else str(score), comment, reviewed)
    return jsonify(saved=True, complete=reviewed)


@bp.post('/quiz/<key>/publish-preview')
def publish_preview(key):
    data = storage().snapshot(key)
    if not data:
        abort(404)
    if safe_mode() or data['source'] == 'demo':
        return render_template('publish.html', error='Safe Mode: publishing is disabled.', key=key), 403
    try:
        token = publisher('quiz').preview(key)
        return redirect(url_for('publish_review', token=token))
    except CanvasError as error:
        return render_template('publish.html', error=str(error), key=key), 409
