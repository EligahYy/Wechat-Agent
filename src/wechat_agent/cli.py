import argparse
import getpass
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .analysis import Blocked, call_model, run_once
from .collector import Collector
from .config import Settings
from .db import DB, dumps
from .ingestion import ingest
from .services import allow_conversation, create_merchant, create_project


def parser():
    p = argparse.ArgumentParser(description="本地商家备货与头程物流协同助手")
    p.add_argument(
        "--data-dir", type=Path, help="本机私有数据目录（请勿选网盘同步目录）"
    )
    s = p.add_subparsers(dest="command", required=True)
    s.add_parser("init")
    s.add_parser("diagnose", help="输出安全的模型失败诊断，不调用API、不输出聊天或凭据")
    token = s.add_parser("token")
    token.add_argument(
        "--rotate", action="store_true", help="轮换本地口令并使旧会话失效"
    )
    s.add_parser("demo")
    start = s.add_parser("start", help="启动工作台及采集、历史补齐和分析后台")
    start.add_argument("--port", type=int, default=8765)
    archive = s.add_parser("archive", help="全量私信与群聊本地初始化，不依赖导出文件")
    archive.add_argument(
        "action", choices=["discover", "init-all", "resume", "repair", "status"]
    )
    archive.add_argument(
        "--details", action="store_true", help="显示失败会话断点与错误，不含消息正文"
    )
    archive.add_argument("--account", help="明确确认源端 wxid；首次绑定必填")
    archive.add_argument(
        "--rescan", action="store_true", help="从第一页幂等重扫，重查迟到历史与缺口"
    )
    bridge = s.add_parser("key-import", help="本地校验并迁移旧导出工具密钥；默认只预览")
    bridge.add_argument("--legacy-root", type=Path, required=True)
    bridge.add_argument("--write", action="store_true")
    auth = s.add_parser("credentials")
    auth.add_argument("name", choices=["DEEPSEEK_API_KEY", "WX_SOURCE_TOKEN"])
    imp = s.add_parser("import")
    imp.add_argument("file", type=Path)
    imp.add_argument("--preview", action="store_true")
    imp.add_argument("--account", help="文件所属工作微信账号 wxid")
    serve = s.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    serve.add_argument("--port", type=int, default=8765)
    worker = s.add_parser("worker")
    worker.add_argument("--engine", choices=["deepseek"], default="deepseek")
    worker.add_argument("--once", action="store_true")
    source = s.add_parser("source")
    source.add_argument("action", choices=["validate"])
    source.add_argument("--source", choices=["wx-cli"], default="wx-cli")
    collect = s.add_parser("collect")
    collect.add_argument("--source", choices=["wx-cli"], default="wx-cli")
    collect.add_argument("--once", action="store_true")
    collect.add_argument("--conversation")
    collect.add_argument("--since", type=int)
    collect.add_argument("--until", type=int)
    model = s.add_parser("model")
    model.add_argument("action", choices=["validate"])
    model.add_argument("--fixture", type=Path, required=True)
    b = s.add_parser("backup")
    b.add_argument("file", type=Path)
    return p


def seed_demo(db):
    if db.rows("SELECT 1 FROM merchants LIMIT 1"):
        raise ValueError("demo 仅可在空数据目录运行，避免混入真实数据")
    mid = create_merchant(db, "示例商家 A（虚构）")
    pid = create_project(db, mid, "美国普通货第一批（虚构）", "美国")
    cid = allow_conversation(
        db,
        "fixture",
        "demo-account",
        "demo-chat-1",
        "三方对接示例（虚构）",
        "group",
        mid,
        pid,
        False,
    )
    rows = [
        dict(
            schema_version=1,
            source="fixture",
            account_id="demo-account",
            conversation_id="demo-chat-1",
            conversation_type="group",
            source_id=f"demo-{i}",
            sender_id=sender,
            direction=direction,
            event_time=f"2026-11-04T09:0{i}:00+08:00",
            message_type="text",
            text=text,
        )
        for i, (sender, direction, text) in enumerate(
            [
                (
                    "demo-merchant",
                    "incoming",
                    "我们这批普通货准备发美国，预计下周备好，请确认费用。",
                ),
                (
                    "demo-provider",
                    "incoming",
                    "我明天核实附加费后回复；请商家补充重量和体积。",
                ),
                (
                    "demo-self",
                    "outgoing",
                    "我来协调，请先确认计价和税费口径，不承诺具体到仓日。",
                ),
            ]
        )
    ]
    ingest(db, rows)
    return {
        "merchant_id": mid,
        "project_id": pid,
        "conversation_id": cid,
        "note": "虚构数据已导入；默认禁止模型外发，不自动生成模拟 AI 结果",
    }


