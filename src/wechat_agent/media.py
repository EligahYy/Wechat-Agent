"""On-demand raster image archival from the local, identity-checked wx-cli API."""

import hashlib
import os
import tempfile

import httpx

from .db import now

LIMIT = 10 * 1024 * 1024


def raster_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("上游未返回支持的图片格式；不展示 HTML、SVG 或未知文件")


def local_image(db, mid, factory, refresh=False):
    rows = db.rows(
        "SELECT m.*,c.source,c.source_id chat_id,c.account_id,c.allowlisted FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=?",
        (mid,),
    )
    if (
        not rows
        or rows[0]["source"] != "wx_cli"
        or rows[0]["type"] not in ("3", "image")
    ):
        raise ValueError("此消息不是可读取的真实微信图片")
    message = rows[0]
    if message["account_id"] != db.settings.source_account:
        raise ValueError("图片不属于当前工作账号")
    directory = db.settings.data_dir / "media"
    cached = db.rows("SELECT * FROM attachments WHERE message_id=?", (mid,))
    if cached and not refresh:
        meta = cached[0]
        path = directory / (meta["sha256"] + ".bin")
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if (
                len(data) <= LIMIT
                and hashlib.sha256(data).hexdigest() == meta["sha256"]
            ):
                return {
                    "bytes": data,
                    "mime": raster_type(data),
                    "quality": meta["quality"],
                }
    if (
        not message["allowlisted"]
        or message["account_id"] != db.settings.source_account
    ):
        raise ValueError("会话已暂停或当前账号不匹配，不再从源端读取图片")
    source = factory(db)
    try:
        source.validate()
        with source.client.stream(
            "GET",
            "/api/v1/media",
            params={"talker": message["chat_id"], "server_id": message["source_id"]},
        ) as response:
            if response.status_code == 404:
                raise ValueError(
                    "本机暂未找到图片：请在微信里打开该图片并下载原图后重试；也可能缺少图片解密密钥"
                )
            response.raise_for_status()
            pieces = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > LIMIT:
                    raise ValueError("图片超过本地预览的 10 MB 上限")
                pieces.append(chunk)
            data = b"".join(pieces)
            quality = response.headers.get("x-wechat-media-quality", "unknown")
            if quality not in {"full", "thumbnail"}:
                quality = "unknown"
        mime = raster_type(data)
        digest = hashlib.sha256(data).hexdigest()
        directory.mkdir(mode=0o700, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=directory, prefix=".image-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temp, directory / (digest + ".bin"))
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        # If policy or evidence changed while downloading, do not attach stale bytes.
        with db.tx() as c:
            current = c.execute(
                "SELECT revision FROM messages WHERE id=?", (mid,)
            ).fetchone()
            allowed = c.execute(
                "SELECT allowlisted FROM conversations WHERE id=?",
                (message["conversation_id"],),
            ).fetchone()
            if (
                not current
                or current["revision"] != message["revision"]
                or not allowed["allowlisted"]
            ):
                raise ValueError("消息或会话状态发生变化，请刷新后重试")
            c.execute(
                "INSERT INTO attachments VALUES(?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET sha256=excluded.sha256,mime=excluded.mime,quality=excluded.quality,size=excluded.size,created_at=excluded.created_at",
                (mid, digest, mime, quality, len(data), now()),
            )
        return {"bytes": data, "mime": mime, "quality": quality}
    except httpx.HTTPError:
        raise ValueError(
            "本机图片接口读取失败，请检查采集服务、认证与图片解密能力"
        ) from None
    finally:
        source.client.close()
