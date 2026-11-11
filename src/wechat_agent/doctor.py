"""Offline diagnostics. Pending capabilities are never reported as verified."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys

from .config import Settings


_SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "password", "token", "access_token",
    "refresh_token", "secret", "client_secret", "headers", "credential", "credentials",
}


def _redact(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if str(key).casefold().replace("-", "_") in _SENSITIVE_KEYS
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def collect_runtime() -> dict:
    supported = sys.version_info[:2] == (3, 12)
    return {
        "component": "runtime",
        "status": "passed" if supported else "failed",
        "facts": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "architecture": platform.machine(),
        },
        "gaps": [] if supported else ["python_3_12_required"],
    }


def _component(name: str, supplied: dict | None, gap: str, *, unsupported: bool = False) -> dict:
    if supplied is not None:
        return _redact({"component": name, "status": "pending", "facts": {}, "gaps": [], **supplied})
    return {
        "component": name,
        "status": "unsupported" if unsupported else "pending",
        "facts": {},
        "gaps": [gap],
    }


def build_report(*, data_dir: Path, source: dict | None, model: dict | None) -> dict:
    runtime = collect_runtime()
    runtime["facts"]["data_dir"] = str(data_dir)
    is_mac = runtime["facts"]["platform"] == "Darwin"
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime,
        "source": _component("source", source, "source_not_checked" if is_mac else "mac_required",
                             unsupported=not is_mac),
        "model": _component("model", model, "model_not_checked"),
        "media": _component("media", None, "media_not_checked"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an offline local capability report.")
    parser.add_argument("--output", type=Path, help="Also write the JSON report to this path.")
    args = parser.parse_args(argv)
    report = build_report(data_dir=Settings.load().data_dir, source=None, model=None)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        except OSError as error:
            parser.exit(2, f"Cannot write diagnostic report: {error}\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
