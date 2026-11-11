"""Offline by default; connection probes require explicit flags."""

import argparse
import asyncio
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


def build_report(*, data_dir: Path, source: dict | None, model: dict | None, media: dict | None = None) -> dict:
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
        "media": _component("media", media, "media_not_checked"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an offline local capability report.")
    parser.add_argument("--output", type=Path, help="Also write the JSON report to this path.")
    parser.add_argument("--check-source", action="store_true", help="Check the local wx-cli HTTP service.")
    parser.add_argument("--source-config", type=Path, help="Local source JSON configuration.")
    parser.add_argument("--source-url", help="Loopback wx-cli URL; default http://127.0.0.1:9100.")
    parser.add_argument("--source-account", help="Expected canonical wxid reported by health.")
    parser.add_argument("--source-samples", action="store_true", help="Read bounded private/group samples, without model calls.")
    parser.add_argument("--check-model", action="store_true", help="Explicitly send one minimal model probe; may incur usage.")
    parser.add_argument("--model-config", type=Path, help="Local configured model endpoint and ID, no plaintext key.")
    parser.add_argument("--check-media", nargs="+", type=Path, help="Inspect explicit local files without parsing them.")
    parser.add_argument("--media-quality", choices=["unknown", "original", "thumbnail"], default="unknown",
                        help="Known source quality, never inferred from a filename.")
    parser.add_argument("--shareable-output", type=Path, help="Write allowlisted technical feedback; omit local paths and chat.")
    args = parser.parse_args(argv)
    if args.source_samples and not args.check_source:
        parser.error("--source-samples requires --check-source")
    settings = Settings.load()
    inputs = [args.source_config or settings.source_config, args.model_config or settings.model_config,
              *(args.check_media or [])]
    input_paths = {path.expanduser().resolve() for path in inputs if path is not None}
    outputs = [path for path in (args.output, args.shareable_output) if path is not None]
    output_paths = [path.expanduser().resolve() for path in outputs]
    if any(path in input_paths for path in output_paths) or len(set(output_paths)) != len(output_paths):
        parser.error("report_output_conflicts_with_input")
    source = None
    if args.check_source:
        from .source.probe import run_source_probe
        source = asyncio.run(run_source_probe(args.source_config or settings.source_config,
                                              base_url=args.source_url, expected_account_id=args.source_account,
                                              samples=args.source_samples)).model_dump(mode="json")
    model = None
    if args.check_model:
        from .model.probe import run_model_probe
        model = asyncio.run(run_model_probe(args.model_config or settings.model_config)).model_dump(mode="json")
    media = None
    if args.check_media:
        from .attachments.probe import inspect_media_set
        media = inspect_media_set(args.check_media, quality=args.media_quality).model_dump(mode="json")
    report = build_report(data_dir=settings.data_dir, source=source, model=model, media=media)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    to_write = [(args.output, payload)] if args.output else []
    if args.shareable_output:
        from .evidence import sanitize_evidence
        payload = json.dumps(sanitize_evidence(report), ensure_ascii=False, indent=2) + "\n"
        to_write.append((args.shareable_output, payload))
    for path, value in to_write:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        except OSError as error:
            parser.exit(2, f"Cannot write diagnostic report: {error}\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
