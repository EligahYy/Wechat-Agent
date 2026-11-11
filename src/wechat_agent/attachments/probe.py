"""Inspect explicit local files without executing or parsing their contents."""

import hashlib
import mimetypes
from pathlib import Path
import stat
from typing import Literal

from ..source.contracts import CapabilityReport


def inspect_media(path: Path, *, quality: Literal["unknown", "original", "thumbnail"] = "unknown") -> dict:
    path = path.expanduser()
    report = {"path": str(path.absolute()), "name": path.name, "state": "failed",
              "quality": quality, "parsed": False, "size_bytes": None, "sha256": None,
              "mime": None, "type_detection": "not_checked"}
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            return {**report, "gap": "media_not_a_file"}
        report["size_bytes"] = before.st_size
        if not before.st_size:
            return {**report, "gap": "media_empty"}
        digest = hashlib.sha256()
        header = b""
        read = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if not header:
                    header = chunk[:64]
                digest.update(chunk)
                read += len(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or read != before.st_size:
            return {**report, "gap": "media_changed_during_check"}
        mime = None
        for prefix, detected in ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
                                 (b"%PDF-", "application/pdf"), (b"GIF8", "image/gif")):
            if header.startswith(prefix):
                mime = detected
                break
        report.update(state="available", sha256=digest.hexdigest(),
                      mime=mime or mimetypes.guess_type(path.name)[0],
                      type_detection="header_hint" if mime else "filename_hint")
        return report
    except FileNotFoundError:
        return {**report, "state": "missing", "gap": "media_missing"}
    except PermissionError:
        return {**report, "gap": "media_permission_denied"}
    except OSError:
        return {**report, "gap": "media_access_failed"}


def inspect_media_set(paths: list[Path], *, quality: str = "unknown") -> CapabilityReport:
    files = [{"index": index + 1, **inspect_media(path, quality=quality)} for index, path in enumerate(paths)]
    gaps = sorted({item["gap"] for item in files if "gap" in item})
    return CapabilityReport(component="media", status="failed" if gaps else "passed", gaps=gaps,
                            facts={"scope": "file_availability", "files_checked": len(files), "parsed": False, "files": files})
