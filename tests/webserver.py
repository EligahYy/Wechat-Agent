"""Isolated browser-test app. Never imported by the production factory."""
from contextlib import closing
from pathlib import Path
import tempfile
import httpx
from fastapi import Body

from tests.factories import seed_case as base_seed,make_message,make_page
from datetime import datetime,timezone
from wechat_agent.source.repository import archive_page

def seed_case(conn):
    base_seed(conn)
    # Each unknown synthetic person has their own recent speech, never group heat.
    ids=[row[0] for row in conn.execute("SELECT contact_id FROM contacts WHERE role='unknown' AND is_self=0")]
    archive_page(conn,make_page([make_message(message_id="activity:"+cid,sender_id=cid,sent_at=datetime.now(timezone.utc),conversation_id="activity-room",body="Synthetic group speech") for cid in ids],conversation_id="activity-room",conversation_kind="group"))
from tests.fakes.source import FakeSource
from wechat_agent.api.app import create_app
from wechat_agent.config import Settings
from wechat_agent.services import Services
from wechat_agent.storage.db import open_db,migrate


def app_factory():
    directory=tempfile.TemporaryDirectory(prefix='wechat browser test ')
    class BrowserSource(FakeSource):
        # seed_case adds this synthetic source. It must remain readable during
        # whole-account sync, rather than masquerading as a disappeared group.
        async def conversations(self):
            from wechat_agent.source.contracts import ConversationRecord
            from wechat_agent.storage.db import open_existing_db
            rooms=await super().conversations()
            with closing(open_existing_db(Path(directory.name)/'archive.sqlite3',readonly=True)) as conn:
                row=conn.execute("SELECT title FROM conversations WHERE account_id=? AND conversation_id='activity-room'",(self.account_id,)).fetchone()
                if row:
                    ids=[r[0] for r in conn.execute("SELECT DISTINCT sender_id FROM messages WHERE account_id=? AND conversation_id='activity-room' AND sender_id IS NOT NULL",(self.account_id,))]
                    rooms.append(ConversationRecord(account_id=self.account_id,conversation_id='activity-room',kind='group',title=row[0],membership_state='known',member_ids=ids))
            return rooms
        async def messages(self,conversation_id,cursor,limit):
            if conversation_id!='activity-room':return await super().messages(conversation_id,cursor,limit)
            import json
            from wechat_agent.storage.db import open_existing_db
            self.calls.append((conversation_id,cursor,limit))
            with closing(open_existing_db(Path(directory.name)/'archive.sqlite3',readonly=True)) as conn:
                rows=conn.execute("SELECT * FROM messages WHERE account_id=? AND conversation_id='activity-room'",(self.account_id,)).fetchall()
                records=[make_message(message_id=r['message_id'],conversation_id=conversation_id,sender_id=r['sender_id'],sent_at=datetime.fromisoformat(r['sent_at']),body=r['body'],source_revision=r['source_revision'],raw=json.loads(r['raw_json'])) for r in rows]
            return make_page(records,conversation_id=conversation_id)
    app=create_app(Settings(data_dir=Path(directory.name)),Services(source=BrowserSource()))
    class MemoryCredentials:
        def __init__(self):self.values={}
        def get(self,ref):return self.values[ref]
        def set(self,ref,value):self.values[ref]=value
    app.state.services.credential_store=MemoryCredentials()
    def model_reply(request):
        import json
        content=json.loads(request.content)['messages'][-1]['content']
        if content=='Return {"probe":"ok"}.':answer='{"probe":"ok"}'
        else:
            payload=json.loads(content)
            result=json.loads((Path(__file__).parent/'fixtures/profile-ready.json').read_text())
            result['contact_id']=payload['contact_id']
            answer=json.dumps(result)
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':answer}}]})
    app.state.services.model_transport=httpx.MockTransport(model_reply)
    app.state.test_directory=directory
    with closing(open_db(app.state.database_path)) as conn:
        migrate(conn)
        seed_case(conn)

    @app.post('/api/__test__/reset')
    def reset(body:dict=Body(default={})):
        with closing(open_db(app.state.database_path)) as conn:
            conn.execute('PRAGMA foreign_keys=OFF')
            tables=[row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'message_search%' AND name!='schema_version'")]
            with conn:
                for table in tables:
                    conn.execute('DELETE FROM "'+table+'"')
            conn.execute('PRAGMA foreign_keys=ON')
            seed_case(conn)
            if body.get('case')=='profile-ready':
                from tests.profile_seed import seed_profile
                seed_profile(conn)
        return {'status':'ok'}
    return app
