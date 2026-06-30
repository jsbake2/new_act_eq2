"""Combine several fights into one aggregate summary (ACT's 'zone / All' roll-up).

Takes a list of fight details ({"summary":..., "chart":...}) and returns a single
detail in the exact same shape, so the dashboard's table / chart / breakdown
render it with no special-casing.
"""
from __future__ import annotations

from typing import List


def _blank_combatant(name: str, is_friend: bool) -> dict:
    return {"name": name, "is_friend": is_friend, "damage": 0, "dps": 0.0,
            "hits": 0, "crits": 0, "crit_pct": 0.0, "misses": 0, "max_hit": 0,
            "healing": 0, "warding": 0, "threat": 0, "damage_taken": 0,
            "deaths": 0, "pct": 0.0, "skills": {}}


def _merge_skill(into: dict, sk: dict) -> None:
    s = into.setdefault(sk["name"], {"name": sk["name"], "hits": 0, "crits": 0,
                                     "total": 0, "max_hit": 0})
    s["hits"] += sk.get("hits", 0)
    s["crits"] += sk.get("crits", 0)
    s["total"] += sk.get("total", 0)
    s["max_hit"] = max(s["max_hit"], sk.get("max_hit", 0))


def combine(details: List[dict], name: str = "Combined") -> dict:
    summaries = [d["summary"] for d in details if d and d.get("summary")]
    charts = [d.get("chart") or {"seconds": [], "series": {}} for d in details if d]
    if not summaries:
        return {"summary": {"name": name, "duration": 0, "total_damage": 0,
                            "raid_dps": 0, "combatants": [], "enemies": [],
                            "active": False}, "chart": {"seconds": [], "series": {}}}

    friends: dict = {}
    enemies: dict = {}
    total_dur = 0.0
    for s in summaries:
        total_dur += s.get("duration", 0) or 0
        for c in s.get("combatants", []):
            acc = friends.get(c["name"]) or _blank_combatant(c["name"], c.get("is_friend", True))
            friends[c["name"]] = acc
            for k in ("damage", "hits", "crits", "misses", "healing", "warding",
                      "threat", "damage_taken", "deaths"):
                acc[k] += c.get(k, 0)
            acc["max_hit"] = max(acc["max_hit"], c.get("max_hit", 0))
            for sk in c.get("skills", []):
                _merge_skill(acc["skills"], sk)
        for e in s.get("enemies", []):
            acc = enemies.get(e["name"]) or _blank_combatant(e["name"], False)
            enemies[e["name"]] = acc
            acc["damage_taken"] += e.get("damage_taken", 0)
            acc["deaths"] += e.get("deaths", 0)
            acc["damage"] += e.get("damage", 0)
            acc["max_hit"] = max(acc["max_hit"], e.get("max_hit", 0))

    total_dur = max(total_dur, 1.0)
    total_dmg = sum(c["damage"] for c in friends.values())
    for acc in friends.values():
        acc["dps"] = acc["damage"] / total_dur
        acc["crit_pct"] = (100.0 * acc["crits"] / acc["hits"]) if acc["hits"] else 0.0
        acc["pct"] = (100.0 * acc["damage"] / total_dmg) if total_dmg else 0.0
        skills = []
        for s in acc["skills"].values():
            s["crit_pct"] = (100.0 * s["crits"] / s["hits"]) if s["hits"] else 0.0
            skills.append(s)
        acc["skills"] = sorted(skills, key=lambda d: d["total"], reverse=True)

    combatants = sorted(friends.values(), key=lambda d: d["damage"], reverse=True)
    enemy_list = sorted(enemies.values(), key=lambda d: d["damage_taken"], reverse=True)

    # chart: lay each fight's per-second buckets end-to-end (continuous combat time)
    names = [c["name"] for c in combatants]
    series = {n: [] for n in names}
    seconds: List[int] = []
    offset = 0
    for ch in charts:
        secs = ch.get("seconds", [])
        L = len(secs) or 1
        for n in names:
            arr = list(ch.get("series", {}).get(n, []))
            if len(arr) < L:
                arr += [0] * (L - len(arr))
            series[n].extend(arr[:L])
        seconds.extend(range(offset, offset + L))
        offset += L

    summary = {
        "id": "combo", "name": name, "duration": total_dur,
        "total_damage": total_dmg, "raid_dps": total_dmg / total_dur,
        "combatants": combatants, "enemies": enemy_list,
        "active": False, "last": False, "fights": len(summaries),
    }
    return {"summary": summary, "chart": {"seconds": seconds, "series": series}}
