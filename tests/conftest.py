"""Isolated database and API fixtures; real service credentials are never loaded."""

from contextlib import closing
import json
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path):
    from wechat_agent.storage.db import open_db, migrate
    with closing(open_db(tmp_path / "archive.sqlite3")) as conn:
        migrate(conn)
        yield conn


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from wechat_agent.api.app import create_app
    from wechat_agent.config import Settings
    from wechat_agent.services import Services
    with TestClient(create_app(Settings(data_dir=tmp_path), Services(auto_run=False))) as client:
        yield client


@pytest.fixture
def case():
    def load(name):
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("invalid_fixture_name")
        return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())
    return load

@pytest.fixture
def snapshot(db):
    from datetime import datetime,timezone
    from tests.factories import seed_case
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.source.contracts import ContactKey
    seed_case(db)
    return build_snapshot(db,ContactKey(account_id='acct-1',contact_id='merchant-a'),datetime(2027,1,1,tzinfo=timezone.utc))
