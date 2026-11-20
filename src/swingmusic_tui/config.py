"""Persistent configuration for swingmusic-tui."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "swingmusic-tui"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class AppConfig:
    server_url: str = ""
    username: str = ""
    access_token: str = ""
    refresh_token: str = ""
    sort_mode: str = "newest"  # newest, oldest, title_asc, title_desc, artist_asc, album_asc, duration_asc, duration_desc, default
    volume: int = 85
    shuffle: bool = False
    repeat: str = "off"  # off, all, one
    quality: str = "original"

    @classmethod
    def load(cls) -> "AppConfig":
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                valid = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
                return cls(**valid)
        except Exception:
            pass
        return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass
