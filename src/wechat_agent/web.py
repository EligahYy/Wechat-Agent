import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import UTC, datetime
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


def create_app(settings=None, source_factory=None):
    db = DB(settings or Settings())
    app = FastAPI(title="Wechat-Agent", docs_url=None, redoc_url=None, openapi_url=None)
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
        # A user following an external link may legitimately navigate to the
        # entry page. Never extend this exception to API reads or mutations.
        entry_navigation = (
            request.method == "GET"
            and request.url.path == "/"
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
        if request.url.path not in {"/login", "/"} and not authenticated:
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

    @app.exception_handler(KeyError)
    async def missing_field(request, exc):
        return JSONResponse({"error": "缺少必填字段"}, 422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity(request, exc):
        return JSONResponse({"error": "关联不存在或记录重复，请核对输入"}, 422)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        template = "dashboard.html" if request.state.authenticated else "login.html"
        return env.get_template(template).render(
            csrf=request.state.csrf if request.state.authenticated else "",
            nonce=request.state.nonce,
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
            "schema": 4,
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
            db.settings.bind_source(account["account_id"])
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
        if not 1 <= page <= 100000:
            raise ValueError("页码无效")
        return db.rows(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY event_time DESC,id DESC LIMIT 100 OFFSET ?",
            (cid, (page - 1) * 100),
        )

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

    return app
