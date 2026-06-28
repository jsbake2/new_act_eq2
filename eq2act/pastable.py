"""Build the pastable group parse you drop into EQ2 group/raid chat.

Format (requested layout):

    Brother Shen: 3.59B dps | max hit 17.70B
    Group max hit: 17.70B by Gaptia (Coordinated Wounds)
    1. Gaptia: 3.54B dps
    2. Maergoth: 54.07M dps
    ...
"""
from __future__ import annotations

from typing import List, Optional, Tuple


def _abbrev(n: float) -> str:
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.2f}{suf}"
    return f"{n:.0f}"


def _dur(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def mob_max_hit(summary: dict) -> int:
    """The mob's own biggest hit (incoming damage onto the group). Prefer the
    named encounter mob; otherwise the hardest-hitting enemy."""
    enemies = summary.get("enemies", [])
    named = summary.get("name")
    for e in enemies:
        if e.get("name") == named:
            return e.get("max_hit", 0)
    return max((e.get("max_hit", 0) for e in enemies), default=0)


def group_max_hit(summary: dict) -> Tuple[int, str, str]:
    """Return (max_hit, who, ability) across the friendly combatants."""
    best = (0, "", "")
    for c in summary.get("combatants", []):
        if c.get("max_hit", 0) > best[0]:
            ability = ""
            for sk in c.get("skills", []):
                if sk.get("max_hit", 0) == c["max_hit"]:
                    ability = sk["name"]
                    break
            best = (c["max_hit"], c["name"], ability)
    return best


def format_parse(summary: dict, top: int = 6, title: str = "EQ2ACT") -> str:
    name = summary.get("name", "Unknown")
    dur = summary.get("duration", 1.0)
    raid_dps = summary.get("raid_dps", 0.0)
    mob_mh = mob_max_hit(summary)
    gmh, who, ability = group_max_hit(summary)

    lines: List[str] = []
    # mob name: DPS | the MOB's max hit (incoming)
    lines.append(f"{name}: {_abbrev(raid_dps)} dps | max hit {_abbrev(mob_mh)} "
                 f"({_dur(dur)})")
    # GROUP MAX HIT AND WHO DID IT
    if who:
        abil = f" ({ability})" if ability else ""
        lines.append(f"Group max hit: {_abbrev(gmh)} by {who}{abil}")
    # per-member DPS
    for i, c in enumerate(summary.get("combatants", [])[:top], start=1):
        lines.append(f"{i}. {c['name']}: {_abbrev(c['dps'])} dps")
    return "\n".join(lines)
