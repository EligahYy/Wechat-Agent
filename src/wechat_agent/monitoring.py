"""On-demand local health checks; never call model inference or expose secrets."""

from datetime import UTC, datetime

import httpx

from .collector import SourceError
from .db import now


def snapshot(db, source_factory, background):
    checks = [
        {"name": "工作台", "state": "ok", "detail": "本机 Web 服务可访问，数据库可读"}
    ]
    source = None
    try:
        source = source_factory(db)
        source.client.timeout = httpx.Timeout(5)
        info = source.probe()
        checks.append(
            {
                "name": "wx-cli / 微信连接",
                "state": "ok" if info["bound"] else "warning",
                "detail": ("已绑定 " if info["bound"] else "服务可达，需确认工作账号：")
                + info["account_name"]
                + " · wx-cli "
                + str(info.get("source_version") or "未知版本"),
            }
        )
    except httpx.HTTPStatusError as exc:
        checks.append(
            {
                "name": "wx-cli / 微信连接",
                "state": "error",
                "detail": "源服务鉴权失败，请配置 WX_SOURCE_TOKEN 并重启"
                if exc.response.status_code in (401, 403)
                else "采集服务返回 HTTP "
                + str(exc.response.status_code)
                + "，检查版本与源服务日志",
            }
        )
    except (httpx.HTTPError, SourceError, ValueError, KeyError, TypeError) as exc:
        checks.append(
            {
                "name": "wx-cli / 微信连接",
                "state": "error",
                "detail": "本机采集服务检查未通过（"
                + type(exc).__name__
                + "），检查微信登录、9100端口和源服务日志",
            }
        )
    finally:
        if source:
            source.client.close()
    rows = {r["name"]: r for r in db.rows("SELECT * FROM runtime")}
    labels = {
        "running": "运行中",
        "idle": "等待新任务",
        "awaiting_account": "等待绑定工作账号",
        "awaiting_authorization": "等待分析授权",
    }
    policy = db.rows(
        "SELECT enabled FROM crm_policies WHERE account_id=?",
        (db.settings.source_account,),
    )
    running = db.rows(
        "SELECT created_at FROM jobs WHERE status='running' ORDER BY created_at DESC LIMIT 1"
    )
    for name, title in (
        ("collector", "消息采集与历史补齐"),
        ("worker", "DeepSeek 分析后台"),
    ):
        row = rows.get(name)
        if not background:
            status, detail = (
                "warning",
                "本进程未启动统一后台，请使用 wechat-agent start",
            )
        elif not row:
            status, detail = "warning", "后台正在启动，尚无状态记录"
        else:
            age = (
                datetime.now(UTC) - datetime.fromisoformat(row["updated_at"])
            ).total_seconds()
            raw = row["status"]
            threshold = (
                660 if name == "worker" and raw == "running" and running else 180
            )
            status = (
                "error"
                if raw.startswith("error:")
                else "warning"
                if age > threshold
                else "ok"
            )
            detail = labels.get(raw, raw) + (
                " · 状态较久未更新，请检查日志" if age > threshold else ""
            )
            if name == "worker" and not (policy and policy[0]["enabled"]):
                status, detail = "warning", "分析已暂停／尚未授权，采集不受影响"
        checks.append(
            {
                "name": title,
                "state": status,
                "detail": detail,
                "updated_at": row["updated_at"] if row else None,
            }
        )
    return {
        "checked_at": now(),
        "checks": checks,
        "note": "只检测本机源服务与后台状态，不读取聊天正文，不调用 DeepSeek；wx-cli 可达不代表模型网络可达。",
    }
