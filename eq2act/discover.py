"""Find EQ2 log files and auto-pick the one that's actually being written to.

Lets you launch with no character name: EQ2ACT scans the logs directory, tails
the most-recently-modified eq2log_<Char>.txt, derives your character from the
filename, and (in follow mode) switches automatically if you log in on someone
else.
"""
from __future__ import annotations

import glob
import os
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# Common EQ2 logs locations to probe when no log_dir is configured.
_CANDIDATE_DIRS = [
    "/mnt/games3/SteamLibrary/steamapps/common/EverQuest 2/logs",
    os.path.expanduser("~/.steam/steam/steamapps/common/EverQuest 2/logs"),
    os.path.expanduser("~/.local/share/Steam/steamapps/common/EverQuest 2/logs"),
]


def char_from_path(path: str) -> str:
    """eq2log_Trailmix.txt -> Trailmix"""
    stem = Path(path).stem            # eq2log_Trailmix
    if stem.lower().startswith("eq2log_"):
        return stem[len("eq2log_"):]
    return stem


def _all_logs(log_dir: str) -> List[str]:
    # logs may sit directly in logs/ or under logs/<Server>/
    pats = [os.path.join(log_dir, "eq2log_*.txt"),
            os.path.join(log_dir, "*", "eq2log_*.txt")]
    out: List[str] = []
    for p in pats:
        out.extend(glob.glob(p))
    return out


def find_log_dir(configured: str = "") -> str:
    """Return a usable logs directory: the configured one if it has logs, else
    the first probed candidate that does."""
    if configured and _all_logs(configured):
        return configured
    for d in ([configured] if configured else []) + _CANDIDATE_DIRS:
        if d and os.path.isdir(d) and _all_logs(d):
            return d
    return configured or ""


def find_latest_log(log_dir: str, max_age: Optional[float] = None
                    ) -> Optional[Tuple[str, float]]:
    """Newest eq2log_*.txt under log_dir. If max_age is set, only consider files
    modified within that many seconds (i.e. an *active* session)."""
    best: Optional[Tuple[str, float]] = None
    now = time.time()
    for path in _all_logs(log_dir):
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        if max_age is not None and (now - mt) > max_age:
            continue
        if best is None or mt > best[1]:
            best = (path, mt)
    return best


class LatestLogWatcher:
    """Polls the logs dir; when a *different* file becomes the most-recently
    active one, fires on_switch(path, character)."""

    def __init__(self, log_dir: str, on_switch: Callable[[str, str], None],
                 current: str = "", interval: float = 8.0, active_window: float = 90.0):
        self.log_dir = log_dir
        self.on_switch = on_switch
        self.current = current
        self.interval = interval
        self.active_window = active_window
        self._stop = None

    def run(self, stop_event) -> None:
        self._stop = stop_event
        while not stop_event.is_set():
            stop_event.wait(self.interval)
            if stop_event.is_set():
                break
            latest = find_latest_log(self.log_dir, max_age=self.active_window)
            if latest and latest[0] != self.current:
                self.current = latest[0]
                try:
                    self.on_switch(latest[0], char_from_path(latest[0]))
                except Exception:
                    pass
