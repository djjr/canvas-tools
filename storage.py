import hashlib
import json
import sqlite3
from pathlib import Path

class Storage:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, score TEXT, comment TEXT NOT NULL, updated TEXT DEFAULT CURRENT_TIMESTAMP);')

        with self.connect() as db:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(drafts)')}
            if 'reviewed' not in columns:
                db.execute('ALTER TABLE drafts ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0')

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    actor TEXT NOT NULL DEFAULT 'Local instructor session',
                    action TEXT NOT NULL, workspace TEXT, subject TEXT,
                    before_json TEXT NOT NULL, after_json TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS activity_no_update BEFORE UPDATE ON activity
                    BEGIN SELECT RAISE(ABORT, 'Activity is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS activity_no_delete BEFORE DELETE ON activity
                    BEGIN SELECT RAISE(ABORT, 'Activity is append-only'); END;
            """)
            if not db.execute('SELECT 1 FROM activity LIMIT 1').fetchone():
                self._audit(db, 'audit.started', after={'note': 'Detailed auditing begins here. Earlier activity cannot be reconstructed; existing upload journals remain available.'})

    @staticmethod
    def _audit(db, action, workspace=None, subject=None, before=None, after=None):
        db.execute('INSERT INTO activity (action, workspace, subject, before_json, after_json) VALUES (?, ?, ?, ?, ?)',
                   (action, workspace, subject, json.dumps(before), json.dumps(after)))

    def audit(self, action, workspace=None, subject=None, before=None, after=None):
        with self.connect() as db:
            self._audit(db, action, workspace, subject, before, after)

    def activity(self, workspace=None, action=None, before_id=None, limit=50):
        clauses, values = [], []
        for column, value in [('workspace', workspace), ('action', action)]:
            if value:
                clauses.append(column + '=?'); values.append(value)
        if before_id:
            clauses.append('id<?'); values.append(before_id)
        query = 'SELECT * FROM activity' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY id DESC LIMIT ?'
        with self.connect() as db:
            rows = db.execute(query, values + [limit]).fetchall()
        return [dict(r, before=json.loads(r['before_json']), after=json.loads(r['after_json'])) for r in rows]

    def activity_filters(self):
        with self.connect() as db:
            return ([dict(r) for r in db.execute('SELECT id, data FROM snapshots')],
                    [r['action'] for r in db.execute('SELECT DISTINCT action FROM activity ORDER BY action')])

    def board(self, workspace, question):
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS comments (workspace TEXT, question TEXT, slot INTEGER, text TEXT NOT NULL, PRIMARY KEY(workspace, question, slot))')
            return {r['slot']: r['text'] for r in db.execute('SELECT slot, text FROM comments WHERE workspace=? AND question=? ORDER BY slot', (workspace, question))}

    def update_board(self, workspace, question, text, slot=None):
        self.board(workspace, question)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = {r['slot']: r['text'] for r in db.execute('SELECT slot, text FROM comments WHERE workspace=? AND question=?', (workspace, question))}
            if text and text in rows.values():
                return
            if slot is None:
                slot = next((n for n in range(1, 10) if n not in rows), None)
                if slot is None:
                    raise ValueError('Board full. Remove a comment or edit a slot to replace it.')
            self._audit(db, 'board.changed', workspace, str(question) + ':' + str(slot), rows.get(slot), text or None)
            if text:
                db.execute('INSERT OR REPLACE INTO comments VALUES (?, ?, ?, ?)', (workspace, question, slot, text))
            else:
                db.execute('DELETE FROM comments WHERE workspace=? AND question=? AND slot=?', (workspace, question, slot))

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def save_snapshot(self, data):
        key = hashlib.sha256(json.dumps([data['source'], data['course'], data['quiz']]).encode()).hexdigest()[:24]
        for r in data['records']:
            identity = [data['source'], data['course'], data['quiz'], r['submission_id'], r['user_id'], r['attempt'], r['question']['id']]
            r['key'] = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            r['fingerprint'] = hashlib.sha256(json.dumps([r['question'], r['answer'], r['score'], r['comment'], r.get('grading_status', 'unknown')], sort_keys=True).encode()).hexdigest()
        with self.connect() as db:
            old = db.execute('SELECT data FROM snapshots WHERE id=?', (key,)).fetchone()
            self._audit(db, 'quiz.loaded', key, after=data, before=json.loads(old['data']) if old else None)
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?, ?)', (key, json.dumps(data)))
        return key

    def snapshot(self, key):
        with self.connect() as db:
            row = db.execute('SELECT data FROM snapshots WHERE id=?', (key,)).fetchone()
        return json.loads(row['data']) if row else None

    def drafts(self):
        with self.connect() as db:
            return {r['id']: dict(r) for r in db.execute('SELECT * FROM drafts')}

    def save_draft(self, key, fingerprint, score, comment, reviewed=False):
        with self.connect() as db:
            old = db.execute('SELECT * FROM drafts WHERE id=?', (key,)).fetchone()
            workspace = None
            context = {}
            for snapshot in db.execute('SELECT id, data FROM snapshots'):
                record = next((r for r in json.loads(snapshot['data'])['records'] if r['key'] == key), None)
                if record:
                    workspace = snapshot['id']
                    context = {field: record[field] for field in ('name', 'user_id', 'submission_id', 'attempt')}
                    context['question_id'] = record['question']['id']
                    break
            self._audit(db, 'draft.saved', workspace, key, dict(old) if old else None, dict(context, score=score, comment=comment, reviewed=bool(reviewed), fingerprint=fingerprint))
            db.execute('INSERT INTO drafts (id, fingerprint, score, comment, reviewed) VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint, score=excluded.score, comment=excluded.comment, updated=CURRENT_TIMESTAMP, reviewed=excluded.reviewed', (key, fingerprint, score, comment, int(reviewed)))

    def publish_batch(self, token, data=None):
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS publish_batches (token TEXT PRIMARY KEY, data TEXT NOT NULL)')
            if data is not None:
                old = db.execute('SELECT data FROM publish_batches WHERE token=?', (token,)).fetchone()
                self._audit(db, 'upload.' + data['state'], data['key'], token, json.loads(old['data']) if old else None, data)
                db.execute('INSERT OR REPLACE INTO publish_batches VALUES (?, ?)', (token, json.dumps(data)))
                return data
            row = db.execute('SELECT data FROM publish_batches WHERE token=?', (token,)).fetchone()
            return json.loads(row['data']) if row else None

    def complete_publish(self, key, record, draft):
        with self.connect() as db:
            row = db.execute('SELECT data FROM snapshots WHERE id=?', (key,)).fetchone()
            data = json.loads(row['data'])
            self._audit(db, 'upload.verified', key, record['key'], {'record': next((r for r in data['records'] if r['key'] == record['key']), None), 'draft': draft}, record)
            data['records'] = [record if r['key'] == record['key'] else r for r in data['records']]
            db.execute('UPDATE snapshots SET data=? WHERE id=?', (json.dumps(data), key))
            db.execute('UPDATE drafts SET fingerprint=?, reviewed=0 WHERE id=?', (record['fingerprint'], record['key']))


    def publish_history(self, key):
        self.publish_batch('initialize')
        with self.connect() as db:
            rows = [(r['token'], json.loads(r['data'])) for r in db.execute('SELECT token, data FROM publish_batches ORDER BY rowid DESC')]
        return [{'token':token, 'state':data['state']} for token, data in rows if data['key'] == key][:10]

    def uncertain_items(self, key):
        self.publish_batch('initialize')
        with self.connect() as db:
            batches = [json.loads(r['data']) for r in db.execute('SELECT data FROM publish_batches')]
        return [item for batch in batches if batch['key'] == key for item in batch['items'] if item['status'] == 'uncertain']
