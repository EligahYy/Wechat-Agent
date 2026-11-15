"""Isolated browser-test app. Never imported by the production factory."""
from contextlib import closing
from pathlib import Path
import tempfile
import httpx

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
    app=create_app(Settings(data_dir=Path(directory.name)),Services(source=FakeSource()))
    class MemoryCredentials:
        def __init__(self):self.values={}
        def get(self,ref):return self.values[ref]
        def set(self,ref,value):self.values[ref]=value
    app.state.services.credential_store=MemoryCredentials()
    app.state.services.model_transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':'{"probe":"ok"}'}}]}))
    app.state.test_directory=directory
    with closing(open_db(app.state.database_path)) as conn:
        migrate(conn)
        seed_case(conn)

    @app.post('/api/__test__/reset')
    def reset():
        with closing(open_db(app.state.database_path)) as conn:
            conn.execute('PRAGMA foreign_keys=OFF')
            tables=[row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'message_search%' AND name!='schema_version'")]
            with conn:
                for table in tables:
                    conn.execute('DELETE FROM "'+table+'"')
            conn.execute('PRAGMA foreign_keys=ON')
            seed_case(conn)
        return {'status':'ok'}
    return app
