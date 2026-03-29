"""
Persistent app settings stored as JSON in the platform Application Support directory.
"""

import json
import sys
from pathlib import Path


def _settings_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "GamePortInstaller"
    elif sys.platform == "win32":
        import os
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "GamePortInstaller"
    else:
        base = Path.home() / ".local" / "share" / "GamePortInstaller"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


_FILE = _settings_path()

_DEFAULTS: dict = {
    "auto_update": False,
}


def load() -> dict:
    if _FILE.exists():
        try:
            return {**_DEFAULTS, **json.loads(_FILE.read_text())}
        except json.JSONDecodeError:
            pass
    return dict(_DEFAULTS)


def save(data: dict) -> None:
    _FILE.write_text(json.dumps(data, indent=2))


def get(key: str):
    return load().get(key, _DEFAULTS.get(key))


def set_value(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)
