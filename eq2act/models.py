"""Core data types shared across the parser, encounter engine and server."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---- a single parsed line of combat -----------------------------------------

@dataclass
class CombatEvent:
    """One meaningful thing that happened in the log.

    `kind` is one of: damage, heal, ward, refresh, death, miss.
    Names are already normalised (YOU/YOUR -> the logging character, pets folded
    onto their owner where applicable — see parser.normalise_actor).
    """
    ts: float                      # epoch seconds
    kind: str
    attacker: str = ""
    victim: str = ""
    skill: str = ""                # ability name, or "Auto Attack"
    amount: int = 0
    dtype: str = ""                # slashing / cold / heal / ward ...
    crit: bool = False
    multi: bool = False            # flurry / multi-attack / aoe / double attack
    miss_reason: str = ""          # for kind == miss
    owner: Optional[str] = None    # set when attacker is a pet -> its owner
    raw: str = ""

    @property
    def credited_to(self) -> str:
        """Who gets credit for this event's output — pet damage rolls to owner."""
        return self.owner or self.attacker


# ---- per-combatant rollup inside one fight ----------------------------------

@dataclass
class SkillStat:
    name: str
    hits: int = 0
    crits: int = 0
    total: int = 0
    max_hit: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "hits": self.hits, "crits": self.crits,
            "total": self.total, "max_hit": self.max_hit,
            "crit_pct": (100.0 * self.crits / self.hits) if self.hits else 0.0,
        }


@dataclass
class Combatant:
    name: str
    is_friend: bool = False
    # outgoing damage
    damage: int = 0
    hits: int = 0
    crits: int = 0
    misses: int = 0
    max_hit: int = 0
    # other roles
    healing: int = 0
    warding: int = 0
    damage_taken: int = 0
    deaths: int = 0
    skills: dict = field(default_factory=dict)   # name -> SkillStat
    first_ts: float = 0.0
    last_ts: float = 0.0

    def add_skill_hit(self, skill: str, amount: int, crit: bool) -> None:
        s = self.skills.get(skill)
        if s is None:
            s = SkillStat(skill)
            self.skills[skill] = s
        s.hits += 1
        s.total += amount
        if crit:
            s.crits += 1
        if amount > s.max_hit:
            s.max_hit = amount

    def dps(self, duration: float) -> float:
        return self.damage / duration if duration > 0 else 0.0

    def crit_pct(self) -> float:
        return (100.0 * self.crits / self.hits) if self.hits else 0.0

    def to_dict(self, duration: float, total_friendly_damage: int) -> dict:
        return {
            "name": self.name,
            "is_friend": self.is_friend,
            "damage": self.damage,
            "dps": self.dps(duration),
            "hits": self.hits,
            "crits": self.crits,
            "crit_pct": self.crit_pct(),
            "misses": self.misses,
            "max_hit": self.max_hit,
            "healing": self.healing,
            "warding": self.warding,
            "damage_taken": self.damage_taken,
            "deaths": self.deaths,
            "pct": (100.0 * self.damage / total_friendly_damage)
                   if total_friendly_damage else 0.0,
            "skills": sorted(
                (s.to_dict() for s in self.skills.values()),
                key=lambda d: d["total"], reverse=True,
            ),
        }
