"""Explicit, journaled publishing. No automatic retries of ambiguous writes."""
import copy
import hashlib
import json
import secrets
from decimal import Decimal
from canvas_api import CanvasError


def draft_version(draft):
    return hashlib.sha256(json.dumps([draft['fingerprint'], draft['score'], draft['comment'], draft['reviewed']]).encode()).hexdigest()


def fingerprint(record):
    return hashlib.sha256(json.dumps([record['question'], record['answer'], record['score'], record['comment'], record.get('grading_status', 'unknown')], sort_keys=True).encode()).hexdigest()


def matches(record, item):
    try:
        return (record.get('grading_status') == 'graded'
                and Decimal(str(record['score'])) == Decimal(item['draft']['score'])
                and (not item['draft']['comment'].strip() or record['comment'] == item['draft']['comment']))
    except (ValueError, TypeError, ArithmeticError):
        return False


class Publisher:
    def __init__(self, storage, client):
        self.storage, self.client = storage, client

    def check_site(self, data):
        if data['source'] != self.client.base:
            raise CanvasError('Configured Canvas site differs from this workspace. Reload the correct quiz.')

    def refresh(self, data, record):
        """Current Canvas state for exactly one record. Scoped to one submission
        instead of a full-quiz reload, since callers only ever look up one identity."""
        excused, records = self.client.load_submission(data['course'], data['quiz'], data.get('assignment'), record['submission_id'], record['attempt'], record['user_id'])
        fresh = records.get(str(record['question']['id']))
        if not fresh:
            return None
        state = 'excused' if excused else record['state']
        current = {**record, **fresh, 'state': state, 'editable': fresh['available'] and state in ('complete', 'pending_review')}
        current['fingerprint'] = fingerprint(current)
        return current

    def preview(self, key):
        data = self.storage.snapshot(key)
        if not data or data['source'] == 'demo':
            raise CanvasError('Demo workspaces cannot publish.')
        self.check_site(data)
        drafts = self.storage.drafts()
        uncertain = {item['record']['key'] for item in self.storage.uncertain_items(key)}
        items = []
        for record in data['records']:
            draft = drafts.get(record['key'])
            if not draft or not draft['reviewed']:
                continue
            current = self.refresh(data, record)
            error = None
            if not record['editable'] or not current or not current['editable']:
                error = 'This exact attempt is unavailable or cannot be graded.'
            elif draft['fingerprint'] != record['fingerprint'] or current['fingerprint'] != record['fingerprint']:
                error = 'Canvas data changed. Reload and review this draft.'
            try:
                score = Decimal(draft['score'])
                if not score.is_finite() or score < 0 or score > Decimal(str(record['question']['points_possible'])) + 1:
                    error = 'Invalid draft score.'
            except (ValueError, TypeError, ArithmeticError):
                error = 'Invalid draft score.'
            if record['key'] in uncertain:
                error = 'A previous upload has an uncertain result. Further writes are blocked pending reconciliation.'
            items.append({'record':record, 'draft':draft, 'version':draft_version(draft), 'status':'blocked' if error else 'ready', 'message':error or 'Ready'})
        batch = {'key':key, 'title':data['title'], 'source':data['source'], 'course':data['course'], 'quiz':data['quiz'], 'items':items, 'state':'preview'}
        token = secrets.token_hex(24)
        self.storage.publish_batch(token, batch)
        return token

    def reconcile(self, token):
        batch = self.storage.publish_batch(token)
        if not batch:
            raise CanvasError('Upload review not found.')
        data = self.storage.snapshot(batch['key'])
        self.check_site(data)
        for item in batch['items']:
            if item['status'] != 'uncertain':
                continue
            current = self.refresh(data, item['record'])
            draft = self.storage.drafts().get(item['record']['key'])
            if current and matches(current, item):
                if draft and draft_version(draft) == item['version']:
                    updated = copy.deepcopy(current)
                    updated['key'] = item['record']['key']
                    self.storage.complete_publish(batch['key'], updated, item['draft'])
                item['status'] = 'success'
                item['message'] = 'Expected result verified in Canvas; no additional write sent.'
            else:
                item['message'] = 'Expected result not verified. Further writes remain blocked; inspect this item in Canvas.'
        self.storage.publish_batch(token, batch)
        return batch

    def run(self, token):
        batch = self.storage.publish_batch(token)
        if not batch or batch['state'] != 'preview':
            raise CanvasError('This review was already submitted. View its results or create a new review.')
        batch['state'] = 'running'
        self.storage.publish_batch(token, batch)
        data = self.storage.snapshot(batch['key'])
        self.check_site(data)
        for item in batch['items']:
            if item['status'] != 'ready':
                continue
            record, expected = item['record'], item['draft']
            try:
                draft = self.storage.drafts().get(record['key'])
                if not draft or draft_version(draft) != item['version']:
                    raise CanvasError('Local draft changed after review. Create a new review.')
                current = self.refresh(data, record)
                if not current or not current['editable'] or current['fingerprint'] != record['fingerprint']:
                    raise CanvasError('Canvas changed after review. No update sent.')
                item['status'], item['message'] = 'uncertain', 'Request may have been sent. Verify in Canvas before retrying.'
                self.storage.publish_batch(token, batch)  # Durable before the network write.
                self.client.publish_question(data['course'], data['quiz'], record['submission_id'], record['attempt'], record['question']['id'], expected['score'], expected['comment'])
                current = self.refresh(data, record)
                if not current or not matches(current, item):
                    raise CanvasError('Canvas did not confirm the expected result. Verify in Canvas before retrying.')
                updated = copy.deepcopy(current)
                updated['key'] = record['key']
                # Refresh just this item, leaving other cached drafts and versions alone.
                self.storage.complete_publish(batch['key'], updated, expected)
                item['status'], item['message'] = 'success', 'Saved to Canvas and verified.'
            except CanvasError as error:
                if item['status'] != 'uncertain':
                    item['status'] = 'blocked'
                item['message'] = str(error)
            self.storage.publish_batch(token, batch)
        batch['state'] = 'done'
        self.storage.publish_batch(token, batch)
        return batch
