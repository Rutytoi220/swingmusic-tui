"""Persistent configuration for swingmusic-tui."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "swingmusic-tui"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSION_FILE = CONFIG_DIR / "session.json"


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


def save_session(queue_dicts: list[dict[str, Any]], index: int, position: float) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "queue": queue_dicts,
        "index": index,
        "position": max(0.0, float(position)),
    }
    tmp = SESSION_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    os.replace(tmp, SESSION_FILE)


def load_session() -> dict[str, Any] | None:
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("queue"), list):
                return data
    except Exception:
        pass
    return None
