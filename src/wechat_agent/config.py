"""Local paths; loading settings does not create data or contact services."""

from dataclasses import dataclass
import os
from pathlib import Path
import platform


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    source_config: Path | None = None
    model_config: Path | None = None

    @classmethod
    def load(cls) -> "Settings":
        if platform.system() == "Darwin":
            default_data = Path.home() / "Library/Application Support/Wechat-Agent"
        else:
            default_data = Path.home() / ".local/share/Wechat-Agent"
        data_dir = Path(os.getenv("WECHAT_AGENT_DATA_DIR") or default_data).expanduser().resolve()
        config_dir = Path.cwd() / ".local/config"
        source_config = config_dir / "source.json"
        model_config = config_dir / "model.json"
        return cls(
            data_dir=data_dir,
            source_config=source_config if source_config.is_file() else None,
            model_config=model_config if model_config.is_file() else None,
        )
