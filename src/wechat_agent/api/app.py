"""Application factory; startup prepares storage without querying external services."""

from contextlib import asynccontextmanager, closing
import sqlite3

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..config import Settings
from ..services import Services
from ..storage.db import SCHEMA_VERSION, migrate, open_db


def create_app(settings: Settings, services: Services | None = None) -> FastAPI:
    database_path = settings.data_dir / "archive.sqlite3"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with closing(open_db(database_path)) as conn:
            migrate(conn)
        yield

    app = FastAPI(title="Wechat-Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.services = services if services is not None else Services()
    app.state.database_path = database_path

    @app.get("/api/health")
    def health():
        # Each sync handler opens and closes its connection on the same thread.
        try:
            with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
                row = conn.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone()
            version = row[0] if row else None
        except sqlite3.Error:
            return JSONResponse(status_code=503, content={
                "code": "database_unavailable", "message": "本地数据库不可用", "details": {}})
        if version != SCHEMA_VERSION:
            return JSONResponse(status_code=503, content={
                "code": "database_schema_mismatch", "message": "数据库版本不匹配", "details": {}})
        return {"status": "ok", "schema_version": version}

    return app


def app_factory() -> FastAPI:
    return create_app(Settings.load())
