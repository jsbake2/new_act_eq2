"""Group CombatEvents into fights and roll up the stats the dashboard needs.

A fight starts on the first damage event and ends after `timeout` seconds with no
combat activity.  We keep per-second damage buckets per friendly combatant so the
front-end can draw Grafana-style stacked DPS-over-time charts.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from .group import GroupTracker
from .models import Combatant, CombatEvent


class Fight:
    _next_id = 1

    def __init__(self, start_ts: float, zone: str = ""):
        self.id = Fight._next_id
        Fight._next_id += 1
        self.start_ts = start_ts
        self.last_ts = start_ts
        self.end_ts: Optional[float] = None
        self.zone = zone
        self.name = "Unknown"
        self.combatants: Dict[str, Combatant] = {}
        self.enemies: Dict[str, Combatant] = {}
        # per-second buckets: second_offset -> {name: damage}
        self.buckets: Dict[int, Dict[str, int]] = {}
        self.enemy_damage: Dict[str, int] = {}   # for naming the fight
        self.events: List[CombatEvent] = []
        self.closed = False
        # death-based completion: an encounter is "done" when every enemy we
        # engaged has died (ACT-style per-pull splitting).
        self.active_enemies: set = set()
        self.engaged = False
        self.kills = 0
        self.completed = False
        self.complete_ts: Optional[float] = None

    # -- lifetime -------------------------------------------------------------
    @property
    def duration(self) -> float:
        end = self.end_ts if self.end_ts is not None else self.last_ts
        return max(end - self.start_ts, 1.0)

    def _combatant(self, name: str, friendly: bool) -> Combatant:
        table = self.combatants if friendly else self.enemies
        c = table.get(name)
        if c is None:
            c = Combatant(name, is_friend=friendly)
            c.first_ts = self.last_ts
            table[name] = c
        return c

    def add(self, ev: CombatEvent, group: GroupTracker) -> None:
        self.last_ts = ev.ts
        self.events.append(ev)
        sec = int(ev.ts - self.start_ts)

        attacker_name = ev.credited_to
        atk_friend = group.is_friend(attacker_name)

        if ev.kind == "damage":
            vic_friend = group.is_friend(ev.victim)
            # outgoing damage (skip when unattributed, e.g. falling/reflect)
            if attacker_name:
                atk = self._combatant(attacker_name, atk_friend)
                atk.damage += ev.amount
                atk.hits += 1
                atk.last_ts = ev.ts
                if ev.crit:
                    atk.crits += 1
                if ev.amount > atk.max_hit:
                    atk.max_hit = ev.amount
                label = ("(pet) " + ev.skill) if ev.owner else ev.skill
                atk.add_skill_hit(label, ev.amount, ev.crit)
            # incoming damage
            vic = self._combatant(ev.victim, vic_friend)
            vic.damage_taken += ev.amount
            vic.last_ts = ev.ts
            # bucket + fight naming (only friendly damage onto an enemy)
            if attacker_name and atk_friend and not vic_friend:
                self.buckets.setdefault(sec, {})
                self.buckets[sec][attacker_name] = (
                    self.buckets[sec].get(attacker_name, 0) + ev.amount)
                self.enemy_damage[ev.victim] = (
                    self.enemy_damage.get(ev.victim, 0) + ev.amount)
                group.note_enemy(ev.victim)
            # Track every mob we're actively killing — including ones hit only by
            # an ally we haven't classified yet (looks_like_player) — so a
            # multi-mob pull stays one encounter until ALL of them are dead.
            if (not vic_friend and attacker_name
                    and (atk_friend or group.looks_like_player(attacker_name))):
                self.active_enemies.add(ev.victim)
                self.engaged = True
            self._rename()

        elif ev.kind == "heal":
            c = self._combatant(attacker_name, atk_friend)
            c.healing += ev.amount
            c.last_ts = ev.ts
            c.add_skill_hit(("(pet) " if ev.owner else "") + ev.skill + " (heal)",
                            ev.amount, ev.crit)
        elif ev.kind == "ward":
            c = self._combatant(attacker_name, atk_friend)
            c.warding += ev.amount
            c.last_ts = ev.ts
        elif ev.kind == "miss":
            c = self._combatant(attacker_name, atk_friend)
            c.misses += 1
        elif ev.kind == "death":
            vic_friend = group.is_friend(ev.victim)
            c = self._combatant(ev.victim, vic_friend)
            c.deaths += 1
            if not vic_friend:
                self.active_enemies.discard(ev.victim)
                self.kills += 1
                # every engaged enemy is dead -> this pull is complete
                if self.engaged and not self.active_enemies:
                    self.completed = True
                    self.complete_ts = ev.ts

    def _rename(self) -> None:
        if self.enemy_damage:
            self.name = max(self.enemy_damage.items(), key=lambda kv: kv[1])[0]

    def close(self, end_ts: Optional[float] = None) -> None:
        if not self.closed:
            self.end_ts = end_ts if end_ts is not None else self.last_ts
            self.closed = True

    # -- output ---------------------------------------------------------------
    def total_friendly_damage(self) -> int:
        return sum(c.damage for c in self.combatants.values())

    def chart_series(self) -> dict:
        """Stacked per-second damage for each friendly combatant."""
        dur = int(self.duration) + 1
        names = sorted(self.combatants.keys(),
                       key=lambda n: self.combatants[n].damage, reverse=True)
        series = {n: [0] * dur for n in names}
        for sec, pername in self.buckets.items():
            if 0 <= sec < dur:
                for n, dmg in pername.items():
                    if n in series:
                        series[n][sec] += dmg
        return {"seconds": list(range(dur)), "series": series}

    def summary(self) -> dict:
        dur = self.duration
        total = self.total_friendly_damage()
        friends = sorted((c.to_dict(dur, total) for c in self.combatants.values()),
                         key=lambda d: d["damage"], reverse=True)
        enemies = sorted((c.to_dict(dur, 1) for c in self.enemies.values()),
                         key=lambda d: d["damage_taken"], reverse=True)
        return {
            "id": self.id,
            "name": self.name,
            "zone": self.zone,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration": dur,
            "total_damage": total,
            "raid_dps": total / dur if dur else 0.0,
            "closed": self.closed,
            "combatants": friends,
            "enemies": enemies,
        }


class EncounterManager:
    """Streams events in, opens/closes fights, and notifies on changes."""

    def __init__(self, group: GroupTracker, timeout: float = 12.0,
                 on_change: Optional[Callable[[], None]] = None):
        self.group = group
        self.timeout = timeout
        self.current: Optional[Fight] = None
        self.history: List[Fight] = []
        self.last_closed: Optional[Fight] = None   # stays until a new fight starts
        self.zone = ""                             # current zone (set by engine)
        self.on_change = on_change

    def _emit(self) -> None:
        if self.on_change:
            self.on_change()

    # grace after the last mob dies before a new engagement starts a new fight,
    # so post-death DoT ticks / same-instant cleave attach to the finished pull.
    COMPLETE_GRACE = 1.5

    def _close_current(self, end_ts: Optional[float] = None) -> None:
        if not self.current or self.current.closed:
            return
        self.current.close(end_ts)
        self.history.append(self.current)
        if self.current.total_friendly_damage() > 0:
            self.last_closed = self.current
        self.current = None
        self._emit()

    def feed(self, ev: CombatEvent) -> None:
        self.group.observe_event(ev)
        # Bidirectional enemy inference (see GroupTracker.infer_from_damage):
        # names proper-titled bosses and traps that the article heuristic misses.
        if ev.kind == "damage":
            self.group.infer_from_damage(ev.credited_to, ev.victim)

        cur = self.current
        if cur and not cur.closed:
            # (1) inactivity fallback — for mobs that flee/despawn without a death
            if ev.ts - cur.last_ts > self.timeout:
                self._close_current(cur.last_ts)
            # (2) death-based split — the pull is complete (all engaged mobs
            #     dead); a fresh friendly engagement after the grace = new pull
            elif (cur.completed and ev.kind == "damage" and ev.attacker
                  and self.group.is_friend(ev.credited_to)
                  and not self.group.is_friend(ev.victim)
                  and (ev.ts - (cur.complete_ts or cur.last_ts)) > self.COMPLETE_GRACE):
                self._close_current(cur.complete_ts or cur.last_ts)

        if ev.kind == "damage":
            if self.current is None or self.current.closed:
                self.current = Fight(ev.ts, zone=self.zone)
            self.current.add(ev, self.group)
        elif self.current and not self.current.closed:
            self.current.add(ev, self.group)

    def tick(self, now: Optional[float] = None) -> None:
        """Call periodically so a fight closes even when the log goes quiet.
        A completed pull closes after the grace; an unfinished one on timeout."""
        if not self.current or self.current.closed:
            return
        now = now if now is not None else time.time()
        cur = self.current
        if cur.completed and (now - (cur.complete_ts or cur.last_ts)) > self.COMPLETE_GRACE:
            self._close_current(cur.complete_ts or cur.last_ts)
        elif now - cur.last_ts > self.timeout:
            self._close_current(cur.last_ts)

    def all_fights(self) -> List[Fight]:
        fights = list(self.history)
        if self.current is not None:
            fights.append(self.current)
        return fights

    def fight_by_id(self, fid: int) -> Optional[Fight]:
        for f in self.all_fights():
            if f.id == fid:
                return f
        return None
