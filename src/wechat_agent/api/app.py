"""Application factory; startup prepares storage without querying external services."""

from contextlib import asynccontextmanager, closing
import json
import sqlite3

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..config import Settings
from ..accounts import AccountError, selected_account
from ..contacts.service import ContactError
from ..operations.service import OperationError
from ..operations.worker import WorkerRuntime
from ..services import Services
from ..source.adapter import WXCLIAdapter, SourceError
from ..source.probe import SourceConfig
from ..storage.db import SCHEMA_VERSION, migrate, open_db
from .contacts import router as contacts_router
from .operations import router as operations_router


def create_app(settings: Settings, services: Services | None = None) -> FastAPI:
    database_path = settings.data_dir / "archive.sqlite3"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with closing(open_db(database_path)) as conn:
            migrate(conn)
        if app.state.services.auto_run:
            app.state.worker = WorkerRuntime(database_path, app.state.services,
                lambda conn: selected_account(conn, app.state.settings, app.state.services))
            app.state.worker.start()
        try:
            yield
        finally:
            if app.state.worker:
                await app.state.worker.close()

    app = FastAPI(title="Wechat-Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.services = services if services is not None else Services()
    app.state.database_path = database_path
    app.state.worker = None
    if services is None:
        def source_factory(account_id):
            path = app.state.settings.source_config
            try:
                values = json.loads(path.read_text()) if path else {}
                config = SourceConfig.model_validate(values)
            except (OSError, ValueError, TypeError):
                raise SourceError("source_config_invalid") from None
            if config.expected_account_id and config.expected_account_id != account_id:
                raise SourceError("source_account_mismatch")
            config = config.model_copy(update={"expected_account_id": account_id})
            return WXCLIAdapter(config)
        app.state.services.source_factory = source_factory
    app.include_router(contacts_router)
    app.include_router(operations_router)

    @app.exception_handler(AccountError)
    async def account_error(request, error):
        return JSONResponse(status_code=error.status, content={
            "code": error.code, "message": "工作账号不可用，请检查账号配置", "details": {}})

    @app.exception_handler(OperationError)
    async def operation_error(request, error):
        return JSONResponse(status_code=error.status, content={
            "code": error.code, "message": "操作未完成，请核对当前状态", "details": error.details})

    @app.exception_handler(ContactError)
    async def contact_error(request, error):
        return JSONResponse(status_code=error.status, content={
            "code": error.code, "message": "联系人操作未完成，请检查账号或当前状态", "details": {}})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        fields = []
        for item in error.errors():
            path = list(item["loc"])
            if item["type"] == "extra_forbidden":
                path[-1] = "unknown_field"
            fields.append({"path": path, "type": item["type"]})
        return JSONResponse(status_code=422, content={
            "code": "validation_error", "message": "请检查输入", "details": {"fields": fields}})

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
