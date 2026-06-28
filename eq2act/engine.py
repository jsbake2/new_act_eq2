"""The engine wires every piece together: a raw log line goes in, parsed events
update the encounter, triggers fire, finished fights persist, and listeners
(the SSE stream) get poked to refresh the dashboard."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from .config import Settings
from .discover import (char_from_path, find_latest_log, find_log_dir,
                       _all_logs)
from .encounter import EncounterManager, Fight
from .group import GroupTracker
import re

from .parser import LINE_RE, Parser
from .storage import FightStore
from .triggers import TriggerEngine

ZONE_RE = re.compile(r"^You have entered (?P<zone>.+?)\.$")


class Engine:
    def __init__(self, settings: Settings, triggers_path: str, db_path: str):
        self.settings = settings
        self.parser = Parser(me=settings.get("me"))
        self.group = GroupTracker(me=settings.get("me"), mode=settings.get("mode"))
        self.store = FightStore(db_path)
        self._listeners: List[Callable[[dict], None]] = []
        self.triggers = TriggerEngine(Path(triggers_path), on_fire=self._on_trigger)
        self.encounters = EncounterManager(
            self.group,
            timeout=float(settings.get("encounter_timeout")),
            on_change=self._on_fight_closed,
        )
        self._lock = threading.Lock()
        self.lines_seen = 0
        self.events_seen = 0
        self._last_emit = 0.0
        self._closed_ids = set()
        self.log_dir = find_log_dir(settings.get("log_dir"))
        self.switch_handler = None      # set by __main__ to repoint the tailer
        self._last_combo = None         # most recent aggregate (for detail/paste)
        self.roster_path = Path(db_path).parent / "roster.json"
        self._load_roster(self.group.me)

    # -- listener plumbing ----------------------------------------------------
    def add_listener(self, fn: Callable[[dict], None]) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[dict], None]) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def _broadcast(self, msg: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(msg)
            except Exception:
                pass

    def _on_trigger(self, payload: dict) -> None:
        self._broadcast(payload)

    def prime_from_log(self, path: str) -> str:
        """On attach we start tailing at the end of the file, so we'd miss the
        'You have entered <zone>' line that fired before we started. Scan the
        existing log for the most recent zone and seed it (this is how we know
        the current zone without having watched you zone in)."""
        import os
        if not path or not os.path.isfile(path):
            return ""
        last_zone = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = LINE_RE.match(line)
                    if not m:
                        continue
                    zm = ZONE_RE.match(m.group("msg"))
                    if zm:
                        last_zone = zm.group("zone").strip()
        except OSError:
            return ""
        if last_zone:
            self.encounters.zone = last_zone
        return last_zone

    # -- ally roster persistence (warm start per character) -------------------
    def _load_roster(self, character: str) -> None:
        import json
        try:
            data = json.loads(self.roster_path.read_text())
            self.group.import_allies(data.get(character, []))
        except (OSError, ValueError):
            pass

    def _save_roster(self) -> None:
        import json
        data = {}
        try:
            data = json.loads(self.roster_path.read_text())
        except (OSError, ValueError):
            pass
        allies = self.group.export_allies()
        if allies:
            data[self.group.me] = allies
            try:
                self.roster_path.parent.mkdir(parents=True, exist_ok=True)
                self.roster_path.write_text(json.dumps(data, indent=2))
            except OSError:
                pass

    def _on_fight_closed(self) -> None:
        # persist any newly-closed fight exactly once, and auto-copy its parse
        newly = []
        for f in self.encounters.history:
            if f.closed and f.id not in self._closed_ids and f.total_friendly_damage() > 0:
                self._closed_ids.add(f.id)
                self.store.save(f.summary(), f.chart_series())
                newly.append(f)
        # auto-copy the most significant newly-closed fight, if it clears the bar
        if newly and self.settings.get("autocopy_enabled"):
            worthy = [f for f in newly
                      if f.duration >= float(self.settings.get("autocopy_min_seconds"))
                      and f.total_friendly_damage() >= int(self.settings.get("autocopy_min_damage"))]
            if worthy:
                best = max(worthy, key=lambda f: f.total_friendly_damage())
                self._auto_copy(best)
        if newly:
            self._save_roster()
        self._broadcast({"type": "fight_closed"})

    def _auto_copy(self, fight) -> None:
        """When a fight ends, drop its parse on the system clipboard."""
        from . import clipboard
        from .pastable import format_parse
        text = format_parse(fight.summary(),
                            top=int(self.settings.get("paste_top")),
                            title=self.settings.get("paste_title"))
        backend = clipboard.copy(text)
        self._broadcast({"type": "paste", "text": text, "auto": True,
                         "backend": backend, "name": fight.name})

    # -- the hot path: one raw log line --------------------------------------
    def feed_line(self, line: str) -> None:
        with self._lock:
            self.lines_seen += 1
            m = LINE_RE.match(line)
            if not m:
                return
            ts = float(m.group("epoch"))
            msg = m.group("msg").rstrip("\r\n")
            # zone changes tag subsequent fights
            zm = ZONE_RE.match(msg)
            if zm:
                self.encounters.zone = zm.group("zone").strip()
            # triggers see every line
            self.triggers.feed(msg, ts)
            # group roster / membership lines
            self.group.observe_text(msg)
            # combat
            ev = self.parser.parse_message(msg, ts, raw=line)
            if ev is not None:
                self.events_seen += 1
                self.encounters.feed(ev)
                self._maybe_emit_live()

    def _maybe_emit_live(self) -> None:
        now = time.time()
        if now - self._last_emit >= 0.5:
            self._last_emit = now
            self._broadcast({"type": "live"})

    # -- periodic housekeeping (called by server timer thread) ----------------
    def tick(self) -> None:
        with self._lock:
            before = self.encounters.current
            self.encounters.tick()
            if before is not None and self.encounters.current is None:
                pass  # on_change already broadcast
            else:
                self._broadcast({"type": "live"})

    # -- snapshots for the API ------------------------------------------------
    def live_summary(self) -> dict:
        cur = self.encounters.current
        if cur is not None and not cur.closed:
            s = cur.summary()
            s["chart"] = cur.chart_series()
            s["active"] = True
            s["last"] = False
            return s
        # no active fight -> keep the last fight up until a new one replaces it
        last = self.encounters.last_closed
        if last is not None:
            s = last.summary()
            s["chart"] = last.chart_series()
            s["active"] = False
            s["last"] = True
            return s
        return {"active": False, "last": False, "id": None,
                "name": "No active fight", "combatants": [], "enemies": [],
                "duration": 0, "total_damage": 0, "raid_dps": 0,
                "chart": {"seconds": [], "series": {}}}

    def fight_list(self) -> List[dict]:
        live = []
        cur = self.encounters.current
        if cur is not None and not cur.closed and cur.total_friendly_damage() > 0:
            s = cur.summary()
            s["live"] = True
            live.append({"id": "live", "name": s["name"], "zone": s.get("zone", ""),
                         "duration": s["duration"], "total_damage": s["total_damage"],
                         "raid_dps": s["raid_dps"], "live": True})
        return live + self.store.list()

    def aggregate(self, ids) -> Optional[dict]:
        """Combine several fights (by id, plus 'live') into one detail."""
        from .aggregate import combine
        details = []
        zones = set()
        for fid in ids:
            d = self.fight_detail(fid)
            if d:
                details.append(d)
                zones.add((d["summary"].get("zone") or "").strip())
        if not details:
            return None
        zones.discard("")
        name = (next(iter(zones)) if len(zones) == 1 else
                (f"{len(zones)} zones" if zones else "Combined"))
        res = combine(details, name=f"{name} — {len(details)} fights")
        self._last_combo = res
        return res

    def fight_detail(self, fid) -> Optional[dict]:
        if fid == "live":
            return {"summary": self.live_summary(),
                    "chart": self.live_summary().get("chart")}
        if fid == "combo":
            return self._last_combo
        rec = self.store.get(int(fid))
        if rec:
            return rec
        f = self.encounters.fight_by_id(int(fid))
        if f:
            return {"summary": f.summary(), "chart": f.chart_series()}
        return None

    # -- settings changes -----------------------------------------------------
    def apply_settings(self, patch: dict) -> None:
        self.settings.update(patch)
        if "me" in patch:
            self.parser.set_me(patch["me"])
            self.group.set_me(patch["me"])
        if "mode" in patch:
            self.group.set_mode(patch["mode"])
        if "encounter_timeout" in patch:
            try:
                self.encounters.timeout = float(patch["encounter_timeout"])
            except (TypeError, ValueError):
                pass

    def switch_character(self, name: str, log_path: str = "") -> None:
        """Called when the watcher detects a different active log. Resets the
        roster/player inference for the new character and closes any open fight."""
        with self._lock:
            if self.encounters.current and not self.encounters.current.closed:
                self.encounters.current.close()
                self.encounters.history.append(self.encounters.current)
                self.encounters.current = None
            self.parser.set_me(name)
            self.group = GroupTracker(me=name, mode=self.settings.get("mode"))
            self.encounters.group = self.group
            self._load_roster(name)     # warm-start this character's known allies
            self.settings.data["me"] = name
            if log_path:
                self.settings.data["log_path"] = log_path
            self.settings.save()
        self._broadcast({"type": "fight_closed"})

    # -- character listing / live switching -----------------------------------
    def list_characters(self) -> List[dict]:
        import os
        out = []
        for p in _all_logs(self.log_dir):
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append({"character": char_from_path(p), "path": p,
                        "mtime": st.st_mtime, "size": st.st_size})
        out.sort(key=lambda d: d["mtime"], reverse=True)
        return out

    def request_switch(self, character: str = "", path: str = "") -> bool:
        """UI asked to follow a different character's log live."""
        if not path and character:
            for c in self.list_characters():
                if c["character"].lower() == character.lower():
                    path = c["path"]
                    break
        if not path:
            return False
        if self.switch_handler:
            self.switch_handler(path, char_from_path(path))
            return True
        # no live tailer wired (rare) — at least update identity
        self.switch_character(char_from_path(path), path)
        return True

    # -- historical range import ----------------------------------------------
    def import_range(self, path: str, me: str = "", start_ts: float = 0.0,
                     end_ts: float = 0.0, mode: str = "all") -> dict:
        """Parse a (sub-range of a) log file offline into fights and save them so
        they appear in the history. Returns a summary of what was imported."""
        import os
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "log file not found"}
        me = me or char_from_path(path)
        parser = Parser(me=me)
        group = GroupTracker(me=me, mode=mode)
        # offline manager: collect closed fights ourselves
        timeout = float(self.settings.get("encounter_timeout"))
        mgr = EncounterManager(group, timeout=timeout)
        last_ts = 0.0
        for line in open(path, encoding="utf-8", errors="replace"):
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group("epoch"))
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                break
            last_ts = ts
            msg = m.group("msg").rstrip("\r\n")
            zm = ZONE_RE.match(msg)
            if zm:
                mgr.zone = zm.group("zone").strip()
            group.observe_text(msg)
            ev = parser.parse_message(msg, ts, raw=line)
            if ev is not None:
                mgr.feed(ev)
        mgr.tick(now=last_ts + timeout + 1)
        saved = []
        for f in mgr.all_fights():
            if f.total_friendly_damage() > 0:
                fid = self.store.save(f.summary(), f.chart_series())
                saved.append({"id": fid, "name": f.name,
                              "total_damage": f.total_friendly_damage(),
                              "duration": f.duration})
        self._broadcast({"type": "fight_closed"})
        return {"ok": True, "character": me, "imported": len(saved),
                "fights": saved}

    def status(self) -> dict:
        return {
            "lines_seen": self.lines_seen,
            "events_seen": self.events_seen,
            "settings": self.settings.data,
            "group": self.group.snapshot(),
            "zone": self.encounters.zone,
            "active_fight": self.encounters.current is not None
                            and not self.encounters.current.closed,
        }
