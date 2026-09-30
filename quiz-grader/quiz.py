"""Classic Quiz workspace identity and change detection.

These formulas determine the keys of snapshots and drafts already stored in
instance/grader.sqlite. Changing them orphans existing drafts; tests pin their values.
"""
import hashlib
import json

KIND = 'quiz'
LOADED_ACTION = 'quiz.loaded'


def workspace_key(data):
    return hashlib.sha256(json.dumps([data['source'], data['course'], data['quiz']]).encode()).hexdigest()[:24]


def record_key(data, record):
    identity = [data['source'], data['course'], data['quiz'], record['submission_id'], record['user_id'], record['attempt'], record['question']['id']]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def fingerprint(record):
    return hashlib.sha256(json.dumps([record['question'], record['answer'], record['score'], record['comment'], record.get('grading_status', 'unknown')], sort_keys=True).encode()).hexdigest()


def draft_context(record):
    """Identity recorded in the audit log alongside each saved draft."""
    context = {field: record[field] for field in ('name', 'user_id', 'submission_id', 'attempt')}
    context['question_id'] = record['question']['id']
    return context
