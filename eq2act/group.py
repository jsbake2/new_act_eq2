"""Figure out who counts as 'my side' so the parse only tracks my group + pets.

EQ2 gives us several signals, in rough order of reliability:
  * /whogroup roster lines:  `Gaptia Lvl 125 Templar (Group)`
  * /whoraid roster lines:   `[1 Main Tank] Gaptia (Templar)`
  * /con results:            `You consider Gaptia...`
  * chat-filtered events:    `Gaptia has joined the group.` / `... left the group.`
  * pets:                    folded onto their owner by the parser, so a pet is
                             friendly iff its owner is friendly.

Modes:
  solo  -> only me + my pets
  group -> me + group roster + their pets   (default; this is the ACT use-case)
  raid  -> me + group + raid roster + their pets
  all   -> track everyone (no filtering)
"""
from __future__ import annotations

import re
from typing import Optional, Set

from .models import CombatEvent

WHOGROUP_RE = re.compile(r"^(?P<name>[A-Za-z]+) Lvl \d+ .+\(Group\)\s*$")
WHOGROUP_RE2 = re.compile(r"^(?P<name>[A-Za-z]+) Lvl \d+ [A-Za-z ]+$")
WHORAID_RE = re.compile(r"^\[\d+ [^\]]+\] (?P<name>[A-Za-z]+) \([^\)]+\)\s*$")
CONSIDER_RE = re.compile(r"^You consider (?P<name>[A-Za-z]+)\b")
JOIN_GROUP_RE = re.compile(r"^(?P<name>[A-Za-z]+) has joined the group\.$")
LEAVE_GROUP_RE = re.compile(r"^(?P<name>[A-Za-z]+) has left the group\.$")
JOIN_RAID_RE = re.compile(r"^(?P<name>[A-Za-z]+) has joined the raid\.$")
LEAVE_RAID_RE = re.compile(r"^(?P<name>[A-Za-z]+) has left the raid\.$")
INVITE_RE = re.compile(r"^You (?:have invited|invite) (?P<name>[A-Za-z]+) "
                       r"to join (?:your|the) group\.$")
DISBAND_RE = re.compile(r"(?:The group has disbanded|has disbanded the raid)\.$")


