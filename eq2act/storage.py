"""Persist finished fights to SQLite so old parses survive a restart."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional


class FightStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fights (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT,
                zone      TEXT,
                start_ts  REAL,
                end_ts    REAL,
                duration  REAL,
                total     INTEGER,
                summary   TEXT,
                chart     TEXT
            )
        """)
        # migrate older DBs that predate the zone column
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(fights)").fetchall()]
        if "zone" not in cols:
            self._conn.execute("ALTER TABLE fights ADD COLUMN zone TEXT")
        self._conn.commit()

    def save(self, summary: dict, chart: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO fights (name,zone,start_ts,end_ts,duration,total,summary,chart)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (summary.get("name"), summary.get("zone", ""), summary.get("start_ts"),
                 summary.get("end_ts"), summary.get("duration"),
                 summary.get("total_damage"), json.dumps(summary), json.dumps(chart)),
            )
            self._conn.commit()
            return cur.lastrowid

    def list(self, limit: int = 500) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,name,zone,start_ts,end_ts,duration,total FROM fights"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "name": r[1], "zone": r[2] or "", "start_ts": r[3],
                 "end_ts": r[4], "duration": r[5], "total_damage": r[6],
                 "raid_dps": (r[6] / r[5]) if r[5] else 0.0} for r in rows]

    def get(self, fid: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT summary,chart FROM fights WHERE id=?", (fid,)).fetchone()
        if not row:
            return None
        return {"summary": json.loads(row[0]), "chart": json.loads(row[1])}

    def delete(self, fid: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM fights WHERE id=?", (fid,))
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM fights")
            self._conn.commit()
