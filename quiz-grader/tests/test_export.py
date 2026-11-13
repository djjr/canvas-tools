import pytest
from app import create_app
from fixtures import demo
from markdown_export import html_to_markdown, latest_attempts, pseudonyms


@pytest.fixture
def loaded(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': tmp_path / 'test.sqlite', 'SECRET_KEY': 'test'})
    client = app.test_client()
    client.get('/')
    with client.session_transaction() as s:
        headers = {'X-CSRF-Token': s['csrf']}
    location = client.post('/load', data={'mode': 'demo'}, headers=headers).location
    return app, client, location.split('/')[-1]


def test_html_to_markdown_basics():
    html = '<p>One <strong>bold</strong> and <em>soft</em> &amp; more.</p><p>Line<br>break</p><ul><li>a</li><li>b</li></ul><ol><li>x</li><li>y</li></ol><p><a href="https://example.com">link</a> <a href="javascript:x()">bad</a></p><script>alert(1)</script>'
    md = html_to_markdown(html)
    assert 'One **bold** and *soft* & more.' in md
    assert 'Line  \nbreak' in md
    assert '- a\n- b' in md and '1. x\n2. y' in md
    assert '[link](https://example.com)' in md and '[bad]' in md and 'javascript' not in md
    assert 'alert' not in md and '\n\n\n' not in md
    assert html_to_markdown(None) == '' and html_to_markdown('') == ''


def test_pseudonyms_stable_and_not_alphabetical():
    first = pseudonyms('ws', [10, 11, 12, 13])
    assert first == pseudonyms('ws', [13, 12, 11, 10, 10])
    assert sorted(first.values()) == ['Student 01', 'Student 02', 'Student 03', 'Student 04']


def test_latest_attempt_only():
    records = [dict(user_id=1, attempt=1, submission_id=5), dict(user_id=1, attempt=2, submission_id=5), dict(user_id=2, attempt=1, submission_id=6)]
    assert sorted((r['user_id'], r['attempt']) for r in latest_attempts(records)) == [(1, 2), (2, 1)]


def test_export_anonymized_by_default(loaded):
    app, client, key = loaded
    response = client.get(f'/quiz/{key}/export/11')
    assert response.status_code == 200
    assert response.mimetype == 'text/markdown'
    assert 'attachment' in response.headers['Content-Disposition'] and 'anonymized' in response.headers['Content-Disposition']
    text = response.get_data(as_text=True)
    assert text.startswith('# Week 03')
    assert 'Choose one claim from the reading' in text
    assert 'comparison group would help' in text
    assert '*Blank answer submitted.*' in text and '*Unanswered.*' in text
    for person in demo()['records']:
        assert person['name'] not in text
    assert text.count('### Student ') == 4
    assert app.extensions['storage'].activity(action='quiz.exported')[0]['after']['names'] is False


def test_export_with_names_and_key(loaded):
    _, client, key = loaded
    text = client.get(f'/quiz/{key}/export/11?names=1').get_data(as_text=True)
    assert '### Alex Morgan' in text and text.index('Alex Morgan') < text.index('Jordan Lee')
    anon = client.get(f'/quiz/{key}/export/11').get_data(as_text=True)
    table = client.get(f'/quiz/{key}/export-key').get_data(as_text=True)
    label = anon.split('### ')[1].split('\n')[0]
    assert f'| {label} |' in table and 'Alex Morgan' in table
    assert client.get(f'/quiz/{key}/export/999').status_code == 404
    assert client.get('/quiz/nope/export-key').status_code == 404
    assert b'export-links' in client.get(f'/quiz/{key}').data
