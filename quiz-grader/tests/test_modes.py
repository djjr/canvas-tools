from unittest.mock import Mock
import pytest
from app import create_app
from canvas_api import CanvasClient, CanvasError
from fixtures import demo
from publishing import Publisher
from storage import Storage


def test_quiz_identity_formulas_match_existing_databases(tmp_path):
    """Keys and fingerprints locate drafts already saved in instance/grader.sqlite.
    These values were produced before grading modes were introduced; they must never change."""
    storage = Storage(tmp_path / 'db.sqlite')
    data = demo(); data['source'] = 'https://school.test'
    key = storage.save_snapshot(data)
    record = storage.snapshot(key)['records'][0]
    assert key == 'a016ceefbc1e2c72f501fbf5'
    assert record['key'] == '182e782579d2376e59bf6e3f81ba2e385c1e62038333619b551f7ddcb5fbd922'
    assert record['fingerprint'] == '188d44293366b6e0eabd0ccceb9d893b30edac515e0d6e083d96f70b5eae33b8'
    assert storage.snapshot_kind(key) == 'quiz'
    assert storage.activity(key, 'quiz.loaded')


def test_verification_raises_when_roster_lookup_fails():
    """The roster lookup carries the excused flag; verification must not proceed without it."""
    session = Mock()
    session.get.return_value = Mock(status_code=500, links={})
    client = CanvasClient('https://school.test', 'SECRET', session)
    with pytest.raises(CanvasError):
        client.load_submission('1', '2', '9', 345, 2, 55)
    assert session.get.call_count == 1


@pytest.fixture
def two_drafts(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': tmp_path / 'db.sqlite', 'SECRET_KEY': 'test'})
    storage = app.extensions['storage']
    data = demo(); data['source'] = 'https://school.test'
    key = storage.save_snapshot(data); data = storage.snapshot(key)
    first, second = data['records'][0], data['records'][1]
    storage.save_draft(first['key'], first['fingerprint'], '3', '', True)
    storage.save_draft(second['key'], second['fingerprint'], '2', '', True)
    client = Mock(); client.base = data['source']
    unreachable = {first['submission_id']}
    def load_submission(course, quiz, assignment, submission, attempt, user_id):
        if submission in unreachable:
            raise CanvasError('Canvas connection timed out.')
        found = [r for r in data['records'] if r['submission_id'] == submission]
        return False, {str(r['question']['id']): {k: r[k] for k in ('question', 'answer', 'available', 'score', 'grading_status', 'comment')} for r in found}
    client.load_submission.side_effect = load_submission
    return app, storage, key, first, second, client, unreachable


def test_one_unreachable_item_blocks_only_itself_in_preview(two_drafts):
    app, storage, key, first, second, client, unreachable = two_drafts
    batch = storage.publish_batch(Publisher(storage, client).preview(key))
    status = {item['record']['key']: (item['status'], item['message']) for item in batch['items']}
    assert status[first['key']][0] == 'blocked' and 'Could not recheck Canvas' in status[first['key']][1]
    assert status[second['key']] == ('ready', 'Ready')
    assert batch['kind'] == 'quiz'


def test_unreachable_item_stays_uncertain_during_reconcile(two_drafts):
    app, storage, key, first, second, client, unreachable = two_drafts
    unreachable.clear()
    publisher = Publisher(storage, client)
    token = publisher.preview(key)
    client.publish_question.side_effect = CanvasError('Timed out')
    assert {i['status'] for i in publisher.run(token)['items']} == {'uncertain'}
    unreachable.add(first['submission_id'])
    items = {i['record']['key']: i for i in publisher.reconcile(token)['items']}
    assert items[first['key']]['status'] == 'uncertain'
    assert 'Could not check Canvas' in items[first['key']]['message']
    assert items[second['key']]['status'] == 'uncertain'  # checked, but Canvas never received it
    assert client.publish_question.call_count == 2


def test_batches_saved_before_modes_still_confirm(two_drafts):
    app, storage, key, first, second, client, unreachable = two_drafts
    unreachable.clear()
    token = Publisher(storage, client).preview(key)
    legacy = storage.publish_batch(token); legacy.pop('kind')
    storage.publish_batch(token, legacy)
    app.config['CANVAS_CLIENT_FACTORY'] = lambda: client
    web = app.test_client(); web.get('/')
    with web.session_transaction() as session:
        headers = {'X-CSRF-Token': session['csrf']}
    assert web.post(f'/publish/{token}/confirm', data={'confirm': 'yes'}, headers=headers).status_code == 302
    assert b'Back to grading' in web.get(f'/publish/{token}').data
    assert client.publish_question.call_count == 2
