"""Original-message scope, immutable import previews, and bounded attachment access."""
from contextlib import closing
import json
from urllib.parse import quote

import pytest
from tests.factories import seed_case, make_message, make_page
from tests.fakes.source import FakeSource
from wechat_agent.storage.db import open_db
from wechat_agent.source.repository import archive_page

@pytest.fixture
def populated(client):
    with closing(open_db(client.app.state.database_path)) as conn:
        seed_case(conn)
    client.app.state.services.source=FakeSource()
    return client

def messages(client, contact='merchant-a', **params):
    return client.get('/api/contacts/'+quote(contact,safe='')+'/messages',params={'account_id':'acct-1',**params})

def test_timeline_preserves_shared_group_speakers_and_is_read_only(populated):
    with closing(open_db(populated.app.state.database_path)) as conn:
        before=conn.total_changes
    response=messages(populated)
    assert response.status_code==200
    result=response.json()
    assert result['total']==4
    assert {row['sender']['contact_id'] for row in result['items']}=={'merchant-a','provider-p','self-1'}
    assert any(row['sender']['is_self'] for row in result['items'])
    assert all(row['body'] for row in result['items'])
    assert len(result['sources'])==2
    with closing(open_db(populated.app.state.database_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==4
        assert conn.execute('SELECT COUNT(*) FROM operations').fetchone()[0]==0

def test_timeline_paging_is_bound_to_scope_and_archive_revision(populated):
    first=messages(populated,page_size=2).json()
    second=messages(populated,page_size=2,cursor=first['next_cursor']).json()
    assert len({m['message_id'] for m in first['items']+second['items']})==4
    assert second['next_cursor'] is None
    assert messages(populated,'merchant-b',page_size=2,cursor=first['next_cursor']).status_code==422
    assert messages(populated,q='海运',page_size=2,cursor=first['next_cursor']).status_code==422
    with closing(open_db(populated.app.state.database_path)) as conn:
        archive_page(conn,make_page([make_message(message_id='new-original',body='海运新消息')]))
    assert messages(populated,page_size=2,cursor=first['next_cursor']).status_code==409

def test_timeline_short_chinese_search_source_filter_and_non_merchant(populated):
    with closing(open_db(populated.app.state.database_path)) as conn:
        archive_page(conn,make_page([make_message(message_id='searchable',body='询问海运价格；100%真实')]))
    found=messages(populated,q='海运').json()
    assert any(row['message_id']=='searchable' for row in found['items'])
    assert messages(populated,q='100%').json()['total']==1
    assert messages(populated,q='not-present').json()['items']==[]
    assert messages(populated,conversation_id='not-related').status_code==404
    assert messages(populated,'provider-p').status_code==200
    assert messages(populated,'not-present').status_code==404
    assert populated.get('/api/contacts/merchant-a/messages',params={'account_id':'another-account'}).status_code==404

def test_attachment_api_refuses_arbitrary_paths_and_unfetched_refs(populated):
    assert populated.get('/api/attachments/..%2F..%2Fetc%2Fpasswd',params={'account_id':'acct-1'}).status_code in (404,422)
    with closing(open_db(populated.app.state.database_path)) as conn:
        archive_page(conn,make_page([make_message(message_id='attachment-original',attachment_ids=['test-attachment'])]))
    response=populated.get('/api/attachments/test-attachment',params={'account_id':'acct-1'})
    assert response.status_code==409
    assert response.json()['details']['state']=='unfetched'

FIELDS={name:name for name in ('conversation_id','sender_id','sent_at','message_id','body')}
def payload(rows=None,**updates):
    rows=rows if rows is not None else [dict(conversation_id='group-1',sender_id='merchant-a',sent_at='2026-11-12T12:00:00+08:00',message_id='external-1',body='导入海运原文')]
    return dict(mode='preview',account_id='acct-1',format='json',namespace='external-batch',mapping=FIELDS,content=json.dumps(rows,ensure_ascii=False),**updates)
def preview(client, rows=None, **updates):
    return client.post('/api/imports',json=payload(rows,**updates))
def commit(client,identifier):
    return client.post('/api/imports',json={'mode':'commit','account_id':'acct-1','preview_id':identifier})

def test_import_requires_json_content_type_before_creating_previews(populated):
    response=populated.post('/api/imports',content=json.dumps(payload()),
        headers={'Content-Type':'text/plain','Origin':'https://untrusted.example'})
    assert response.status_code==415
    with closing(open_db(populated.app.state.database_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM import_previews').fetchone()[0]==0

@pytest.mark.parametrize('field,value', [('body','\ud800'),('unused','\ud800'),('unused',float('inf'))])
def test_import_rejects_invalid_decoded_json_before_inspection_or_storage(populated,field,value):
    rows=json.loads(payload()['content']);rows[0][field]=value
    content=json.dumps(rows,ensure_ascii=True).replace('Infinity','1e999')
    for mapping in (None,FIELDS):
        request=payload();request.update(content=content,mapping=mapping)
        assert populated.post('/api/imports',json=request).status_code==422
    with closing(open_db(populated.app.state.database_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM import_previews').fetchone()[0]==0

def test_import_detects_mixed_conversation_types_in_preview(populated):
    row={**json.loads(payload()['content'])[0],'conversation_id':'new-room','conversation_kind':'group'}
    request=payload([row,{**row,'message_id':'other','conversation_kind':'private'}])
    request['mapping']={**FIELDS,'conversation_kind':'conversation_kind'}
    ready=populated.post('/api/imports',json=request).json()
    assert ready['counts']=={'valid':1,'rejected':1,'new':1,'unchanged':0,'total':2}
    assert ready['issues']==[{'row':2,'code':'conversation_kind_conflict'}]
    assert commit(populated,ready['preview_id']).json()['counts']['inserted']==1

def test_import_rechecks_room_type_at_commit_and_keeps_unrelated_rows(populated):
    row={**json.loads(payload()['content'])[0],'conversation_id':'racing-room','conversation_kind':'group'}
    mapping={**FIELDS,'conversation_kind':'conversation_kind'}
    ready=populated.post('/api/imports',json={**payload([row,{**row,'conversation_id':'safe-room'}]),'mapping':mapping}).json()
    winner=populated.post('/api/imports',json={**payload([{**row,'message_id':'winner','conversation_kind':'private'}]),'mapping':mapping}).json()
    assert commit(populated,winner['preview_id']).status_code==200
    result=commit(populated,ready['preview_id'])
    assert result.status_code==200
    assert result.json()['counts']=={'inserted':1,'unchanged':0,'rejected':1,'total':2}
    assert result.json()['issues']==[{'row':1,'code':'conversation_kind_conflict'}]

def test_import_applies_commit_conflict_to_all_duplicate_rows(populated):
    row=json.loads(payload()['content'])[0]
    ready=preview(populated,[row,row]).json()
    winner=preview(populated,[{**row,'body':'另外一个预览先提交'}]).json()
    assert commit(populated,winner['preview_id']).status_code==200
    result=commit(populated,ready['preview_id']).json()
    assert result['counts']=={'inserted':0,'unchanged':0,'rejected':2,'total':2}
    assert result['issues']==[{'row':1,'code':'message_identity_conflict'},{'row':2,'code':'message_identity_conflict'}]

def test_import_reports_utc_overflow_as_one_bad_row(populated):
    row=json.loads(payload()['content'])[0]
    ready=preview(populated,[{**row,'sent_at':'9999-12-31T23:59:59-01:00'}, {**row,'message_id':'valid'}]).json()
    assert ready['counts']['valid']==1 and ready['counts']['rejected']==1
    assert ready['issues']==[{'row':1,'code':'time_invalid'}]
    assert commit(populated,ready['preview_id']).json()['counts']['inserted']==1

def test_import_preview_then_commit_is_idempotent_and_preserves_sync_state(populated):
    with closing(open_db(populated.app.state.database_path)) as conn:
        cursors=[tuple(row) for row in conn.execute('SELECT * FROM sync_cursors ORDER BY conversation_id')]
    response=preview(populated)
    assert response.status_code==200
    data=response.json(); assert data['counts']['valid']==1
    with closing(open_db(populated.app.state.database_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==4
    done=commit(populated,data['preview_id'])
    assert done.status_code==200 and done.json()['counts']['inserted']==1
    assert commit(populated,data['preview_id']).json()['already_committed'] is True
    assert commit(populated,preview(populated).json()['preview_id']).json()['counts']['unchanged']==1
    with closing(open_db(populated.app.state.database_path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==5
        assert cursors==[tuple(row) for row in conn.execute('SELECT * FROM sync_cursors ORDER BY conversation_id')]
    assert messages(populated,q='导入海运').json()['total']==1

def test_import_reports_bad_rows_and_cannot_override_existing_original(populated):
    rows=json.loads(payload()['content']); rows+=[{**rows[0],'message_id':'bad','sender_id':''},{**rows[0],'message_id':'other','body':'导入海运原文'}]
    data=preview(populated,rows).json()
    assert data['counts']['valid']==2 and data['counts']['rejected']==1
    assert data['issues'][0]['row']==2
    assert commit(populated,data['preview_id']).json()['counts']['inserted']==2
    conflict=preview(populated,[{**rows[0],'body':'不得覆盖原文'}]).json()
    assert conflict['counts']['valid']==0 and conflict['counts']['rejected']==1
    assert conflict['issues'][0]['code']=='message_identity_conflict'
    assert commit(populated,conflict['preview_id']).json()['counts']['inserted']==0
    assert messages(populated,q='不得覆盖').json()['total']==0

def test_import_mapping_account_and_encoding_validation(populated):
    rows=json.loads(payload()['content']); rows[0]['account_id']='another-account'
    data=preview(populated,rows).json()
    assert data['counts']['rejected']==1 and data['issues'][0]['code']=='account_scope_mismatch'
    missing=payload();missing['mapping']={'body':'body'}
    result=populated.post('/api/imports',json=missing)
    assert result.status_code==200 and result.json()['counts']['valid']==0
    bad=payload();bad['content']='\ud800'
    assert populated.post('/api/imports',content=json.dumps(bad).encode(),headers={'Content-Type':'application/json'}).status_code==422
    assert populated.post('/api/imports',json={'mode':'commit','account_id':'another-account','preview_id':'fake'}).status_code==404

def test_import_csv_inspection_mapping_and_commit(populated):
    request=dict(mode='preview',account_id='acct-1',namespace='csv-batch',format='csv',content='room,who,time,id,text\ngroup-1,merchant-a,2026-11-12T12:00:00+08:00,1,海运CSV\n')
    inspected=populated.post('/api/imports',json=request).json()
    assert inspected['columns']==['room','who','time','id','text']
    assert inspected['preview_id'] is None
    request['mapping']=dict(zip(FIELDS,['room','who','time','id','text']))
    ready=populated.post('/api/imports',json=request).json()
    assert ready['counts']['valid']==1
    assert commit(populated,ready['preview_id']).json()['counts']['inserted']==1


def test_attachment_root_allows_only_existing_regular_files_without_symlinks(populated,tmp_path):
    root=populated.app.state.settings.data_dir/'attachments';root.mkdir()
    safe=root/'invoice.txt';safe.write_bytes(b'local original')
    secret=tmp_path/'outside.txt';secret.write_bytes(b'must not be served')
    (root/'link.txt').symlink_to(secret)
    with closing(open_db(populated.app.state.database_path)) as conn:
        archive_page(conn,make_page([make_message(message_id='local-files',attachment_ids=['local-safe','local-link','local-outside'])]))
        with conn:
            for aid,path in [('local-safe',safe),('local-link',root/'link.txt'),('local-outside',secret)]:
                conn.execute("UPDATE attachments SET state='original',local_path=?,mime='text/plain' WHERE attachment_id=?",(str(path),aid))
    response=populated.get('/api/attachments/local-safe',params={'account_id':'acct-1'})
    assert response.status_code==200 and response.content==b'local original'
    assert response.headers['content-disposition'].startswith('attachment;')
    for identifier in ('local-link','local-outside'):
        response=populated.get('/api/attachments/'+identifier,params={'account_id':'acct-1'})
        assert response.status_code==409 and b'must not be served' not in response.content
    assert populated.get('/api/attachments/local-safe',params={'account_id':'another-account'}).status_code==404


def test_import_failure_rolls_back_entire_batch_and_can_be_retried(populated):
    rows=json.loads(payload()['content']);rows.append({**rows[0],'message_id':'second','body':'blocked by fixture'})
    data=preview(populated,rows).json()
    with closing(open_db(populated.app.state.database_path)) as conn,conn:
        conn.execute("CREATE TRIGGER refuse_import BEFORE INSERT ON messages WHEN NEW.body='blocked by fixture' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    assert commit(populated,data['preview_id']).status_code==503
    with closing(open_db(populated.app.state.database_path)) as conn,conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==4
        assert conn.execute("SELECT state FROM import_previews WHERE preview_id=?",(data['preview_id'],)).fetchone()[0]=='ready'
        conn.execute('DROP TRIGGER refuse_import')
    assert commit(populated,data['preview_id']).json()['counts']['inserted']==2


def test_import_duplicate_rows_and_stale_preview_conflict_do_not_revise_messages(populated):
    rows=json.loads(payload()['content'])
    first=preview(populated,rows+rows).json()
    done=commit(populated,first['preview_id']).json()
    assert done['counts']=={'inserted':1,'unchanged':1,'rejected':0,'total':2}
    pending=preview(populated,[{**rows[0],'message_id':'pending'}]).json()
    other=preview(populated,[{**rows[0],'message_id':'pending','body':'already committed original'}]).json()
    assert commit(populated,other['preview_id']).status_code==200
    rejected=commit(populated,pending['preview_id']).json()
    assert rejected['counts']['rejected']==1 and rejected['counts']['inserted']==0
    assert messages(populated,q='already committed').json()['total']==1


def test_timeline_keeps_unassigned_system_events_and_hides_invalid_author_identity(populated):
    with closing(open_db(populated.app.state.database_path)) as conn:
        archive_page(conn,make_page([make_message(message_id='system-event',sender_id=None,kind='system',body='群系统事件')]))
    row=next(item for item in messages(populated).json()['items'] if item['message_id']=='system-event')
    assert row['sender']['contact_id'] is None and row['sender']['display_name']=='系统消息'
    assert messages(populated,q='" OR provider').json()['total']==0
    assert messages(populated,cursor='not-a-cursor').status_code==422


def test_timeline_cursor_detects_newly_related_existing_history(populated):
    with closing(open_db(populated.app.state.database_path)) as conn:
        archive_page(conn,make_page([make_message(message_id='prior-unrelated',conversation_id='prior-room',sender_id='provider-p')],conversation_id='prior-room'))
    first=messages(populated,page_size=2).json()
    with closing(open_db(populated.app.state.database_path)) as conn,conn:
        conn.execute("INSERT INTO members(account_id,conversation_id,contact_id) VALUES('acct-1','prior-room','merchant-a')")
    assert messages(populated,page_size=2,cursor=first['next_cursor']).status_code==409


def test_import_rejects_nonstandard_json_numbers_and_expired_previews(populated):
    request=payload();request['content']=request['content'].replace('"导入海运原文"','NaN')
    assert populated.post('/api/imports',json=request).status_code==422
    ready=preview(populated).json()
    with closing(open_db(populated.app.state.database_path)) as conn,conn:
        conn.execute('UPDATE import_previews SET expires_at=0 WHERE preview_id=?',(ready['preview_id'],))
    assert commit(populated,ready['preview_id']).status_code==409
    request=payload();request['content']='x'*(2*1024*1024+1)
    assert populated.post('/api/imports',json=request).status_code==413


def test_imported_attachment_paths_remain_unfetched_references(populated):
    request=payload();rows=json.loads(request['content']);rows[0]['attachment_ids']=['../../etc/passwd','file:///private/secret']
    request['content']=json.dumps(rows);request['mapping']={**FIELDS,'attachment_ids':'attachment_ids'}
    ready=populated.post('/api/imports',json=request).json()
    assert commit(populated,ready['preview_id']).json()['counts']['inserted']==1
    imported=messages(populated,q='导入海运').json()['items'][0]
    assert len(imported['attachments'])==2
    for attachment in imported['attachments']:
        assert attachment['state']=='unfetched' and not attachment['downloadable']
        assert populated.get('/api/attachments/'+attachment['id'],params={'account_id':'acct-1'}).status_code==409
