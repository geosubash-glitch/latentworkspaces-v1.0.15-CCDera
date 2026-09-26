"""Small persistent preferences and the log file location."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

APP_DIR_NAME = "Latent Studio"


def config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def default_photo_folder() -> str:
    home = os.path.expanduser("~")
    for name in ("Pictures", "My Pictures", "Photos"):
        candidate = os.path.join(home, name)
        if os.path.isdir(candidate):
            return candidate
    return home


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.data: Dict[str, Any] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self) -> None:
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass
