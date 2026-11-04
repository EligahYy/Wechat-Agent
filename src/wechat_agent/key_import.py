"""Offline bridge for wechat-export-macos/raw-key-v1; never invokes a debugger."""

import hashlib
import hmac
import json
import os
import struct
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path


class ImportError(ValueError):
    """Only fixed, non-secret messages may leave this module."""


def page_matches(raw, page):
    if len(page) != 4096:
        return False
    enc = hashlib.pbkdf2_hmac("sha512", raw, page[:16], 256000, dklen=32)
    salt = bytes(x ^ 0x3A for x in page[:16])
    mac = hashlib.pbkdf2_hmac("sha512", enc, salt, 2, dklen=32)
    expected = hmac.new(
        mac, page[16:4032] + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    return hmac.compare_digest(expected, page[-64:])


def private_temp(directory, content, prefix):
    fd, name = tempfile.mkstemp(dir=directory, prefix=prefix)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        os.unlink(name)
        raise
    return Path(name)


def import_legacy(root, target=None, write=False):
    """Preview by default. Raw key stays in memory and local protected files."""
    root = Path(root).expanduser().resolve()
    preferred = root / "data/config.json"
    config_path = (
        preferred
        if preferred.exists() or not (root / "config.json").exists()
        else root / "config.json"
    )
    try:
        config = json.loads(config_path.read_text())
        db_path = Path(config["db_dir"]).expanduser()
        if not db_path.is_absolute():
            db_path = config_path.parent / db_path
        db_path = db_path.resolve(strict=True)
        key_path = Path(config.get("keys_file", "all_keys.json")).expanduser()
        if not key_path.is_absolute():
            key_path = config_path.parent / key_path
        payload = json.loads(key_path.read_text())
        if (
            payload.get("_format") != "wechat-export-macos/raw-key-v1"
            or payload.get("_key_type") != "account_raw_key"
        ):
            raise ImportError("只支持旧工具 raw-key-v1 格式，未写入")
        raw = bytes.fromhex(payload["_raw_key"])
        if len(raw) != 32:
            raise ImportError("旧密钥长度无效，未写入")
        if Path(payload["_account_dir"]).expanduser().resolve() != db_path:
            raise ImportError("密钥声明账号与旧配置不一致，未写入")
        if (
            db_path.name != "db_storage"
            or db_path.parent.parent.name != "xwechat_files"
        ):
            raise ImportError("账号目录结构不符合预期，未写入")
        required = {"message/message_0.db", "contact/contact.db", "session/session.db"}
        validated = []
        for path in sorted(db_path.rglob("*.db")):
            if path.is_symlink():
                raise ImportError("发现符号链接数据库，未写入")
            with path.open("rb") as stream:
                page = stream.read(4096)
            if len(page) < 4096 or page.startswith(b"SQLite format 3\0"):
                continue
            if not page_matches(raw, page):
                raise ImportError("存在数据库首页校验失败，未写入；请先用旧工具诊断")
            validated.append(path.relative_to(db_path).as_posix())
        if not required <= set(validated):
            raise ImportError("消息、联系人、会话库未全部验证，未写入")
        account = db_path.parent.name
        version = str(payload.get("_wechat", {}).get("version", "unknown"))
        target = (
            Path(target)
            if target
            else Path.home() / "Library/Application Support/wx-cli/config/keys.toml"
        )
        target = target.expanduser().absolute()
        if target.is_symlink():
            raise ImportError("目标密钥库为符号链接，未写入")
        original = target.read_bytes() if target.exists() else None
        parsed = tomllib.loads(original.decode()) if original is not None else {}
        accounts = parsed.get("accounts", {})
        if not isinstance(accounts, dict):
            raise ImportError("目标密钥库格式不兼容，未写入")
        existing = accounts.get(account)
        report = {
            "account_id": account,
            "validated_databases": len(validated),
            "target": str(target),
            "written": False,
        }
        if existing is not None:
            if not isinstance(existing, dict) or existing.get("data_key") != raw.hex():
                raise ImportError("目标账号已有不同密钥或配置，拒绝覆盖")
            return report | {"status": "already_present"}

        def quoted(value):
            return json.dumps(value, ensure_ascii=False)

        entry = (
            "\n[accounts."
            + quoted(account)
            + "]\n"
            + "".join(
                k + " = " + quoted(v) + "\n"
                for k, v in {
                    "account_id": account,
                    "data_key": raw.hex(),
                    "extracted_at": datetime.now(UTC).isoformat(),
                    "wechat_version": version,
                }.items()
            )
        )
        # An inline empty accounts table cannot be extended in TOML. Preserve its
        # original bytes in the backup, then replace only this known-empty shape.
        base = "" if parsed in ({}, {"accounts": {}}) else original.decode()
        output = (base.rstrip() + "\n" + entry).encode()
        combined = tomllib.loads(output.decode())
        if combined["accounts"][account]["data_key"] != raw.hex():
            raise ImportError("转换验证失败，未写入")
        if not write:
            return report | {"status": "preview_ok"}
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup = None
        if original is not None:
            backup = private_temp(target.parent, original, "keys.toml.backup-")
        temp = private_temp(target.parent, output, ".keys-import-")
        try:
            if (
                target.is_symlink()
                or (target.read_bytes() if target.exists() else None) != original
            ):
                raise ImportError(
                    "目标文件在导入期间变化，未覆盖；请停止 wx-cli 服务后重试"
                )
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return report | {
            "status": "imported",
            "written": True,
            "backup": str(backup) if backup else None,
        }
    except ImportError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # JSON decode errors can embed content: never forward their text.
        raise ImportError(
            "读取或格式校验失败，未完成导入；请检查旧项目路径与配置"
        ) from None
