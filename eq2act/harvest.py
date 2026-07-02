"""Track resource harvesting (gathering, mining, trapping, foraging, …).

EQ2 emits one line per successful harvest, e.g.

    (1782492531)[Thu ...] You gather 3 \\aITEM -1610631990 -385153372:root\\/a from the roots.
    (1782494402)[Fri ...] You mine 10 \\aITEM -2020834341 914639161:lead cluster\\/a from the rugged stones.
    (1781479355)[Sun ...] You acquire a 1 \\aITEM 1994519880 1913240700:deer meat\\/a from the creature den.

A rare pull prints a separate line on the *next* tick:

    (1782494402)[Fri ...] You have found a rare item!

This module is deliberately independent of the combat engine — harvest lines
never match a combat regex, so we simply feed every log line here in parallel.
It rolls up totals per item, per node and per skill category, and (like the ally
roster) persists per-character so totals survive a restart.
"""
from __future__ import annotations

import re
from typing import Optional

# "You gather 3 \aITEM <id> <id>:root\/a from the roots."
# verb + optional past-tense tail (gather/gathered, mine/mined, acquire/acquired…),
# an optional "a" article ("acquire a 1 …"), the qty, the \aITEM…:name\/a token
# and the node ("from the <node>.").
HARVEST_RE = re.compile(
    r"^You (?P<verb>gather|mine|acquire|forage|trap|fell|chop|fish|net|catch|collect)\w* "
    r"(?:a )?(?P<qty>\d+) "
    r"\\aITEM\s+-?\d+\s+-?\d+:(?P<item>[^\\]+)\\/a "
    r"from the (?P<node>.+?)\.$"
)
RARE_RE = re.compile(r"^You have found a rare item!$")

# harvest verb -> EQ2 tradeskill/harvesting category (for the pie chart)
_CATEGORY = {
    "gather": "Gathering",
    "forage": "Foraging",
    "mine": "Mining",
    "acquire": "Trapping",
    "trap": "Trapping",
    "fell": "Foresting",
    "chop": "Foresting",
    "fish": "Fishing",
    "net": "Fishing",
    "catch": "Fishing",
    "collect": "Collecting",
}


def _category(verb: str) -> str:
    return _CATEGORY.get(verb, verb.title())


class HarvestTracker:
    """Cumulative harvest rollup for one character.  Pure/streaming: feed it log
    messages (timestamp already stripped) and read `snapshot()` for the UI."""

    def __init__(self):
        # item name -> aggregate dict
        self.items: dict[str, dict] = {}
        self.rare_total = 0
        self.first_ts = 0.0
        self.last_ts = 0.0
        self._last_item: Optional[str] = None   # for attributing the rare line

    # -- ingest ---------------------------------------------------------------
    def feed(self, msg: str, ts: float) -> bool:
        """Consume one log message. Returns True if it was a harvest/rare line."""
        m = HARVEST_RE.match(msg)
        if m:
            self._record(m.group("item").strip(), int(m.group("qty")),
                         m.group("verb"), m.group("node").strip(), ts)
            return True
        if RARE_RE.match(msg):
            self.rare_total += 1
            if self._last_item and self._last_item in self.items:
                self.items[self._last_item]["rares"] += 1
            return True
        return False

    def _record(self, item: str, qty: int, verb: str, node: str, ts: float) -> None:
        row = self.items.get(item)
        if row is None:
            row = {"item": item, "qty": 0, "actions": 0, "rares": 0,
                   "category": _category(verb), "node": node, "last_ts": 0.0}
            self.items[item] = row
        row["qty"] += qty
        row["actions"] += 1
        row["node"] = node
        row["last_ts"] = ts
        if not self.first_ts or ts < self.first_ts:
            self.first_ts = ts
        if ts > self.last_ts:
            self.last_ts = ts
        self._last_item = item

    # -- combine (past-log import merges into the live dataset) ----------------
    def merge(self, other: "HarvestTracker") -> None:
        for item, o in other.items.items():
            row = self.items.get(item)
            if row is None:
                self.items[item] = dict(o)
            else:
                row["qty"] += o["qty"]
                row["actions"] += o["actions"]
                row["rares"] += o["rares"]
                row["last_ts"] = max(row["last_ts"], o["last_ts"])
                row["node"] = o["node"] or row["node"]
        self.rare_total += other.rare_total
        if other.first_ts and (not self.first_ts or other.first_ts < self.first_ts):
            self.first_ts = other.first_ts
        self.last_ts = max(self.last_ts, other.last_ts)

    def clear(self) -> None:
        self.items.clear()
        self.rare_total = 0
        self.first_ts = self.last_ts = 0.0
        self._last_item = None

    # -- snapshot for the API -------------------------------------------------
    def snapshot(self) -> dict:
        rows = sorted(self.items.values(), key=lambda r: r["qty"], reverse=True)
        total_qty = sum(r["qty"] for r in rows)
        total_actions = sum(r["actions"] for r in rows)
        cats: dict[str, int] = {}
        for r in rows:
            cats[r["category"]] = cats.get(r["category"], 0) + r["qty"]
        categories = sorted(
            ({"label": k, "value": v} for k, v in cats.items()),
            key=lambda d: d["value"], reverse=True)
        items = [dict(r, pct=(100.0 * r["qty"] / total_qty) if total_qty else 0.0)
                 for r in rows]
        return {
            "items": items,
            "categories": categories,
            "total_qty": total_qty,
            "total_actions": total_actions,
            "unique_items": len(rows),
            "rare_total": self.rare_total,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
        }

    # -- persistence ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {"items": self.items, "rare_total": self.rare_total,
                "first_ts": self.first_ts, "last_ts": self.last_ts}

    def load(self, data: dict) -> None:
        self.clear()
        items = (data or {}).get("items") or {}
        if isinstance(items, dict):
            for name, row in items.items():
                self.items[name] = {
                    "item": row.get("item", name),
                    "qty": int(row.get("qty", 0)),
                    "actions": int(row.get("actions", 0)),
                    "rares": int(row.get("rares", 0)),
                    "category": row.get("category", "Gathering"),
                    "node": row.get("node", ""),
                    "last_ts": float(row.get("last_ts", 0.0)),
                }
        self.rare_total = int((data or {}).get("rare_total", 0))
        self.first_ts = float((data or {}).get("first_ts", 0.0))
        self.last_ts = float((data or {}).get("last_ts", 0.0))
