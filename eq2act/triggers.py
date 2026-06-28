"""Regex trigger engine — 'ding' on log events you care about.

Triggers live in config/triggers.json and are fully editable from the web UI.
Each trigger:
  { "id", "name", "pattern", "enabled", "sound", "tts", "say", "cooldown" }

We match the trigger pattern against the *de-timestamped* message text so users
write natural regexes (e.g. "has joined the group" or "Brother Shen .* casts").
A per-trigger cooldown stops machine-gun dings on DoT ticks.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class Trigger:
    id: str
    name: str
    pattern: str
    enabled: bool = True
    sound: str = "ding"       # sound key the browser knows
    tts: bool = False         # speak via browser SpeechSynthesis
    say: str = ""             # text to show / speak; supports \1 group refs, or {0}
    cooldown: float = 2.0     # seconds
    _re: Optional[re.Pattern] = field(default=None, repr=False, compare=False)
    _last: float = field(default=0.0, repr=False, compare=False)

    def compile(self) -> Optional[str]:
        try:
            self._re = re.compile(self.pattern)
            return None
        except re.error as e:
            self._re = None
            return str(e)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "pattern": self.pattern,
            "enabled": self.enabled, "sound": self.sound, "tts": self.tts,
            "say": self.say, "cooldown": self.cooldown,
            "valid": self._re is not None,
        }


class TriggerEngine:
    def __init__(self, path: Path, on_fire: Optional[Callable[[dict], None]] = None):
        self.path = Path(path)
        self.on_fire = on_fire
        self.triggers: List[Trigger] = []
        self.load()

    # -- persistence ----------------------------------------------------------
    def load(self) -> None:
        self.triggers = []
        if self.path.exists():
            data = json.loads(self.path.read_text() or "[]")
            for d in data:
                t = Trigger(
                    id=str(d.get("id") or _new_id()),
                    name=d.get("name", "trigger"),
                    pattern=d.get("pattern", ""),
                    enabled=bool(d.get("enabled", True)),
                    sound=d.get("sound", "ding"),
                    tts=bool(d.get("tts", False)),
                    say=d.get("say", ""),
                    cooldown=float(d.get("cooldown", 2.0)),
                )
                t.compile()
                self.triggers.append(t)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([t.to_dict() for t in self.triggers], indent=2))

    # -- crud (used by the UI) ------------------------------------------------
    def replace_all(self, items: List[dict]) -> None:
        self.triggers = []
        for d in items:
            t = Trigger(
                id=str(d.get("id") or _new_id()),
                name=d.get("name", "trigger"),
                pattern=d.get("pattern", ""),
                enabled=bool(d.get("enabled", True)),
                sound=d.get("sound", "ding"),
                tts=bool(d.get("tts", False)),
                say=d.get("say", ""),
                cooldown=float(d.get("cooldown", 2.0)),
            )
            t.compile()
            self.triggers.append(t)
        self.save()

    def list(self) -> List[dict]:
        return [t.to_dict() for t in self.triggers]

    # -- the hot path ---------------------------------------------------------
    def feed(self, msg: str, ts: float, now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        for t in self.triggers:
            if not t.enabled or t._re is None:
                continue
            m = t._re.search(msg)
            if not m:
                continue
            if now - t._last < t.cooldown:
                continue
            t._last = now
            text = t.say or t.name
            try:
                text = m.expand(text) if "\\" in text else text
            except (re.error, IndexError):
                pass
            if self.on_fire:
                self.on_fire({
                    "type": "trigger",
                    "trigger_id": t.id,
                    "name": t.name,
                    "sound": t.sound,
                    "tts": t.tts,
                    "text": text,
                    "match": m.group(0),
                    "ts": ts,
                })


_counter = [0]


def _new_id() -> str:
    _counter[0] += 1
    return "t%d_%d" % (int(time.time()) % 100000, _counter[0])
