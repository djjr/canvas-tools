import sqlite3
import pytest
from app import create_app
from fixtures import demo

@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True,'SECRET_KEY':'test','DATABASE':tmp_path/'audit.sqlite'})

def test_history_keeps_before_after_and_survives_restart(app):
    s=app.extensions['storage'];key=s.save_snapshot(demo());r=s.snapshot(key)['records'][0]
    s.save_draft(r['key'],r['fingerprint'],'2','First',True)
    s.save_draft(r['key'],r['fingerprint'],'3','Second',False)
    rows=s.activity(key,'draft.saved')
    assert len(rows)==2
    assert rows[0]['before']['comment']=='First'
    assert rows[0]['after']['comment']=='Second'
    assert rows[0]['before']['reviewed']==1 and rows[0]['after']['reviewed'] is False
    assert rows[0]['after']['attempt']==r['attempt']
    assert rows[0]['occurred_at'].endswith('Z')
    fresh=create_app({'TESTING':True,'DATABASE':app.config['DATABASE']})
    assert len(fresh.extensions['storage'].activity(key,'draft.saved'))==2

def test_append_only_and_atomic_rollback(app):
    s=app.extensions['storage'];key=s.save_snapshot(demo());r=s.snapshot(key)['records'][0]
    with pytest.raises(sqlite3.IntegrityError):
        with s.connect() as db:db.execute('DELETE FROM activity')
    with pytest.raises(sqlite3.IntegrityError):
        with s.connect() as db:db.execute("UPDATE activity SET action='tampered'")
    with s.connect() as db:
        db.execute("CREATE TRIGGER fail_draft BEFORE INSERT ON drafts BEGIN SELECT RAISE(ABORT, 'test'); END")
    before=len(s.activity(limit=100))
    with pytest.raises(sqlite3.IntegrityError):s.save_draft(r['key'],r['fingerprint'],'2','Not committed')
    assert len(s.activity(limit=100))==before

def test_filter_pagination_export_and_ui(app):
    s=app.extensions['storage'];key=s.save_snapshot(demo())
    for i in range(55):s.audit('test.event',key,after={'number':i})
    web=app.test_client()
    page=web.get(f'/activity?workspace={key}&action=test.event')
    assert page.status_code==200 and b'Older activity' in page.data
    rows=s.activity(key,'test.event',limit=50)
    assert len(s.activity(key,'test.event',rows[-1]['id']))==5
    exported=web.get(f'/activity/export?workspace={key}&action=test.event')
    assert len(exported.json)==55
    assert 'attachment' in exported.headers['Content-Disposition']
    assert 'before_json' not in exported.json[0]

def test_rejected_request_does_not_log_credentials(app):
    web=app.test_client()
    web.post('/load',data={'csrf':'PRIVATE_SECRET','CANVAS_TOKEN':'PRIVATE_SECRET'})
    rows=app.extensions['storage'].activity(action='request.rejected')
    assert rows[0]['after']=={'route':'/load','status':403}
    assert 'PRIVATE_SECRET' not in str(rows)
