import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "WECHAT_AGENT_DATA_DIR",
                str(
                    Path.home()
                    / (
                        "Library/Application Support/Wechat-Agent"
                        if sys.platform == "darwin"
                        else ".local/share/wechat-agent"
                    )
                ),
            )
        )
    )
    source_url: str = field(
        default_factory=lambda: os.environ.get("WX_SOURCE_URL", "http://127.0.0.1:9100")
    )
    source_account: str = field(
        default_factory=lambda: os.environ.get("WX_ACCOUNT_ID", "")
    )
    self_id: str = field(default_factory=lambda: os.environ.get("WX_SELF_ID", ""))
    model: str = field(
        default_factory=lambda: os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    )
    daily_token_limit: int = 100000
    max_output_tokens: int = 2000

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        return self

    def source_endpoint(self):
        parsed = urlparse(self.source_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
        ):
            raise ValueError("采集地址必须是本机回环 HTTP 地址，且不含凭据")
        return self.source_url.rstrip("/")


def secret(name: str):
    value = os.environ.get(name)
    if value:
        return value
    try:
        import keyring

        return keyring.get_password("Wechat-Agent", name)
    except Exception:
        return None