class GroupTracker:
    def __init__(self, me: str = "You", mode: str = "group"):
        self.me = me or "You"
        self.mode = mode
        self.group: Set[str] = set()
        self.raid: Set[str] = set()
        self.manual: Set[str] = set()       # names the user pinned in the UI
        self.pet_owner: dict = {}           # pet display name -> owner
        self.enemies: Set[str] = set()      # inferred hostiles
        # positively-confirmed players, grown from the heal network anchored on
        # `me`: someone who heals (or is healed by) a known player is a player.
        # Traps/DoTs/mobs never heal your group, so this stays clean.
        self.players: Set[str] = {self.me}

    @staticmethod
    def _canon(name: str) -> str:
        """EQ2 names are first-letter-capitalised; the /invite line echoes what
        you typed (often lowercase), so canonicalise to avoid Adoration vs
        adoration duplicates."""
        return name[:1].upper() + name[1:] if name else name

    # -- ingest a non-combat roster/membership line ---------------------------
    def observe_text(self, msg: str) -> Optional[str]:
        """Feed a raw (already de-timestamped) message; returns an event word
        if membership changed, else None."""
        m = WHOGROUP_RE.match(msg) or WHOGROUP_RE2.match(msg)
        if m and "Lvl" in msg:
            n = self._canon(m.group("name"))
            self.group.add(n); self.players.add(n)
            return "group_roster"
        m = WHORAID_RE.match(msg)
        if m:
            n = self._canon(m.group("name"))
            self.raid.add(n); self.players.add(n)
            return "raid_roster"
        m = CONSIDER_RE.match(msg)
        if m:
            # consider marks a target we care about; treat as group hint
            n = self._canon(m.group("name"))
            self.group.add(n); self.players.add(n)
            return "consider"
        m = JOIN_GROUP_RE.match(msg) or INVITE_RE.match(msg)
        if m:
            n = self._canon(m.group("name"))
            self.group.add(n); self.players.add(n)
            return "join_group"
        m = LEAVE_GROUP_RE.match(msg)
        if m:
            self.group.discard(self._canon(m.group("name")))
            return "leave_group"
        m = JOIN_RAID_RE.match(msg)
        if m:
            n = self._canon(m.group("name"))
            self.raid.add(n); self.players.add(n)
            return "join_raid"
        m = LEAVE_RAID_RE.match(msg)
        if m:
            self.raid.discard(self._canon(m.group("name")))
            return "leave_raid"
        if DISBAND_RE.search(msg):
            self.group.clear()
            return "disband"
        return None

    # -- learn pet ownership + the player set from combat events --------------
    def observe_event(self, ev: CombatEvent) -> None:
        if ev.owner:
            self.pet_owner[ev.attacker] = ev.owner
            if ev.owner in self.players:
                self.players.add(ev.attacker)
        # heal network: grow `players` outward from known players
        if ev.kind in ("heal", "ward", "refresh"):
            h, v = ev.credited_to, ev.victim
            if v in self.players and h and not self.looks_like_mob(h):
                self.players.add(h)
            if h in self.players and v and not self.looks_like_mob(v):
                self.players.add(v)

    def note_enemy(self, name: str) -> None:
        if name and name != self.me and name not in self.players:
            self.enemies.add(name)

    def infer_from_damage(self, attacker: str, victim: str) -> None:
        """Classify both sides from a damage event, with no /whogroup needed:

          * a known player attacking X  -> X is an enemy
          * X attacking a known player   -> X is an enemy
          * anyone (not a mob) attacking a known enemy -> they're on my side
          * a known enemy attacking anyone (not a mob)  -> that target is my side

        The last two are 'co-combat': everyone shooting at my mobs, and everyone
        my mobs shoot at, is my group/raid — which is what you actually want to
        see when you never type /whogroup.
        """
        if not attacker or not victim or attacker == victim:
            return
        am, vm = self.looks_like_mob(attacker), self.looks_like_mob(victim)
        ap = attacker == self.me or attacker in self.players
        vp = victim == self.me or victim in self.players

        # enemy detection (anchored on confirmed players)
        if ap and not vp and not vm:
            self.note_enemy(victim)
        elif vp and not ap and not am:
            self.note_enemy(attacker)

        # co-combat ally detection (anchored on confirmed enemies)
        if victim in self.enemies and not am and not ap and attacker != self.me:
            self.add_player(attacker)
        if attacker in self.enemies and not vm and not vp and victim != self.me:
            self.add_player(victim)

    def add_player(self, name: str) -> None:
        if name and not self.looks_like_mob(name):
            self.players.add(name)
            self.enemies.discard(name)   # ally wins over a stale enemy guess

    # -- membership queries ---------------------------------------------------
    def friendly_names(self) -> Set[str]:
        names = {self.me} | self.manual
        if self.mode in ("group", "raid"):
            names |= self.group
        if self.mode == "raid":
            names |= self.raid
        return names

    @staticmethod
    def looks_like_mob(name: str) -> bool:
        """A combatant name is a mob if it has an article prefix OR contains a
        space — EQ2 player tokens in the combat log are always a single word
        ('Prax'), while mobs are 'a fierce badger' / 'Vicathyra the Weaver' /
        'Brother Shen'. This is ACT's documented 'space in name = mob' heuristic.
        (Pets are folded onto their single-word owner before we get here.)"""
        return " " in name or name.lower().startswith(("a`", "an`"))

    @staticmethod
    def looks_like_player(name: str) -> bool:
        """EQ2 character names are a single capitalised, alphabetic token with no
        spaces (e.g. Prax, Lantik). Mobs are 'a/an/the ...' or multi-word proper
        names ('Vicathyra the Weaver'). This is a strong (not perfect) signal —
        used only as a fallback; real damage relationships always override it."""
        return (bool(name) and name[:1].isupper() and name.isalpha()
                and 2 <= len(name) <= 20 and " " not in name)

    def is_friend(self, name: str) -> bool:
        if not name:
            return False
        check = self.pet_owner.get(name, name)
        if check == self.me:
            return True
        if self.mode == "solo":
            return False                      # only me + my pets (pets -> me above)
        # confirmed ally (heal network, co-combat, roster, group-join) wins
        if check in self.players or check in self.friendly_names():
            return True
        # confirmed / obvious enemy
        if check in self.enemies or self.looks_like_mob(check):
            return False
        # not yet confirmed: a single-token capitalised name is almost certainly a
        # player (groupmate) — show them now; if they're really a mob, the first
        # hit from me/an ally flips them to enemy. Multi-word unknowns stay foes
        # except in 'all' mode.
        if self.looks_like_player(check):
            return True
        return self.mode == "all"

    # -- persistence: remember this character's allies across restarts --------
    def export_allies(self) -> list:
        return sorted(n for n in self.players if n != self.me)

    def import_allies(self, names) -> None:
        for n in names or []:
            if n and n != self.me:
                self.players.add(n)

    def set_mode(self, mode: str) -> None:
        if mode in ("solo", "group", "raid", "all"):
            self.mode = mode

    def set_me(self, name: str) -> None:
        if name:
            self.me = name
            self.players.add(name)

    def snapshot(self) -> dict:
        return {
            "me": self.me,
            "mode": self.mode,
            "group": sorted(self.group),
            "raid": sorted(self.raid),
            "manual": sorted(self.manual),
            "pets": self.pet_owner,
        }
