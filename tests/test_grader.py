from unittest.mock import Mock
import pytest
from app import create_app
from canvas_api import CanvasClient, CanvasError, parse_quiz
from fixtures import demo

@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATABASE': tmp_path/'test.sqlite', 'SECRET_KEY':'test'})

def csrf(client):
    client.get('/')
    with client.session_transaction() as s:
        return {'X-CSRF-Token':s['csrf']}

def test_demo_and_draft_survive_restart(app):
    client = app.test_client()
    headers = csrf(client)
    loaded = client.post('/load', data={'mode':'demo'}, headers=headers)
    assert loaded.status_code == 302
    assert b'Evidence &amp; interpretation' in client.get(loaded.location).data
    key = loaded.location.split('/')[-1]
    record = app.extensions['storage'].snapshot(key)['records'][0]
    url = f"{loaded.location}/draft/{record['key']}"
    payload = {'fingerprint':record['fingerprint'], 'score':'2.75', 'comment':'Nice argument'}
    assert client.post(url, json=payload, headers=headers).status_code == 200
    fresh = create_app({'TESTING':True,'DATABASE':app.config['DATABASE']})
    assert b'Nice argument' in fresh.test_client().get(loaded.location).data
    for invalid in ['NaN', 'Infinity', '-1', '6.01', 'abc']:
        assert client.post(url, json={**payload,'score':invalid}, headers=headers).status_code == 400
    for extra_credit in ['5.5', '6']:
        assert client.post(url, json={**payload, 'score':extra_credit}, headers=headers).status_code == 200
    assert b'max="6"' in client.get(loaded.location).data
    assert client.post(url, json=payload).status_code == 403
    changed = demo()
    changed['records'][0]['answer']='Changed answer'
    app.extensions['storage'].save_snapshot(changed)
    assert client.post(url, json=payload, headers=headers).status_code == 409
    assert app.extensions['storage'].drafts()[record['key']]['comment'] == 'Nice argument'

def test_attempt_identity_and_sanitization(app):
    data = demo()
    one = data['records'][0].copy()
    one['attempt'] = 3
    data['records'].append(one)
    key = app.extensions['storage'].save_snapshot(data)
    rows = app.extensions['storage'].snapshot(key)['records']
    assert rows[0]['key'] != rows[-1]['key']
    html = str(app.jinja_env.filters['safe_canvas']('<p onclick="bad()">Hi<img src=x onerror=bad()><script>alert(1)</script></p>'))
    assert '<p>Hi' in html and '<script' not in html and 'onerror' not in html and '<img' not in html

class Response:
    def __init__(self, data, next_url=None, status=200):
        self.data, self.status_code = data, status
        self.links = {'next': {'url':next_url}} if next_url else {}
    def json(self):
        return self.data

def test_pagination_and_origin_guard():
    session = Mock()
    session.get.side_effect = [Response({'rows':[1]}, 'https://school.test/api/v1/next'), Response({'rows':[2]})]
    client = CanvasClient('https://school.test','secret',session)
    assert client.pages('/api/v1/first', 'rows', {'per_page':100}) == [1,2]
    assert session.get.call_count == 2
    assert all(c.kwargs['allow_redirects'] is False for c in session.get.call_args_list)
    with pytest.raises(CanvasError):
        client.get('https://evil.test/api/v1/stolen')
    assert session.get.call_count == 2
    session.get.side_effect = [Response({},status=401)]
    with pytest.raises(CanvasError,match='authentication') as error:
        client.get('/api/v1/first')
    assert 'secret' not in str(error.value)

@pytest.mark.parametrize('url', ['https://evil.test/courses/1/quizzes/2','https://school.test/courses/1/assignments/2'])
def test_bad_quiz_url(url):
    with pytest.raises(CanvasError):
        parse_quiz(url,'','','https://school.test')

def test_load_matches_history_attempt_and_keeps_partial_results():
    client = CanvasClient('https://school.test','secret')
    client.get = Mock(return_value=({'title':'Test','assignment_id':8}, None))
    sub = {'id':5,'user_id':9,'attempt':2,'workflow_state':'pending_review'}
    question = {'id':10,'question_type':'essay_question','points_possible':5}
    client.pages = Mock(side_effect=[
        [sub, {**sub,'id':6,'user_id':11}],
        [{'user_id':9,'user':{'name':'Alex'},'submission_history':[{'attempt':1,'submission_data':[{'question_id':10,'text':'Wrong attempt'}]},{'attempt':2,'submission_data':[{'question_id':10,'text':'Correct attempt','points':2.5,'more_comments':'Good'}]}]}, {'user_id':12,'missing':True}],
        [question], [{'id':10}], CanvasError('Access denied')])
    data = client.load('1','2')
    assert len(data['records']) == 1
    assert data['records'][0]['answer'] == 'Correct attempt'
    assert data['records'][0]['score'] == 2.5
    assert data['warnings'] and data['absent'][0]['state'] == 'missing'
    assert client.pages.call_args_list[2].kwargs['params']['quiz_submission_attempt'] == 2

def test_question_boards_are_isolated_and_persistent(app):
    client=app.test_client()
    headers=csrf(client)
    key=app.extensions['storage'].save_snapshot(demo())
    url=f'/quiz/{key}/board/11'
    for n in range(1,10):
        assert client.post(url,json={'text':f'Comment {n}'},headers=headers).status_code==200
    assert client.post(url,json={'text':'Comment 1'},headers=headers).status_code==200
    assert client.post(url,json={'text':'Overflow'},headers=headers).status_code==409
    assert client.post(url,json={'text':'Replacement','slot':3},headers=headers).status_code==200
    assert client.post(url,json={'text':'','slot':2},headers=headers).status_code==200
    assert client.post(url,json={'text':'New'},headers=headers).json['board']['2']=='New'
    assert app.extensions['storage'].board(key,'12')=={}
    assert app.extensions['storage'].board('another-quiz','11')=={}
    assert client.post(url,json={'text':'Bad','slot':10},headers=headers).status_code==400
    assert client.post(url,json={'text':'No CSRF'}).status_code==403
    fresh=create_app({'TESTING':True,'DATABASE':app.config['DATABASE']})
    assert fresh.extensions['storage'].board(key,'11')[3]=='Replacement'
    assert b'Comment board' in fresh.test_client().get(f'/quiz/{key}').data


