import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import services
from .analysis import Blocked, call_model, context
from .collector import Collector, SourceError
from .config import Settings
from .db import DB, now, uid
from .ingestion import enqueue, ingest


def create_app(settings=None, source_factory=None, background=False):
    db = DB(settings or Settings())
    page_paths = {"/", "/workspace", "/workspace/", "/legacy", "/legacy/"}

    @asynccontextmanager
    async def lifespan(app):
        runtime = None
        if background:
            from .runtime import Runtime

            runtime = Runtime(db, source_factory or Collector)
            runtime.start()
        app.state.background = background
        yield
        if runtime:
            await run_in_threadpool(runtime.close)

    app = FastAPI(
        title="Wechat-Agent",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.db = db
    source_factory = source_factory or Collector
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(),
    )

    @app.middleware("http")
    async def security(request, call_next):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"error": "invalid_host"}, 400)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"error": "invalid_origin"}, 403)
        # Top-level navigation is valid for each HTML entry, including history
        # URLs restored/reloaded after opening the app from an external link.
        # Never extend this exception to API reads, embeds or mutations.
        entry_navigation = (
            request.method == "GET"
            and request.url.path in page_paths
            and request.headers.get("sec-fetch-mode") == "navigate"
            and request.headers.get("sec-fetch-dest") == "document"
        )
        if (
            request.headers.get("sec-fetch-site") == "cross-site"
            and not entry_navigation
        ):
            return JSONResponse({"error": "cross_site"}, 403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 2_000_000):
                return JSONResponse({"error": "request_too_large"}, 413)
            if "application/json" not in request.headers.get("content-type", ""):
                return JSONResponse({"error": "json_required"}, 415)
            raw = await request.body()
            if len(raw) > 2_000_000:
                return JSONResponse({"error": "request_too_large"}, 413)
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                return JSONResponse({"error": "JSON 对象无效"}, 422)
        current_token = db.token
        csrf = hashlib.sha256(("csrf:" + current_token).encode()).hexdigest()
        request.state.csrf = csrf
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        token = bearer or request.cookies.get("wa_session", "")
        authenticated = bool(token) and hmac.compare_digest(token, current_token)
        public_page = request.method == "GET" and request.url.path in page_paths
        if request.url.path != "/login" and not public_page and not authenticated:
            return JSONResponse({"error": "请登录本地会话"}, 401)
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.url.path != "/login"
        ):
            if not authenticated or (
                not bearer
                and not hmac.compare_digest(
                    request.headers.get("x-csrf-token", ""), csrf
                )
            ):
                return JSONResponse({"error": "csrf_or_auth"}, 403)
        request.state.authenticated = authenticated
        request.state.nonce = secrets.token_urlsafe(20)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'nonce-{request.state.nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        if isinstance(exc, Blocked):
            message = exc.status
        elif isinstance(exc, ValidationError):
            message = "输入字段校验失败：" + ", ".join(
                ".".join(map(str, e["loc"])) for e in exc.errors()
            )
        else:
            message = str(exc)
        return JSONResponse(
            {"error": message}, 409 if isinstance(exc, services.Conflict) else 422
        )

    @app.exception_handler(httpx.HTTPError)
    async def remote_error(request, exc):
        return JSONResponse(
            {"error": "接口请求未完成，请检查服务连接、模型权限或稍后重试"}, 502
        )

    @app.exception_handler(KeyError)
    async def missing_field(request, exc):
        return JSONResponse({"error": "缺少必填字段"}, 422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity(request, exc):
        return JSONResponse({"error": "关联不存在或记录重复，请核对输入"}, 422)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return render_page(request, "workspace.html")

    def render_page(request, template):
        return env.get_template(
            template if request.state.authenticated else "login.html"
        ).render(
            csrf=request.state.csrf if request.state.authenticated else "",
            nonce=request.state.nonce,
        )

    @app.get("/legacy", response_class=HTMLResponse)
    def legacy_workspace(request: Request):
        return render_page(request, "dashboard.html")

    @app.get("/workspace", response_class=HTMLResponse)
    def workspace(request: Request):
        return render_page(request, "workspace.html")

    @app.get("/api/workspace/runs")
    def workspace_runs():
        return db.rows(
            "SELECT id,status,calls,error,created_at FROM workspace_runs WHERE account_id=? ORDER BY created_at DESC LIMIT 20",
            (db.settings.source_account,),
        )

    @app.get("/api/workspace/scans")
    def workspace_scans():
        return db.rows(
            "SELECT s.source_id,s.status,s.phase,s.total_pages,s.completed_pages,s.source_messages,s.processed_messages,s.error,s.updated_at,COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),s.source_id) name FROM workspace_scans s LEFT JOIN identity_metadata i ON i.account_id=s.account_id AND i.source_id=s.source_id WHERE s.account_id=? AND NOT EXISTS(SELECT 1 FROM effective_actor_exclusions e WHERE e.account_id=s.account_id AND e.source_id=s.source_id) ORDER BY s.updated_at DESC",
            (db.settings.source_account,),
        )

    @app.get("/api/workspace/progress")
    def workspace_progress(page: int = 1):
        from .workspace.queue import progress

        return progress(db, page, background=background)

    @app.get("/api/workspace/dashboard")
    def workspace_dashboard(
        q: str = "",
        selected: str = "all",
        page: int = 1,
        followup: str = "all",
        followup_page: int = 1,
    ):
        from .workspace.dashboard import snapshot

        return snapshot(db, q, selected, page, followup, followup_page, background)

    @app.get("/api/workspace/whitelist")
    def workspace_whitelist(
        entity: str = "people", q: str = "", scope: str = "archive", page: int = 1
    ):
        from .workspace.whitelist import listing

        return listing(db, entity, q, scope, page)

    @app.post("/api/workspace/whitelist")
    async def workspace_whitelist_change(request: Request):
        from .workspace.whitelist import change

        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("workspace_invalid_control")
        return await run_in_threadpool(
            change, db, body.get("entity"), body.get("id"), body.get("excluded")
        )

    async def dispatch_workspace_job(request, action=None):
        from .workspace.queue import command

        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("workspace_invalid_control")
        return await run_in_threadpool(
            command,
            db,
            body.get("source_id"),
            action or body.get("action"),
            background=background,
        )

    @app.post("/api/workspace/jobs/command")
    async def workspace_job_command(request: Request):
        return await dispatch_workspace_job(request)

    @app.post("/api/workspace/progress/control")
    async def workspace_progress_control(request: Request):
        return await dispatch_workspace_job(request)

    @app.get("/api/workspace/sources")
    def workspace_sources(
        source_id: str, page: int = 1, order: str = "oldest", q: str = ""
    ):
        from .workspace.views import sources

        return sources(db, source_id, page, order, q)

    @app.get("/api/workspace/packets")
    def workspace_packets(source_id: str, page: int = 1):
        from .workspace.views import packets

        return packets(db, source_id, page)

    @app.get("/api/workspace/queue")
    def workspace_queue(page: int = 1):
        from .workspace.queue import report

        return report(db, page, background=background)

    @app.post("/api/workspace/automation")
    async def workspace_automation(request: Request):
        from .workspace.queue import configure

        body = await request.json()
        return await run_in_threadpool(configure, db, body.get("enabled"))

    @app.post("/api/workspace/queue/refresh")
    async def workspace_queue_refresh():
        from .workspace.queue import reconcile, report

        await run_in_threadpool(reconcile, db)
        return report(db)

    @app.post("/api/workspace/queue/retry")
    async def workspace_queue_retry(request: Request):
        return await dispatch_workspace_job(request, "retry")

    @app.get("/api/workspace/candidates")
    def workspace_candidates(q: str = "", page: int = 1):
        from .workspace.views import candidates

        return candidates(db, q, page)

    @app.get("/api/workspace/documents")
    def workspace_documents():
        from .workspace.views import listing

        return listing(db, compact=True)

    @app.get("/api/workspace/customer")
    def workspace_customer(source_id: str):
        from .workspace.views import details

        return details(db, source_id)

    @app.get("/api/workspace/settings")
    def workspace_settings():
        from .workspace.presentation import settings

        return settings(db, background)

    @app.get("/api/workspace/journal")
    def workspace_journal(source_id: str, page: int = 1):
        from .workspace.presentation import journal

        return journal(db, source_id, page)

    @app.get("/api/workspace/history")
    def workspace_history(source_id: str):
        from .workspace.presentation import history

        return history(db, source_id)

    @app.post("/api/workspace/draft")
    async def workspace_draft(request: Request):
        from .workspace.drafts import generate

        body = await request.json()
        if (
            not isinstance(body.get("source_id"), str)
            or not isinstance(body.get("action_id"), str)
            or type(body.get("version")) is not int
        ):
            raise ValueError("workspace_invalid_command")
        return await run_in_threadpool(
            generate, db, body["source_id"], body["action_id"], body["version"]
        )

    @app.get("/api/workspace/images/{mid}")
    def workspace_image(mid: str, refresh: bool = False):
        from .media import local_image
        from .workspace.ocr import message

        message(db, mid)
        result = local_image(db, mid, source_factory, refresh=refresh)
        return Response(
            result["bytes"],
            media_type=result["mime"],
            headers={"X-Wechat-Media-Quality": result["quality"]},
        )

    @app.get("/api/workspace/images/{mid}/text")
    def workspace_image_text(mid: str):
        from .workspace.ocr import state

        return state(db, mid)

    @app.post("/api/workspace/images/{mid}/recognize")
    async def workspace_recognize(mid: str):
        from .workspace.ocr import candidate

        return await run_in_threadpool(candidate, db, mid, source_factory)

    @app.post("/api/workspace/images/{mid}/text")
    async def workspace_verify_text(mid: str, request: Request):
        from .workspace.ocr import confirm

        body = await request.json()
        return await run_in_threadpool(
            confirm, db, mid, body.get("version"), body.get("text"), source_factory
        )

    @app.post("/api/workspace/analyze")
    async def workspace_analyze(request: Request):
        return await dispatch_workspace_job(request, "start")

    @app.post("/api/workspace/command")
    async def workspace_command(request: Request):
        from .workspace.store import command

        body = await request.json()
        return command(
            db,
            body.get("source_id"),
            body.get("version"),
            body.get("operation"),
            body.get("target"),
            body.get("value"),
        )

    @app.post("/login")
    async def login(request: Request):
        body = await request.json()
        value = body.get("token", "")
        if not isinstance(value, str) or not hmac.compare_digest(value, db.token):
            raise HTTPException(401, "本地登录口令不正确")
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "wa_session", db.token, httponly=True, samesite="strict", path="/"
        )
        return response

    @app.get("/health")
    def health():
        return {
            "database": "ok",
            "schema": db.rows("PRAGMA user_version")[0]["user_version"],
            "runtime": db.rows("SELECT * FROM runtime"),
            "gaps": db.rows("SELECT COUNT(*) n FROM sync_windows WHERE status='gap'")[
                0
            ]["n"],
            "model": "not_live_verified",
        }

    @app.get("/api/state")
    def state():
        return {
            **{
                table: db.rows(
                    f"SELECT * FROM {table}"
                    + (
                        " ORDER BY rowid DESC LIMIT 100"
                        if table == "conversations"
                        else ""
                    )
                )
                for table in (
                    "merchants",
                    "providers",
                    "projects",
                    "conversations",
                    "tasks",
                    "materials",
                    "quotes",
                    "milestones",
                    "touchpoints",
                    "contact_roles",
                    "runtime",
                )
            },
            "suggestions": [
                dict(x, payload=json.loads(x["payload"]))
                for x in db.rows(
                    "SELECT * FROM suggestions ORDER BY created_at DESC LIMIT 100"
                )
            ],
            "jobs": db.rows(
                "SELECT id,status,attempts,error,created_at FROM jobs ORDER BY created_at DESC LIMIT 50"
            ),
            "sync": db.rows(
                "SELECT * FROM sync_windows ORDER BY created_at DESC LIMIT 30"
            ),
            "usage": db.rows(
                "SELECT day,SUM(COALESCE(actual,reserved)) tokens,COUNT(*) calls FROM usage GROUP BY day"
            ),
            "conversation_totals": db.rows(
                "SELECT source,COUNT(*) n FROM conversations GROUP BY source"
            ),
            "activation": services.activation(db),
        }

    def source_operation(operation):
        source = source_factory(db)
        try:
            return operation(source)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise SourceError(
                    "采集服务需要认证。请在本机配置 WX_SOURCE_TOKEN 并重启应用。"
                ) from None
            raise SourceError(
                "采集接口返回错误，请核对 wx-cli 版本与服务日志。"
            ) from None
        except httpx.TransportError:
            raise SourceError(
                "未连接到本机微信采集服务。请先安装并启动 wx-cli（默认 9100 端口）。"
            ) from None
        except (KeyError, TypeError):
            raise SourceError("采集接口结构不兼容，请核对 wx-cli 版本。") from None
        finally:
            source.client.close()

    @app.post("/api/source/probe")
    def source_probe():
        return source_operation(lambda source: source.probe())

    @app.post("/api/source/bind")
    async def source_bind(request: Request):
        b = await request.json()

        def bind(source):
            account = source.probe()
            if account["account_id"] != b["account_id"]:
                raise SourceError("当前微信账号已变化，请重新检测并确认")
            db.settings.bind_source(account["account_id"], account.get("account_name"))
            with db.tx() as c:
                db.event(c, account["account_id"], "source_bound", {})
            return {"ok": True, "account_id": account["account_id"]}

        return await run_in_threadpool(source_operation, bind)

    @app.post("/api/source/groups")
    async def source_groups(request: Request):
        b = await request.json()
        return await run_in_threadpool(
            source_operation, lambda source: source.groups(b.get("offset", 0))
        )

    @app.post("/api/source/pilot")
    async def source_pilot(request: Request):
        b = await request.json()
        groups = b.get("groups")
        if not isinstance(groups, list) or not 1 <= len(groups) <= 2:
            raise ValueError("试采集请选择 1–2 个群")
        ids = [g.get("source_id") for g in groups if isinstance(g, dict)]
        if (
            len(ids) != len(groups)
            or any(not isinstance(x, str) or not x.endswith("@chatroom") for x in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("必须选择不同的精确群 ID")

        # Validate all project associations before changing any white-list policy.
        for group in groups:
            if not isinstance(group.get("title", ""), str):
                raise ValueError("群名称必须为文本")
            merchant, project = (
                group.get("merchant_id") or None,
                group.get("project_id") or None,
            )
            if merchant and (
                not isinstance(merchant, str)
                or not db.rows("SELECT id FROM merchants WHERE id=?", (merchant,))
            ):
                raise ValueError("关联商家不存在")
            if project and (
                not isinstance(project, str)
                or not db.rows(
                    "SELECT id FROM projects WHERE id=? AND merchant_id=?",
                    (project, merchant),
                )
            ):
                raise ValueError("关联项目与商家不匹配")

        # One-shot pilot never archives unrelated allowlisted conversations.
        def pilot(source):
            source.validate()
            chats = []
            for group in groups:
                existing = db.rows(
                    "SELECT * FROM conversations WHERE source='wx_cli' AND account_id=? AND source_id=?",
                    (db.settings.source_account, group["source_id"]),
                )
                merchant_id = group.get("merchant_id") or None
                project_id = group.get("project_id") or None
                if not merchant_id and existing:
                    merchant_id, project_id = (
                        existing[0]["merchant_id"],
                        existing[0]["project_id"],
                    )
                cid = services.allow_conversation(
                    db,
                    "wx_cli",
                    db.settings.source_account,
                    group["source_id"],
                    group.get("title") or group["source_id"],
                    "group",
                    merchant_id,
                    project_id,
                    False,
                )
                chats.append(
                    db.rows("SELECT * FROM conversations WHERE id=?", (cid,))[0]
                )
            end = int(datetime.now(UTC).timestamp())
            results = []
            for chat in chats:
                result = source.sync_window(chat, end - 900, end)
                messages = db.rows(
                    "SELECT COUNT(*) n FROM messages WHERE conversation_id=?",
                    (chat["id"],),
                )[0]["n"]
                results.append(
                    {
                        "conversation_id": chat["id"],
                        "title": chat["title"],
                        "message_count": messages,
                        **result,
                    }
                )
            return {"results": results, "egress": False, "window_minutes": 15}

        return await run_in_threadpool(source_operation, pilot)

    @app.post("/api/conversations/{cid}/pause")
    def pause_conversation(cid: str):
        with db.tx() as c:
            if not c.execute(
                "UPDATE conversations SET allowlisted=0,egress=0 WHERE id=?", (cid,)
            ).rowcount:
                raise ValueError("会话不存在")
            c.execute(
                "UPDATE suggestions SET status='stale' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE json_extract(payload,'$.conversation_id')=?)",
                (cid,),
            )
            db.event(c, cid, "collection_paused", {})
        return {"ok": True}

    @app.get("/api/archive/status")
    def archive_status():
        from .archive import status_report

        return status_report(db)

    @app.get("/api/archive/conversations")
    def archive_conversations(q: str = "", kind: str = "all", page: int = 1):
        if (
            kind not in {"all", "group", "private"}
            or not 1 <= page <= 100000
            or len(q) > 200
        ):
            raise ValueError("查询参数无效")
        where = "source IN ('wx_cli','manual') AND account_id=?"
        args = [db.settings.source_account]
        if kind != "all":
            where += " AND kind=?"
            args.append(kind)
        if q:
            where += " AND (instr(title,?)>0 OR instr(source_id,?)>0)"
            args.extend([q, q])
        total = db.rows("SELECT COUNT(*) n FROM conversations WHERE " + where, args)[0][
            "n"
        ]
        rows = db.rows(
            "SELECT c.*,(SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) message_count FROM conversations c WHERE "
            + where
            + " ORDER BY title,id LIMIT 50 OFFSET ?",
            [*args, (page - 1) * 50],
        )
        return {
            "items": rows,
            "total": total,
            "page": page,
            "has_more": page * 50 < total,
        }

    @app.post("/api/imports/file")
    async def import_message_file(request: Request):
        from .file_import import import_file

        body = await request.json()
        if not isinstance(body.get("text"), str) or not isinstance(
            body.get("filename"), str
        ):
            raise ValueError("请选择文件")
        return await run_in_threadpool(
            import_file,
            db,
            body["text"],
            body["filename"],
            body.get("account_id") or db.settings.source_account or None,
            body.get("write") is True,
        )

    @app.get("/api/customers")
    def customer_list(q: str = "", page: int = 1):
        if len(q) > 200 or not 1 <= page <= 100000:
            raise ValueError("无效查询")
        account = db.settings.source_account
        rows = db.rows(
            "SELECT c.source_id identity,c.title display_name FROM conversations c WHERE c.source IN ('wx_cli','manual') AND c.account_id=? AND c.kind='private' UNION SELECT m.sender_id identity,m.sender_id display_name FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.source IN ('wx_cli','manual') AND c.account_id=? AND m.direction='incoming' AND m.sender_id NOT IN ('unknown',?)",
            (account, account, account),
        )
        people = {}
        for row in rows:
            key = row["identity"]
            if key == account:
                continue
            previous = people.get(key)
            if not previous or row["display_name"] != key:
                people[key] = row
        found = [
            r
            for r in people.values()
            if q.lower() in (r["identity"] + " " + r["display_name"]).lower()
        ]
        found.sort(key=lambda r: r["display_name"])
        return {
            "items": found[(page - 1) * 50 : page * 50],
            "total": len(found),
            "has_more": page * 50 < len(found),
        }

    @app.get("/api/customers/{identity}/timeline")
    def customer_timeline(identity: str):
        account = db.settings.source_account
        return db.rows(
            "SELECT m.*,c.title conversation_title,c.kind conversation_kind FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.source IN ('wx_cli','manual') AND c.account_id=? AND (m.sender_id=? OR (c.kind='private' AND c.source_id=?)) ORDER BY m.event_time DESC LIMIT 100",
            (account, identity, identity),
        )

    @app.get("/api/messages/{cid}")
    def messages(cid: str, page: int = 1):
        from .message_value import classify

        if not 1 <= page <= 100000:
            raise ValueError("页码无效")
        return [
            r | classify(r)
            for r in db.rows(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY event_time DESC,id DESC LIMIT 100 OFFSET ?",
                (cid, (page - 1) * 100),
            )
        ]

    @app.get("/api/messages/{mid}/image")
    def message_image(mid: str):
        from .media import local_image

        image = local_image(db, mid, source_factory)
        return Response(
            image["bytes"],
            media_type=image["mime"],
            headers={"X-Wechat-Media-Quality": image["quality"]},
        )

    @app.post("/api/merchants")
    async def merchant(request: Request):
        b = await request.json()
        return {"id": services.create_merchant(db, b["name"])}

    @app.post("/api/merchants/{mid}/preferences")
    async def preference(mid: str, request: Request):
        b = await request.json()
        if not isinstance(b.get("do_not_contact"), bool):
            raise ValueError("do_not_contact 必须为布尔值")
        with db.tx() as c:
            if not c.execute(
                "UPDATE merchants SET do_not_contact=? WHERE id=?",
                (int(b["do_not_contact"]), mid),
            ).rowcount:
                raise ValueError("商家不存在")
            db.event(c, mid, "contact_preference", b)
        return {"ok": True}

    @app.post("/api/providers")
    async def provider(request: Request):
        b = await request.json()
        pid = uid()
        if not b.get("name", "").strip():
            raise ValueError("服务商名称不能为空")
        with db.tx() as c:
            c.execute(
                "INSERT INTO providers VALUES(?,?,?)",
                (pid, b["name"], b.get("capabilities", "")),
            )
        return {"id": pid}

    @app.post("/api/projects")
    async def project(request: Request):
        b = await request.json()
        return {
            "id": services.create_project(
                db, b["merchant_id"], b["name"], b.get("market", "")
            )
        }

    @app.post("/api/projects/{pid}/transition")
    async def stage(pid: str, request: Request):
        b = await request.json()
        services.project_stage(db, pid, b["stage"], b["version"])
        return {"ok": True}

    @app.post("/api/conversations")
    async def conversation(request: Request):
        b = await request.json()
        return {
            "id": services.allow_conversation(
                db,
                b["source"],
                b["account_id"],
                b["source_id"],
                b.get("title", b["source_id"]),
                b["kind"],
                b.get("merchant_id") or None,
                b.get("project_id") or None,
                b.get("egress") is True,
            )
        }

    @app.post("/api/roles")
    async def roles(request: Request):
        b = await request.json()
        if b.get("role") not in {
            "self",
            "merchant",
            "service_provider",
            "other",
            "unknown",
        } or not b.get("sender_id"):
            raise ValueError("角色配置无效")
        with db.tx() as c:
            c.execute(
                "INSERT INTO contact_roles VALUES(?,?,?,?) ON CONFLICT(conversation_id,sender_id) DO UPDATE SET role=excluded.role,display_name=excluded.display_name",
                (
                    b["conversation_id"],
                    b["sender_id"],
                    b["role"],
                    b.get("display_name", ""),
                ),
            )
            c.execute(
                "UPDATE suggestions SET status='stale' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE json_extract(payload,'$.conversation_id')=?)",
                (b["conversation_id"],),
            )
            # Role changes intentionally permit a fresh analysis by versioning its key.
            db.event(
                c,
                b["conversation_id"],
                "role_changed",
                {"sender_id": b["sender_id"], "role": b["role"]},
            )
            enqueue(c, b["conversation_id"])
        return {"ok": True}

    @app.post("/api/imports")
    async def imports(request: Request):
        b = await request.json()
        return ingest(db, b["records"], b.get("preview", False))

    @app.post("/api/suggestions/{sid}/accept")
    def accept(sid: str):
        return {"id": services.accept(db, sid)}

    @app.post("/api/suggestions/{sid}/dismiss")
    def dismiss(sid: str):
        with db.tx() as c:
            if not c.execute(
                "UPDATE suggestions SET status='dismissed' WHERE id=? AND status='pending'",
                (sid,),
            ).rowcount:
                raise services.Conflict("建议不存在或已处理")
            db.event(c, sid, "suggestion_dismissed", {})
        return {"ok": True}

    @app.post("/api/tasks")
    async def manual_task(request: Request):
        b = await request.json()
        tid = uid()
        if (
            b.get("party")
            not in {"self", "merchant", "service_provider", "other", "unknown"}
            or not b.get("summary", "").strip()
        ):
            raise ValueError("任务内容或责任方无效")
        pid = b.get("project_id") or None
        with db.tx() as c:
            if (
                pid
                and not c.execute(
                    "SELECT 1 FROM projects WHERE id=? AND merchant_id=?",
                    (pid, b["merchant_id"]),
                ).fetchone()
            ):
                raise ValueError("项目归属不匹配")
            c.execute(
                "INSERT INTO tasks(id,merchant_id,project_id,summary,party,created_at) VALUES(?,?,?,?,?,?)",
                (tid, b["merchant_id"], pid, b["summary"], b["party"], now()),
            )
            db.event(c, tid, "manual_task", {"summary": b["summary"]})
        return {"id": tid}

    @app.post("/api/tasks/{tid}/transition")
    async def task(tid: str, request: Request):
        b = await request.json()
        services.transition_task(db, tid, b["state"], b["version"], b.get("due_at"))
        return {"ok": True}

    @app.post("/api/touchpoints")
    async def touched(request: Request):
        b = await request.json()
        tid = uid()
        pid = b.get("project_id") or None
        if not b.get("outcome", "").strip():
            raise ValueError("请填写人工联系结果")
        with db.tx() as c:
            if (
                pid
                and not c.execute(
                    "SELECT 1 FROM projects WHERE id=? AND merchant_id=?",
                    (pid, b["merchant_id"]),
                ).fetchone()
            ):
                raise ValueError("项目归属不匹配")
            c.execute(
                "INSERT INTO touchpoints VALUES(?,?,?,?,?)",
                (tid, b["merchant_id"], pid, b["outcome"], now()),
            )
            db.event(c, tid, "contact_confirmed", {"merchant_id": b["merchant_id"]})
        return {"id": tid}

    @app.post("/api/materials")
    async def material(request: Request):
        b = await request.json()
        mid = uid()
        if b.get("scope") not in {"internal", "external"} or b.get("status") not in {
            "pending",
            "approved",
            "withdrawn",
        }:
            raise ValueError("无效素材范围或状态")
        valid = b.get("valid_until") or None
        if valid:
            dt = datetime.fromisoformat(valid)
            if dt.utcoffset() is None:
                raise ValueError("素材有效期必须含时区")
            valid = dt.astimezone(UTC).isoformat()
        with db.tx() as c:
            c.execute(
                "INSERT INTO materials VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    mid,
                    b["name"],
                    b["version"],
                    b["market"],
                    b.get("kind", "rate_card"),
                    b["terms"],
                    b["scope"],
                    valid,
                    b["status"],
                    now(),
                ),
            )
        return {"id": mid}

    @app.post("/api/materials/{mid}/withdraw")
    def withdraw(mid: str):
        with db.tx() as c:
            c.execute("UPDATE materials SET status='withdrawn' WHERE id=?", (mid,))
            db.event(c, mid, "withdraw_material", {})
        return {"ok": True}

    @app.post("/api/quotes")
    async def quote(request: Request):
        b = await request.json()
        qid = uid()
        material = b.get("material_id") or None
        if not b.get("terms", "").strip():
            raise ValueError("需填写本批具体报价条件")
        with db.tx() as c:
            if material:
                m = c.execute(
                    "SELECT * FROM materials WHERE id=?", (material,)
                ).fetchone()
                if not m or not services.material_usable(m):
                    raise ValueError("素材未审核、过期或禁止对外使用")
            c.execute(
                "INSERT INTO quotes VALUES(?,?,?,?,?,?,?)",
                (
                    qid,
                    b["project_id"],
                    b["provider_id"],
                    material,
                    b["terms"],
                    int(b.get("confirmed") is True),
                    now(),
                ),
            )
            db.event(c, qid, "quote_snapshot", {"project_id": b["project_id"]})
        return {"id": qid}

    @app.post("/api/milestones")
    async def milestone(request: Request):
        b = await request.json()
        mid = uid()
        if b.get("evidence_type") not in {
            "chat_report",
            "document",
            "platform_record",
            "manual_verification",
        }:
            raise ValueError("证据类型无效")
        if b.get("verified") and (
            b["evidence_type"] == "chat_report" or not b.get("note", "").strip()
        ):
            raise ValueError("聊天反馈不等于核验；请填写核验口径")
        for field in ("planned_at", "actual_at"):
            if b.get(field):
                dt = datetime.fromisoformat(b[field])
                if dt.utcoffset() is None:
                    raise ValueError("时间必须含时区")
        with db.tx() as c:
            c.execute(
                "INSERT INTO milestones VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    mid,
                    b["project_id"],
                    b["kind"],
                    b.get("planned_at") or None,
                    b.get("actual_at") or None,
                    b["evidence_type"],
                    b.get("note", ""),
                    int(b.get("verified") is True),
                    now(),
                ),
            )
        return {"id": mid}

    @app.post("/api/analysis/{cid}/preview")
    def preview(cid: str):
        _, _, payload, fingerprint = context(db, cid)
        return {
            "payload": payload,
            "fingerprint": fingerprint,
            "notice": "请确认全部文本获准外发；正则脱敏不保证覆盖机密信息",
        }

    @app.post("/api/analysis/{cid}/enqueue")
    def analyze(cid: str):
        context(db, cid)
        with db.tx() as c:
            enqueue(c, cid)
            c.execute(
                "UPDATE jobs SET status='queued',attempts=0,error=NULL,available_at=? WHERE json_extract(payload,'$.conversation_id')=? AND status IN ('blocked_policy','blocked_credentials','blocked_budget','blocked_context_limit','blocked_association','blocked_empty','blocked_partial','failed')",
                (now(), cid),
            )
        return {"ok": True}

    @app.post("/api/drafts/{cid}")
    def draft(cid: str):
        chat, ev, payload, fingerprint = context(db, cid)
        merchant = db.rows(
            "SELECT * FROM merchants WHERE id=?", (chat["merchant_id"],)
        )[0]
        if merchant["do_not_contact"]:
            raise ValueError("此商家已禁止触达")
        result = call_model(db, payload, draft=True)
        if context(db, cid)[3] != fingerprint:
            raise services.Conflict("上下文或外发政策已变化")
        return result.model_dump() | {
            "notice": "草稿未发送；先核对事实、价格与称呼。复制不代表已联系。"
        }

    # Simplified CRM is the primary product. Older business endpoints remain
    # for existing local integrations while their stored data is retained.
    @app.get("/api/crm")
    def crm_state():
        from .crm import overview

        return overview(db) | {"background": background}

    @app.get("/api/analysis/progress")
    def analysis_progress():
        from .progress import overview

        return overview(db)

    @app.post("/api/analysis/budget/reconcile")
    async def reconcile_budget(request: Request):
        from .analysis import budget_state
        from .crm import schedule

        body = await request.json()
        value = body.get("confirmed_tokens")
        if (
            body.get("confirm_billing") is not True
            or type(value) is not int
            or not 0 <= value <= 100000000
        ):
            raise ValueError("请先核对DeepSeek账单，填写今天已确认的总token用量")
        day = budget_state(db)["day"]
        with db.tx() as c:
            running = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='running' AND lease_until>?",
                (now(),),
            ).fetchone()[0]
            reserved = c.execute(
                "SELECT COUNT(*) FROM usage WHERE day=? AND status='reserved' AND created_at>?",
                (day, (datetime.now(UTC) - timedelta(minutes=10)).isoformat()),
            ).fetchone()[0]
            if running or reserved:
                raise ValueError("仍有请求在进行，请暂停分析并等待请求结束后再校正")
            through = c.execute(
                "SELECT COALESCE(MAX(rowid),0) FROM usage WHERE day=?", (day,)
            ).fetchone()[0]
            db.event(
                c,
                "local-budget:" + day,
                "budget_reconciled",
                {"confirmed_tokens": value, "through_rowid": through},
            )
        schedule(db, retry=True)
        return {"ok": True}

    @app.get("/api/analysis/jobs")
    def analysis_jobs(scope: str = "all", status: str = "all", page: int = 1):
        from .progress import job_page

        return job_page(db, scope, status, page)

    @app.post("/api/crm/configure")
    async def crm_configure(request: Request):
        from .crm import configure

        body = await request.json()
        existing = db.rows(
            "SELECT * FROM crm_policies WHERE account_id=?",
            (db.settings.source_account,),
        )
        previous = existing[0] if existing else {}
        await run_in_threadpool(
            configure,
            db,
            body["enabled"],
            body.get("daily_budget", previous.get("daily_budget", 100000)),
            body.get("include_new", bool(previous.get("include_new", True))),
        )
        return {"ok": True}

    @app.post("/api/crm/retry")
    def crm_retry():
        from .crm import schedule

        return {"queued": schedule(db, retry=True)}

    @app.post("/api/crm/credentials")
    async def crm_credentials(request: Request):
        import keyring

        body = await request.json()
        key = body.get("key")
        if (
            not isinstance(key, str)
            or not 10 <= len(key) <= 500
            or any(ch.isspace() for ch in key)
        ):
            raise ValueError("API key 格式无效")
        try:
            await run_in_threadpool(
                keyring.set_password, "Wechat-Agent", "DEEPSEEK_API_KEY", key
            )
        except Exception:
            raise ValueError(
                "系统凭据存储不可用，请使用本机环境变量或 credentials 命令"
            ) from None
        return {"ok": True}

    @app.post("/api/crm/conversations/{cid}/policy")
    async def crm_conversation_policy(cid: str, request: Request):
        body = await request.json()
        if type(body.get("enabled")) is not bool:
            raise ValueError("会话授权无效")
        with db.tx() as c:
            policy = c.execute(
                "SELECT enabled FROM crm_policies WHERE account_id=?",
                (db.settings.source_account,),
            ).fetchone()
            if body["enabled"] and (not policy or not policy["enabled"]):
                raise ValueError("请先确认工作账号的分析授权")
            changed = c.execute(
                "UPDATE conversations SET egress=? WHERE id=? AND account_id=?",
                (int(body["enabled"]), cid, db.settings.source_account),
            )
            if not changed.rowcount:
                raise ValueError("会话不存在")
            db.event(c, cid, "crm_scope_change", {"enabled": body["enabled"]})
        from .crm import schedule

        schedule(db)
        return {"ok": True}

    @app.get("/api/crm/people")
    def people(q: str = "", scope: str = "customer", page: int = 1):
        if (
            len(q) > 200
            or scope not in {"customer", "archive"}
            or not 1 <= page <= 100000
        ):
            raise ValueError("筛选参数无效")
        where = "n.account_id=? AND n.source_id NOT LIKE '%@chatroom' AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.account_id=n.account_id AND v.source_id=n.source_id AND v.kind='group') AND (instr(lower(COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),n.name)),lower(?))>0 OR instr(lower(n.source_id),lower(?))>0) AND EXISTS(SELECT 1 FROM effective_actor_exclusions x WHERE x.account_id=n.account_id AND x.source_id=n.source_id) = ?"
        args = (db.settings.source_account, q, q, int(scope == "archive"))
        joins = " FROM crm_contacts n LEFT JOIN identity_metadata i ON i.account_id=n.account_id AND i.source_id=n.source_id WHERE "
        total = db.rows("SELECT COUNT(*) n" + joins + where, args)[0]["n"]
        rows = db.rows(
            "SELECT n.id,n.source_id,n.account_id,n.role,COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),n.name) name,? excluded"
            + joins
            + where
            + " ORDER BY name,n.id LIMIT 50 OFFSET ?",
            (int(scope == "archive"), *args, (page - 1) * 50),
        )
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": 50,
            "pages": max(1, (total + 49) // 50),
            "has_more": page * 50 < total,
        }

    @app.post("/api/identity/sync")
    def sync_identity():
        from .crm import index_contacts
        from .identity import sync_contacts

        result = source_operation(lambda source: sync_contacts(db, source))
        with db.tx() as c:
            index_contacts(c, db.settings.source_account)
        return result

    @app.post("/api/source/names/refresh")
    def refresh_source_names():
        from .archive import discover
        from .identity import clean_name

        def refresh(source):
            sessions = discover(source)
            changed = 0
            with db.tx() as c:
                for item in sessions:
                    meta = c.execute(
                        "SELECT remark,nickname FROM identity_metadata WHERE account_id=? AND source_id=?",
                        (db.settings.source_account, item["source_id"]),
                    ).fetchone()
                    title = clean_name(item["title"], item["source_id"])
                    if (not title or title == item["source_id"]) and meta:
                        title = clean_name(
                            meta["remark"] or meta["nickname"], item["source_id"]
                        )

                    if not title or title == item["source_id"]:
                        continue
                    changed += c.execute(
                        "UPDATE conversations SET title=? WHERE account_id=? AND source='wx_cli' AND source_id=? AND title<>?",
                        (title, db.settings.source_account, item["source_id"], title),
                    ).rowcount
            return {
                "ok": True,
                "updated": changed,
                "visible": len(sessions),
                "note": "仅刷新会话名称，不导入消息、不调用模型。",
            }

        return source_operation(refresh)

    @app.get("/api/identity/audit")
    def identity_audit():
        from .identity import audit

        return audit(db)

    @app.post("/api/crm/people/{actor_id}/exclusion")
    async def exclude_person(actor_id: str, request: Request):
        from .identity import set_excluded

        body = await request.json()
        return set_excluded(
            db, actor_id, body.get("enabled"), body.get("reason", "人工免跟进")
        )

    @app.get("/api/monitor")
    def monitor():
        from .monitoring import snapshot

        return snapshot(
            db, source_factory, bool(getattr(app.state, "background", False))
        )

    @app.post("/api/crm/exemptions/undo")
    async def undo_scope(request: Request):
        from .source_scope import undo_sources

        return undo_sources(db, (await request.json()).get("event_id"))

    @app.get("/api/crm/exemptions")
    def exemptions(q: str = "", kind: str = "all", scope: str = "all", page: int = 1):
        from .source_scope import list_sources

        return list_sources(db, q, kind, scope, page)

    @app.post("/api/crm/exemptions")
    async def update_exemptions(request: Request):
        from .source_scope import set_sources

        body = await request.json()
        if type(body.get("enabled")) is not bool:
            raise ValueError("请指定是否免跟进")
        return set_sources(db, body.get("conversation_ids"), not body["enabled"])

    @app.get("/api/crm/followup-sources")
    def followup_sources(
        q: str = "", kind: str = "all", scope: str = "all", page: int = 1
    ):
        from .source_scope import list_sources

        return list_sources(db, q, kind, scope, page)

    @app.post("/api/crm/followup-sources")
    async def update_followup_sources(request: Request):
        from .source_scope import set_sources

        body = await request.json()
        return set_sources(db, body.get("conversation_ids"), body.get("enabled"))

    @app.get("/api/crm/customers")
    def crm_customers(q: str = "", page: int = 1):
        if len(q) > 200 or not 1 <= page <= 100000:
            raise ValueError("查询无效")
        return db.rows(
            "SELECT c.*, (SELECT value FROM crm_facts f WHERE f.customer_id=c.id AND field='summary' ORDER BY event_time DESC LIMIT 1) summary FROM crm_customers c WHERE c.account_id=? AND instr(c.name,?)>0 ORDER BY c.created_at DESC LIMIT 50 OFFSET ?",
            (db.settings.source_account, q, (page - 1) * 50),
        )

    @app.get("/api/crm/customers/{customer_id}")
    def crm_customer(customer_id: str):
        from .crm import customer_details

        return customer_details(db, customer_id)

    @app.post("/api/crm/facts/{fact_id}")
    async def crm_correct_fact(fact_id: str, request: Request):
        body = await request.json()
        value = body.get("value")
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
            raise ValueError("请填写需要保留的事实（最多500字）")
        with db.tx() as c:
            fact = c.execute(
                "SELECT f.* FROM crm_facts f JOIN crm_customers u ON u.id=f.customer_id WHERE f.id=? AND u.account_id=?",
                (fact_id, db.settings.source_account),
            ).fetchone()
            if not fact:
                raise ValueError("事实不存在")
            c.execute(
                "UPDATE crm_facts SET value=?,locked=1 WHERE id=?",
                (value.strip(), fact_id),
            )
            db.event(
                c,
                fact_id,
                "crm_fact_correction",
                {"previous": fact["value"], "value": value.strip()},
            )
        from .crm import schedule

        schedule(db)
        return {"ok": True}

    @app.post("/api/crm/customers/{customer_id}/preferences")
    async def crm_customer_preference(customer_id: str, request: Request):
        body = await request.json()
        if type(body.get("do_not_contact")) is not bool:
            raise ValueError("联系设置无效")
        with db.tx() as c:
            cur = c.execute(
                "UPDATE crm_customers SET do_not_contact=? WHERE id=? AND account_id=?",
                (int(body["do_not_contact"]), customer_id, db.settings.source_account),
            )
            if not cur.rowcount:
                raise ValueError("客户不存在")
        return {"ok": True}

    @app.get("/api/crm/actions/{action_id}/evidence")
    def crm_evidence(action_id: str):
        from .crm import valid_evidence

        actions = db.rows(
            "SELECT a.* FROM crm_actions a JOIN crm_customers c ON c.id=a.customer_id WHERE a.id=? AND c.account_id=?",
            (action_id, db.settings.source_account),
        )
        if not actions:
            raise ValueError("事项不存在")
        return {
            "action": actions[0],
            "messages": valid_evidence(db, actions[0]["evidence"]),
        }

    @app.post("/api/crm/actions/{action_id}/transition")
    async def crm_transition(action_id: str, request: Request):
        from .crm import transition

        body = await request.json()
        return transition(
            db,
            action_id,
            body["state"],
            body["version"],
            body.get("due_date"),
            body.get("note", ""),
        )

    @app.post("/api/crm/actions/{action_id}/draft")
    def crm_draft(action_id: str):
        from .crm import valid_evidence

        action = db.rows(
            "SELECT a.*,u.do_not_contact FROM crm_actions a JOIN crm_customers u ON u.id=a.customer_id WHERE a.id=? AND u.account_id=?",
            (action_id, db.settings.source_account),
        )
        if (
            not action
            or action[0]["do_not_contact"]
            or action[0]["state"] not in {"open", "waiting_external", "snoozed"}
        ):
            raise ValueError("此事项不可生成联系话术")
        refs = valid_evidence(db, action[0]["evidence"])
        if not refs:
            raise ValueError("消息依据已变化，请重新分析")
        # Drafts use only same-conversation evidence; multi-source evidence is
        # retained in the profile but must not be silently omitted in a draft.
        if len({m["conversation_id"] for m in refs}) != 1:
            raise ValueError("跨会话依据需先核对，暂不自动起草")
        cid = refs[0]["conversation_id"]
        ids = [m["id"] for m in refs]
        _, _, payload, fingerprint = context(db, cid, ids)
        payload["action"] = {
            "summary": action[0]["summary"],
            "reason": action[0]["reason"],
        }
        cached = db.rows(
            "SELECT payload FROM events WHERE entity_id=? AND kind='crm_draft_cache' ORDER BY created_at DESC LIMIT 1",
            (action_id,),
        )
        if cached:
            value = json.loads(cached[0]["payload"])
            if (
                value.get("fingerprint") == fingerprint
                and value.get("version") == action[0]["version"]
                and value.get("model") == db.settings.model
            ):
                return value["result"] | {
                    "notice": "草稿未发送；复制不会记录联系或完成。"
                }
        result = call_model(db, payload, draft=True)
        current_action = db.rows(
            "SELECT a.version,u.do_not_contact FROM crm_actions a JOIN crm_customers u ON u.id=a.customer_id WHERE a.id=?",
            (action_id,),
        )
        if (
            not current_action
            or current_action[0]["do_not_contact"]
            or current_action[0]["version"] != action[0]["version"]
        ):
            raise services.Conflict("任务或联系设置已变化")
        if context(db, cid, ids)[3] != fingerprint:
            raise services.Conflict("依据或授权已变化")
        with db.tx() as c:
            db.event(
                c,
                action_id,
                "crm_draft_cache",
                {
                    "version": action[0]["version"],
                    "fingerprint": fingerprint,
                    "model": db.settings.model,
                    "result": result.model_dump(),
                },
            )
        return result.model_dump() | {"notice": "草稿未发送；复制不会记录联系或完成。"}

    @app.get("/api/crm/reviews")
    def crm_reviews():
        from .crm import valid_evidence

        return [
            r | {"sources": valid_evidence(db, r["evidence"])}
            for r in db.rows(
                "SELECT * FROM crm_reviews WHERE account_id=? AND status='pending' ORDER BY created_at DESC LIMIT 50",
                (db.settings.source_account,),
            )
        ]

    @app.post("/api/crm/reviews/clear")
    def clear_reviews():
        with db.tx() as c:
            result = c.execute(
                "UPDATE crm_reviews SET status='cleared' WHERE account_id=? AND status='pending'",
                (db.settings.source_account,),
            )
            count = result.rowcount
            db.event(c, db.settings.source_account, "reviews_cleared", {"count": count})
        return {"ok": True, "cleared": count}

    @app.post("/api/crm/reviews/{review_id}")
    async def crm_review(review_id: str, request: Request):
        from .crm import resolve_review

        return resolve_review(db, review_id, (await request.json())["resolution"])

    return app
