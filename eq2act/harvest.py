"""Track resource harvesting (gathering, mining, foresting, trapping, …).

EQ2 emits one line per successful harvest, e.g.

    (1782492531)[Thu ...] You gather 3 \\aITEM -1610631990 -385153372:root\\/a from the roots.
    (1782454331)[Fri ...] You forest 10 \\aITEM ...:severed maple\\/a from the wind felled tree.
    (1781479355)[Sun ...] You acquire a 1 \\aITEM ...:deer meat\\/a from the creature den.

A rare pull prints a banner line, and the **very next** harvest line is the
rare item itself (always qty 1, a distinct rare-tier resource):

    (1782454278)[Fri ...] You have found a rare item!
    (1782454278)[Fri ...] You mine 1 \\aITEM ...:blackened iron cluster\\/a from the cloven ore.

So the rare is attributed *forward* to the following item, not backward — the
common item mined just before the banner is unrelated.

This module is independent of the combat engine (harvest lines never match a
combat regex).  It rolls totals up per item, and the snapshot pre-groups them by
node and by skill category so the UI can pivot the same data many ways.  Totals
persist per character (like the ally roster).
"""
from __future__ import annotations

import re
from typing import Optional

# "You forest 10 \aITEM <id> <id>:severed maple\/a from the wind felled tree."
HARVEST_RE = re.compile(
    r"^You (?P<verb>gather|mine|forest|acquire|forage|trap|fell|chop|fish|net|catch|collect)\w* "
    r"(?:a )?(?P<qty>\d+) "
    r"\\aITEM\s+-?\d+\s+-?\d+:(?P<item>[^\\]+)\\/a "
    r"from the (?P<node>.+?)\.$"
)
RARE_RE = re.compile(r"^You have found a rare item!$")

# harvest verb -> EQ2 tradeskill/harvesting category (for grouping + the pie)
_CATEGORY = {
    "gather": "Gathering",
    "forage": "Foraging",
    "mine": "Mining",
    "forest": "Foresting",
    "fell": "Foresting",
    "chop": "Foresting",
    "acquire": "Trapping",
    "trap": "Trapping",
    "fish": "Fishing",
    "net": "Fishing",
    "catch": "Fishing",
    "collect": "Collecting",
}


def _category(verb: str) -> str:
    return _CATEGORY.get(verb, verb.title())


class HarvestTracker:
    """Cumulative harvest rollup for one character.  Feed it log messages
    (timestamp already stripped) and read `snapshot()` for the UI."""

    def __init__(self):
        # item name -> {item, qty, pulls, rares, category, node, last_ts}
        self.items: dict[str, dict] = {}
        self.rare_total = 0
        self.first_ts = 0.0
        self.last_ts = 0.0
        self._rare_pending = False   # the NEXT harvest line is a rare

    # -- ingest ---------------------------------------------------------------
    def feed(self, msg: str, ts: float) -> bool:
        """Consume one log message. Returns True if it was a harvest/rare line."""
        if RARE_RE.match(msg):
            self.rare_total += 1
            self._rare_pending = True
            return True
        m = HARVEST_RE.match(msg)
        if m:
            self._record(m.group("item").strip(), int(m.group("qty")),
                         m.group("verb"), m.group("node").strip(), ts,
                         rare=self._rare_pending)
            self._rare_pending = False
            return True
        return False

    def _record(self, item: str, qty: int, verb: str, node: str, ts: float,
                rare: bool = False) -> None:
        row = self.items.get(item)
        if row is None:
            row = {"item": item, "qty": 0, "pulls": 0, "rares": 0,
                   "category": _category(verb), "node": node, "last_ts": 0.0}
            self.items[item] = row
        row["qty"] += qty
        row["pulls"] += 1
        if rare:
            row["rares"] += 1
        row["node"] = node
        row["last_ts"] = ts
        if not self.first_ts or ts < self.first_ts:
            self.first_ts = ts
        if ts > self.last_ts:
            self.last_ts = ts

    # -- combine (past-log import merges into the live dataset) ----------------
    def merge(self, other: "HarvestTracker") -> None:
        for item, o in other.items.items():
            row = self.items.get(item)
            if row is None:
                self.items[item] = dict(o)
            else:
                row["qty"] += o["qty"]
                row["pulls"] += o["pulls"]
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
        self._rare_pending = False

    # -- snapshot for the API -------------------------------------------------
    def snapshot(self) -> dict:
        rows = sorted(self.items.values(), key=lambda r: r["qty"], reverse=True)
        total_qty = sum(r["qty"] for r in rows)
        total_pulls = sum(r["pulls"] for r in rows)
        total_rares = sum(r["rares"] for r in rows)

        def enrich(r):
            return {**r, "is_rare": r["rares"] > 0,
                    "pct": (100.0 * r["qty"] / total_qty) if total_qty else 0.0}
        items = [enrich(r) for r in rows]

        # group by node and by category (pre-pivoted; the UI can also regroup)
        def group(keyfn):
            g: dict[str, dict] = {}
            for it in items:
                k = keyfn(it) or "—"
                b = g.get(k)
                if b is None:
                    b = {"key": k, "category": it["category"], "qty": 0,
                         "pulls": 0, "rares": 0, "items": []}
                    g[k] = b
                b["qty"] += it["qty"]
                b["pulls"] += it["pulls"]
                b["rares"] += it["rares"]
                b["items"].append(it)
            out = sorted(g.values(), key=lambda b: b["qty"], reverse=True)
            for b in out:
                b["pct"] = (100.0 * b["qty"] / total_qty) if total_qty else 0.0
            return out

        return {
            "items": items,
            "nodes": group(lambda it: it["node"]),
            "categories": group(lambda it: it["category"]),
            "total_qty": total_qty,
            "total_pulls": total_pulls,
            "total_rares": total_rares,
            "unique_items": len(rows),
            "unique_nodes": len({r["node"] for r in rows}),
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
                    # tolerate the older "actions" key
                    "pulls": int(row.get("pulls", row.get("actions", 0))),
                    "rares": int(row.get("rares", 0)),
                    "category": row.get("category", "Gathering"),
                    "node": row.get("node", ""),
                    "last_ts": float(row.get("last_ts", 0.0)),
                }
        self.rare_total = int((data or {}).get("rare_total", 0))
        self.first_ts = float((data or {}).get("first_ts", 0.0))
        self.last_ts = float((data or {}).get("last_ts", 0.0))
