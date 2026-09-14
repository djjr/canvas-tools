from fixtures import demo
from storage import Storage


def test_reset_only_removes_demo_drafts(tmp_path):
    storage = Storage(tmp_path / 'db.sqlite')
    key = storage.save_snapshot(demo())
    sample = storage.snapshot(key)['records'][0]
    storage.save_draft(sample['key'], 'old-fingerprint', '1', 'Old demo', True)
    live = demo()
    live['source'] = 'https://school.test'
    live_key = storage.save_snapshot(live)
    record = storage.snapshot(live_key)['records'][0]
    storage.save_draft(record['key'], record['fingerprint'], '2', 'Keep', True)
    storage.update_board(key, '11', 'Reusable')
    assert storage.reset_demo() == key
    assert sample['key'] not in storage.drafts()
    assert storage.drafts()[record['key']]['comment'] == 'Keep'
    assert storage.drafts()[record['key']]['reviewed'] == 1
    assert storage.board(key, '11')[1] == 'Reusable'
    assert storage.activity(key, 'demo.reset')[0]['before'][0]['comment'] == 'Old demo'
