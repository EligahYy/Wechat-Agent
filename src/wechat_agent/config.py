import json
import os
import sys
import tempfile
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
    max_output_tokens: int = 4000

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        source_config = self.data_dir / "source-binding.json"
        if source_config.exists():
            binding = json.loads(source_config.read_text())
            if not os.environ.get("WX_ACCOUNT_ID"):
                self.source_account = binding["account_id"]
            if not os.environ.get("WX_SELF_ID"):
                self.self_id = binding["account_id"]
        return self

    def bind_source(self, account_id):
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("账号标识不能为空")
        for name in ("WX_ACCOUNT_ID", "WX_SELF_ID"):
            if os.environ.get(name) and os.environ[name] != account_id:
                raise ValueError("终端环境变量与所选账号冲突，请更新环境变量后重启")
        fd, name = tempfile.mkstemp(prefix=".source-", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"account_id": account_id}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.data_dir / "source-binding.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)
        self.source_account = self.self_id = account_id

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
