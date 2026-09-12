import copy
from unittest.mock import Mock
import pytest
from app import create_app
from canvas_api import CanvasClient, CanvasError
from fixtures import demo
from publishing import Publisher

@pytest.fixture
def setup(tmp_path):
    app=create_app({'TESTING':True,'DATABASE':tmp_path/'db.sqlite','SECRET_KEY':'test'})
    storage=app.extensions['storage']
    data=demo(); data['source']='https://school.test'
    key=storage.save_snapshot(data); data=storage.snapshot(key)
    record=data['records'][0]
    storage.save_draft(record['key'],record['fingerprint'],'3.25','',True)
    client=Mock(); client.base=data['source']
    client.load.side_effect=lambda *args: copy.deepcopy(data)
    def write(course,quiz,submission,attempt,question,score,comment):
        for r in data['records']:
            if (r['submission_id'],r['attempt'],r['question']['id'])==(submission,attempt,question):
                r['score']=float(score);r['grading_status']='graded'
                if comment.strip():r['comment']=comment
    client.publish_question.side_effect=write
    app.config['CANVAS_CLIENT_FACTORY']=lambda:client
    return app,storage,key,data,record,client

def test_preview_is_readonly_and_confirm_is_exact_and_verified(setup):
    app,storage,key,data,r,client=setup
    p=Publisher(storage,client); token=p.preview(key)
    assert len(storage.publish_batch(token)['items'])==1
    client.publish_question.assert_not_called()
    result=p.run(token)
    assert result['items'][0]['status']=='success'
    client.publish_question.assert_called_once_with('101','42',100,1,11,'3.25','')
    draft=storage.drafts()[r['key']]
    assert draft['reviewed']==0
    updated=storage.snapshot(key)['records'][0]
    assert updated['score']==3.25 and updated['comment']=='Thoughtful use of evidence.'
    assert updated['fingerprint']==draft['fingerprint']
    with pytest.raises(CanvasError):p.run(token)
    assert len(storage.publish_batch(p.preview(key))['items'])==0

def test_local_edit_after_preview_blocks_write(setup):
    app,s,key,data,r,c=setup;p=Publisher(s,c);token=p.preview(key)
    s.save_draft(r['key'],r['fingerprint'],'2','changed',True)
    assert p.run(token)['items'][0]['status']=='blocked'
    c.publish_question.assert_not_called()

def test_canvas_edit_after_preview_blocks_write(setup):
    app,s,key,data,r,c=setup;p=Publisher(s,c);token=p.preview(key)
    data['records'][0]['comment']='Changed in Canvas'
    assert p.run(token)['items'][0]['status']=='blocked'
    c.publish_question.assert_not_called()

def test_uncertain_write_is_journaled_and_not_retried(setup):
    app,s,key,data,r,c=setup;p=Publisher(s,c);token=p.preview(key)
    c.publish_question.side_effect=CanvasError('Outcome uncertain')
    assert p.run(token)['items'][0]['status']=='uncertain'
    assert s.drafts()[r['key']]['reviewed']==1
    next_token=p.preview(key)
    assert s.publish_batch(next_token)['items'][0]['status']=='blocked'
    p.run(next_token)
    assert c.publish_question.call_count==1

def test_safe_mode_blocks_preview_and_old_confirmation(setup):
    app,s,key,data,r,c=setup;web=app.test_client();web.get('/')
    with web.session_transaction() as session:headers={'X-CSRF-Token':session['csrf']}
    response=web.post(f'/quiz/{key}/publish-preview',headers=headers)
    assert response.status_code==302
    token=response.location.split('/')[-1]
    assert b'Confirm and send 1 item' in web.get(response.location).data
    web.get('/?safe=1')
    assert web.post(f'/publish/{token}/confirm',data={'confirm':'yes'},headers=headers).status_code==403
    assert web.post(f'/quiz/{key}/publish-preview',headers=headers).status_code==403
    c.publish_question.assert_not_called()

def test_demo_always_blocked_and_confirmation_requires_csrf(setup):
    app,s,key,data,r,c=setup;web=app.test_client();web.get('/')
    with web.session_transaction() as session:headers={'X-CSRF-Token':session['csrf']}
    demo_key=s.save_snapshot(demo())
    assert web.post(f'/quiz/{demo_key}/publish-preview',headers=headers).status_code==403
    token=Publisher(s,c).preview(key)
    assert web.post(f'/publish/{token}/confirm',data={'confirm':'yes'}).status_code==403
    c.publish_question.assert_not_called()

def test_wire_payload_uses_quiz_submission_id_and_omits_blank_comment():
    session=Mock();session.put.return_value.status_code=200
    client=CanvasClient('https://school.test','SECRET',session)
    client.publish_question('1','2',345,2,678,'3.25','')
    call=session.put.call_args
    assert call.args[0]=='https://school.test/api/v1/courses/1/quizzes/2/submissions/345'
    assert call.kwargs['json']=={'quiz_submissions':[{'attempt':2,'questions':{'678':{'score':3.25}}}]}
    assert call.kwargs['allow_redirects'] is False
    client.publish_question('1','2',345,2,678,'3.25','Specific feedback')
    assert session.put.call_args.kwargs['json']['quiz_submissions'][0]['questions']['678']['comment']=='Specific feedback'

def test_reconcile_verifies_without_resending(setup):
    app,s,key,data,r,c=setup;p=Publisher(s,c);token=p.preview(key)
    original=c.publish_question.side_effect
    def applied_but_timeout(*args):
        original(*args)
        raise CanvasError('Timed out')
    c.publish_question.side_effect=applied_but_timeout
    assert p.run(token)['items'][0]['status']=='uncertain'
    assert p.reconcile(token)['items'][0]['status']=='success'
    assert c.publish_question.call_count==1
    assert s.drafts()[r['key']]['reviewed']==0

def test_partial_results_keep_success_and_continue_after_conflict(setup):
    app,s,key,data,r,c=setup
    other=data['records'][1]
    s.save_draft(other['key'],other['fingerprint'],'2.5','Second feedback',True)
    p=Publisher(s,c);token=p.preview(key)
    data['records'][0]['answer']='Externally changed'
    result=p.run(token)
    assert [i['status'] for i in result['items']]==['blocked','success']
    assert c.publish_question.call_count==1
    assert s.drafts()[r['key']]['reviewed']==1
    assert s.drafts()[other['key']]['reviewed']==0

def test_environment_safe_mode_cannot_be_disabled_by_url(setup,monkeypatch):
    app,s,key,data,r,c=setup;monkeypatch.setenv('CANVAS_SAFE_MODE','1')
    web=app.test_client();web.get('/?safe=0')
    with web.session_transaction() as session:headers={'X-CSRF-Token':session['csrf']}
    assert web.post(f'/quiz/{key}/publish-preview?safe=0',headers=headers).status_code==403
    c.publish_question.assert_not_called()
