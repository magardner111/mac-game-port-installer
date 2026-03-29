"""
Persistent app settings stored as JSON next to the script.
"""

import json
from pathlib import Path

_FILE = Path(__file__).parent / "settings.json"

_DEFAULTS: dict = {
    "auto_update": False,
}


def load() -> dict:
    if _FILE.exists():
        try:
            return {**_DEFAULTS, **json.loads(_FILE.read_text())}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(data: dict) -> None:
    _FILE.write_text(json.dumps(data, indent=2))


def get(key: str):
    return load().get(key, _DEFAULTS.get(key))


def set(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)