def test_expired_load_form_returns_fresh_form_and_keeps_url(app):
    client = app.test_client()
    response = client.post('/load', data={'csrf':'stale', 'url':'https://school.test/courses/1/quizzes/2'})
    assert response.status_code == 403
    assert b'request was not sent to Canvas' in response.data
    assert b'value="https://school.test/courses/1/quizzes/2"' in response.data
    with client.session_transaction() as session:
        token = session['csrf']
    assert client.post('/load', data={'csrf':token, 'mode':'demo'}).status_code == 302


def test_default_score_prefers_canvas_including_zero(app):
    import re
    data = demo()
    data['records'][0]['score'] = 0
    data['records'][1]['score'] = 2.75
    data['records'][1]['grading_status'] = 'graded'
    storage = app.extensions['storage']
    key = storage.save_snapshot(data)
    client = app.test_client()
    def scores():
        html = client.get(f'/quiz/{key}').data.decode()
        return re.findall(r'name="score"[^>]*value="([^"]*)"', html)
    assert scores()[:3] == ['0', '2.75', '5']
    record = storage.snapshot(key)['records'][0]
    storage.save_draft(record['key'], record['fingerprint'], '1.5', '')
    assert scores()[0] == '1.5'
    storage.save_draft(record['key'], record['fingerprint'], None, '')
    assert scores()[0] == ''


@pytest.mark.parametrize('detail,answer,expected', [
    ({'correct':'undefined','points':0},{},'ungraded'),
    ({'correct':False,'points':0},{},'graded'),
    ({'correct':'defined','points':0},{},'graded'),
    ({'correct':True},{},'graded'),
    ({'points':0},{},'unknown'),
    ({'correct':None},{},'unknown'),
    ({'correct':'false'},{},'unknown'),
    ({'correct':'undefined'},{'correct':False},'unknown'),
])
def test_grading_markers(detail, answer, expected):
    from canvas_api import grading_status
    assert grading_status(detail, answer) == expected


def test_ungraded_zero_and_unknown_defaults(app):
    import re
    data=demo()
    for r in data['records']:
        r['score']=0
        r['grading_status']='ungraded'
    data['records'][1]['grading_status']='graded'
    data['records'][2]['grading_status']='unknown'
    data['records'][3]['grading_status']='unknown'
    data['records'][3]['score']=None
    key=app.extensions['storage'].save_snapshot(data)
    html=app.test_client().get(f'/quiz/{key}').data.decode()
    assert re.findall(r'name="score"[^>]*value="([^"]*)"',html)==['5','0','0','']
    assert 'Grading status unconfirmed' in html


def test_review_is_explicit_toggle_and_edits_clear_it(app):
    client=app.test_client(); headers=csrf(client)
    storage=app.extensions['storage']; key=storage.save_snapshot(demo())
    r=storage.snapshot(key)['records'][0]
    url=f"/quiz/{key}/draft/{r['key']}"
    payload={'fingerprint':r['fingerprint'],'score':'5','comment':'Feedback'}
    assert client.post(url,json=payload,headers=headers).json['complete'] is False
    assert client.post(url,json={**payload,'reviewed':True},headers=headers).json['complete'] is True
    assert storage.drafts()[r['key']]['reviewed']==1
    assert b'1 / 4 newly graded' in client.get(f'/quiz/{key}').data
    assert client.post(url,json={**payload,'reviewed':False},headers=headers).json['complete'] is False
    assert client.post(url,json={**payload,'reviewed':True,'score':''},headers=headers).status_code==400
    client.post(url,json={**payload,'reviewed':True},headers=headers)
    client.post(url,json={**payload,'comment':'Edited'},headers=headers)
    assert storage.drafts()[r['key']]['reviewed']==0


def test_toggle_off_preserves_score_feedback_and_canvas_status(app):
    client=app.test_client(); headers=csrf(client)
    storage=app.extensions['storage']; key=storage.save_snapshot(demo())
    r=storage.snapshot(key)['records'][0]
    url=f"/quiz/{key}/draft/{r['key']}"
    payload={'fingerprint':r['fingerprint'],'score':'3.25','comment':'Still working on this.', 'reviewed':True}
    client.post(url,json=payload,headers=headers)
    assert '✓ Newly Graded' in client.get(f'/quiz/{key}').data.decode()
    client.post(url,json={**payload,'reviewed':False},headers=headers)
    draft=storage.drafts()[r['key']]
    assert (draft['score'],draft['comment'],draft['reviewed']) == ('3.25','Still working on this.',0)
    html=client.get(f'/quiz/{key}').data.decode()
    assert '>Already Graded</button>' in html
    assert '>Not Graded</button>' in html
    assert '✓ Newly Graded' not in html


def test_existing_canvas_comment_prefills_feedback_without_queueing(app):
    import re
    data=demo(); data['records'][0]['comment']='Existing Canvas note'
    key=app.extensions['storage'].save_snapshot(data)
    html=app.test_client().get(f'/quiz/{key}').data.decode()
    assert 'Existing Canvas note' in html
    assert 'Not queued for upload' in html
    assert not app.extensions['storage'].drafts()