def main():
    args = parser().parse_args()
    settings = Settings()
    if args.data_dir:
        settings.data_dir = args.data_dir
    if args.command == "key-import":
        from .key_import import import_legacy

        try:
            print(dumps(import_legacy(args.legacy_root, write=args.write)))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1)
        return
    db = DB(settings)
    try:
        if args.command == "init":
            print("已初始化本地数据库；查看登录口令：wechat-agent token")
        elif args.command == "diagnose":
            from .diagnostics import snapshot

            print(dumps(snapshot(db)))
        elif args.command == "token":
            if args.rotate:
                db.rotate_token()
            print(db.token)
        elif args.command == "credentials":
            import keyring

            value = getpass.getpass("输入 DeepSeek API key（不回显，不发送到聊天）: ")
            if not value:
                raise ValueError("不能为空")
            keyring.set_password("Wechat-Agent", args.name, value)
            print("已保存到系统凭据存储")
        elif args.command == "demo":
            print(dumps(seed_demo(db)))
        elif args.command == "import":
            from .file_import import MAX_BYTES, import_file

            if args.file.stat().st_size > MAX_BYTES:
                raise ValueError("文件超过 64 MB，请拆分")
            print(
                dumps(
                    import_file(
                        db,
                        args.file.read_text(encoding="utf-8-sig"),
                        args.file.name,
                        args.account,
                        write=not args.preview,
                    )
                )
            )
        elif args.command in {"serve", "start"}:
            import uvicorn

            from .web import create_app

            uvicorn.run(
                create_app(settings, background=True),
                host="127.0.0.1",
                port=args.port,
                access_log=False,
            )
        elif args.command == "archive":
            from .archive import (
                discover,
                import_history,
                register,
                repair_metadata,
                status_report,
            )

            if args.action == "status":
                print(dumps(status_report(db, details=args.details)))
                return
            source = Collector(db)
            try:
                account = source.probe()
                if args.account:
                    if args.account != account["account_id"]:
                        raise ValueError("源端账号不匹配")
                    db.settings.bind_source(args.account)
                if not account["bound"] and not args.account:
                    raise ValueError(
                        "请用 --account 明确源端 wxid 后绑定，或先在页面确认账号"
                    )
                if args.action in {"discover", "init-all"}:
                    sessions = discover(source)
                    print(
                        dumps(
                            {
                                "discovered": len(sessions),
                                "groups": sum(
                                    s["kind"] == "group" and not s["excluded"]
                                    for s in sessions
                                ),
                                "private": sum(
                                    s["kind"] == "private" and not s["excluded"]
                                    for s in sessions
                                ),
                                "excluded": sum(s["excluded"] for s in sessions),
                            }
                        ),
                        flush=True,
                    )
                    if args.action == "discover":
                        return
                    register(
                        db,
                        sessions,
                        int(datetime.now(UTC).timestamp()),
                        args.rescan,
                    )
                if args.action == "repair":
                    print(
                        dumps({"metadata_chats_requeued": repair_metadata(db)}),
                        flush=True,
                    )
                report = import_history(
                    db, source, emit=lambda event: print(dumps(event), flush=True)
                )
                print(dumps(report))
                if any(
                    p["status"] in {"failed", "scanned_with_gaps"}
                    for p in report["progress"]
                ):
                    raise SystemExit(2)
            finally:
                source.client.close()
        elif args.command == "source":
            client = Collector(db)
            try:
                print(dumps(client.validate()))
            finally:
                client.client.close()
        elif args.command == "collect":
            source = Collector(db)
            try:
                while True:
                    if args.conversation:
                        if args.since is None or args.until is None:
                            raise ValueError(
                                "指定会话回填需 --since 和 --until Unix 时间"
                            )
                        chats = db.rows(
                            "SELECT * FROM conversations WHERE id=?",
                            (args.conversation,),
                        )
                        if not chats:
                            raise ValueError("会话不存在")
                        print(
                            dumps(source.sync_window(chats[0], args.since, args.until))
                        )
                        break
                    print(dumps(source.tick()))
                    if args.once:
                        break
                    time.sleep(10)
            finally:
                source.client.close()
        elif args.command == "worker":
            while True:
                worked = run_once(db)
                if args.once:
                    break
                if not worked:
                    time.sleep(2)
        elif args.command == "model":
            payload = json.loads(args.fixture.read_text())
            # Smoke fixture is explicitly synthetic and cannot carry arbitrary live data.
            if payload.get("synthetic") is not True:
                raise ValueError("首次 API 检查仅接受 synthetic=true 的虚构样例")
            result = call_model(db, payload)
            print(
                dumps({"status": "live_api_succeeded", "result": result.model_dump()})
            )
        elif args.command == "backup":
            db.backup(args.file)
            print("数据库已一致性备份（素材文件如有需另存）")
    except KeyboardInterrupt:
        return
    except Exception as exc:
        # Credential-bearing HTTP exceptions and validation inputs are not printed.
        if isinstance(exc, Blocked):
            message = exc.status
        elif isinstance(exc, ValueError):
            message = str(exc) if type(exc) is ValueError else type(exc).__name__
        else:
            message = type(exc).__name__
        print(f"操作失败：{message}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
