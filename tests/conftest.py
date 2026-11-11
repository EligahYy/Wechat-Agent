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
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        yield client


@pytest.fixture
def case():
    def load(name):
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("invalid_fixture_name")
        return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())
    return load
