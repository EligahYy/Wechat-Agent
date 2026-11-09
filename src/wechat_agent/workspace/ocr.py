"""Local OCR candidates. Only explicit human confirmation becomes model input."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..db import now
from ..media import local_image
from ..services import Conflict


def available():
    if sys.platform == "darwin" and shutil.which("xcrun"):
        return {
            "available": True,
            "engine": "macOS Vision",
            "note": "本机文字识别；需人工核对后才用于分析",
        }
    if shutil.which("tesseract"):
        return {
            "available": True,
            "engine": "Tesseract",
            "note": "语言能力取决于本机语言包；识别结果需人工核对",
        }
    return {
        "available": False,
        "engine": None,
        "note": "未找到本机OCR工具；仍可查看图片并手动填写核对文本",
    }


def message(db, mid):
    rows = db.rows(
        "SELECT m.* FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id=? AND v.account_id=?",
        (mid, db.settings.source_account),
    )
    if not rows or not db.rows(
        "SELECT 1 FROM conversations WHERE id=? AND account_id=? AND allowlisted=1",
        (rows[0]["conversation_id"], db.settings.source_account),
    ):
        raise ValueError("workspace_source_not_allowed")
    if rows[0]["type"] not in {"image", "3"}:
        raise ValueError("workspace_not_image")
    return rows[0]


def state(db, mid):
    m = message(db, mid)
    rows = db.rows(
        "SELECT x.* FROM message_extractions x JOIN attachments a ON a.message_id=x.message_id AND a.sha256=x.sha256 WHERE x.message_id=? AND x.source_revision=?",
        (mid, m["revision"]),
    )
    old = db.rows("SELECT version FROM message_extractions WHERE message_id=?", (mid,))
    fallback = {
        "message_id": mid,
        "version": old[0]["version"] if old else 0,
        "source_revision": m["revision"],
        "candidate_text": "",
        "confirmed_text": "",
    }
    return (rows[0] if rows else fallback) | {"ocr": available()}


def recognize_bytes(data):
    capability = available()
    if not capability["available"]:
        raise ValueError("workspace_ocr_unavailable")
    try:
        if capability["engine"] == "macOS Vision":
            with tempfile.NamedTemporaryFile(suffix=".image") as f:
                f.write(data)
                f.flush()
                result = subprocess.run(
                    [
                        "xcrun",
                        "swift",
                        str(Path(__file__).with_name("vision.swift")),
                        f.name,
                    ],
                    capture_output=True,
                    timeout=120,
                    check=True,
                )
                text = json.loads(result.stdout)["text"]
        else:
            languages = subprocess.run(
                ["tesseract", "--list-langs"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.splitlines()
            lang = "chi_sim+eng" if "chi_sim" in languages else "eng"
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", lang],
                input=data,
                capture_output=True,
                timeout=60,
                check=True,
            )
            text = result.stdout.decode("utf-8").strip()
        if not isinstance(text, str) or not text.strip():
            raise ValueError("workspace_ocr_empty")
        if len(text) > 20000:
            raise ValueError("workspace_ocr_too_large")
        return text, capability["engine"]
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        raise ValueError("workspace_ocr_failed") from None


def candidate(db, mid, factory):
    m = message(db, mid)
    image = local_image(db, mid, factory)
    digest = hashlib.sha256(image["bytes"]).hexdigest()
    text, engine = recognize_bytes(image["bytes"])
    with db.tx() as c:
        current = message(db, mid)
        if current["revision"] != m["revision"]:
            raise Conflict("workspace_stale_input")
        old = c.execute(
            "SELECT * FROM message_extractions WHERE message_id=?", (mid,)
        ).fetchone()
        same = (
            old and old["source_revision"] == m["revision"] and old["sha256"] == digest
        )
        version = old["version"] if same else (old["version"] + 1 if old else 0)
        confirmed = old["confirmed_text"] if same else ""
        c.execute(
            "INSERT OR REPLACE INTO message_extractions VALUES(?,?,?,?,?,?,?,?)",
            (mid, m["revision"], digest, version, confirmed, text, engine, now()),
        )
    return state(db, mid)


def confirm(db, mid, version, text, factory):
    if (
        type(version) is not int
        or not isinstance(text, str)
        or not 1 <= len(text.strip()) <= 20000
    ):
        raise ValueError("workspace_invalid_ocr_text")
    m = message(db, mid)
    image = local_image(db, mid, factory)
    digest = hashlib.sha256(image["bytes"]).hexdigest()
    with db.tx() as c:
        if message(db, mid)["revision"] != m["revision"]:
            raise Conflict("workspace_stale_input")
        old = c.execute(
            "SELECT * FROM message_extractions WHERE message_id=?", (mid,)
        ).fetchone()
        actual = old["version"] if old else 0
        if actual != version:
            raise Conflict("workspace_ocr_version_conflict")
        engine = old["engine"] if old else "manual"
        c.execute(
            "INSERT OR REPLACE INTO message_extractions VALUES(?,?,?,?,?,?,?,?)",
            (
                mid,
                m["revision"],
                digest,
                version + 1,
                text.strip(),
                old["candidate_text"]
                if old
                and old["source_revision"] == m["revision"]
                and old["sha256"] == digest
                else "",
                engine,
                now(),
            ),
        )
        db.event(
            c,
            mid,
            "verified_image_text",
            {"version": version + 1, "text": text.strip()},
        )
    return state(db, mid)
