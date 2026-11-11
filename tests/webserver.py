"""Isolated browser-test app. Never imported by the production factory."""
from contextlib import closing
from pathlib import Path
import tempfile

from tests.factories import seed_case
from tests.fakes.source import FakeSource
from wechat_agent.api.app import create_app
from wechat_agent.config import Settings
from wechat_agent.services import Services
from wechat_agent.storage.db import open_db,migrate


def app_factory():
    directory=tempfile.TemporaryDirectory(prefix='wechat browser test ')
    app=create_app(Settings(data_dir=Path(directory.name)),Services(source=FakeSource()))
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
