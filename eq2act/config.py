"""Load/save runtime settings (config/settings.json)."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "log_path": "",              # full path to eq2log_<Character>.txt
    "log_dir": "",               # logs folder, for auto-detecting the latest log
    "me": "You",                 # your character name (expands YOU/YOUR)
    "mode": "group",             # solo | group | raid | all
    "encounter_timeout": 12.0,   # seconds of quiet that ends a fight
    "from_start": False,         # replay whole file on launch vs live-only
    "host": "127.0.0.1",
    "port": 8777,
    "paste_title": "EQ2ACT",
    "paste_top": 6,
    "autocopy_enabled": True,     # copy a fight's parse to the clipboard on end
    "autocopy_min_seconds": 30.0, # ...only if the fight lasted at least this long
    "autocopy_min_damage": 0,     # ...and dealt at least this much (0 = no min)
}


class Settings:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text() or "{}"))
            except json.JSONDecodeError:
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def update(self, patch: dict) -> None:
        for k, v in patch.items():
            if k in DEFAULTS:
                self.data[k] = v
        self.save()
