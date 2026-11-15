from tests.test_contacts import archive,contacts_client,fetch

def update(client,ids,included=False,version=0,account='acct-1'):
    return client.patch('/api/contacts/scope',json={'account_id':account,'included':included,'items':[{'key':{'account_id':account,'contact_id':cid},'expected_version':version} for cid in ids]})

def test_scope_roundtrip_and_partial_versions(contacts_client):
    c=contacts_client
    assert update(c,['merchant-a']).status_code==200
    assert fetch(c,scope='business',q='商家甲').json()['total']==0
    rows=fetch(c,scope='all',q='商家甲').json()
    assert rows['items'][0]['business_scope']['version']==1
    assert fetch(c,membership='excluded',q='商家甲').json()['total']==1
    result=update(c,['merchant-a','merchant-b'],True).json()
    assert len(result['details']['updated'])==len(result['details']['failed'])==1
    assert update(c,['merchant-a'],True,1).status_code==200
    assert fetch(c,scope='business',q='商家甲').json()['total']==1

def test_scope_rejects_foreign_and_duplicate_batch_before_write(contacts_client):
    c=contacts_client
    assert update(c,['merchant-a','merchant-a']).status_code==422
    assert update(c,['merchant-a'],account='acct-other').status_code==403
    assert fetch(c,scope='invalid').status_code==422
    assert fetch(c,q='商家甲').json()['items'][0]['business_scope']['version']==0
