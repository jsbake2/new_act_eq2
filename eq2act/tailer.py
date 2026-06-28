"""Follow an EQ2 log file like `tail -f`, surviving rotation/truncation.

EQ2 writes to <install>/logs/eq2log_<Character>.txt once you `/log on` in game.
The tailer runs in its own thread and calls a callback with each new raw line.
On start it can optionally replay the existing file (so you don't lose the fight
you were already in) or seek to the end (live only).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class LogTailer:
    def __init__(self, path: str, on_line: Callable[[str], None],
                 from_start: bool = False, poll: float = 0.25):
        self.path = Path(path)
        self.on_line = on_line
        self.from_start = from_start
        self.poll = poll
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.lines_read = 0
        self.alive_file = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="eq2-tailer")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def change_path(self, path: str, from_start: bool = False) -> None:
        """Swap the watched file at runtime (e.g. user picks a new character)."""
        self.stop()
        self._stop = threading.Event()
        self.path = Path(path)
        self.from_start = from_start
        self.lines_read = 0
        self.start()

    def _open(self):
        try:
            f = open(self.path, "r", encoding="utf-8", errors="replace")
            self.alive_file = True
            if not self.from_start:
                f.seek(0, os.SEEK_END)
            return f, os.fstat(f.fileno()).st_ino
        except OSError:
            self.alive_file = False
            return None, None

    def _run(self) -> None:
        f, inode = None, None
        buf = ""
        while not self._stop.is_set():
            if f is None:
                f, inode = self._open()
                if f is None:
                    time.sleep(max(self.poll, 0.5))
                    continue
            where = f.tell()
            chunk = f.read()
            if chunk:
                buf += chunk
                while True:
                    nl = buf.find("\n")
                    if nl < 0:
                        break
                    line = buf[:nl]
                    buf = buf[nl + 1:]
                    if line:
                        self.lines_read += 1
                        try:
                            self.on_line(line)
                        except Exception:
                            pass
                continue
            # no new data — check for rotation / truncation
            try:
                st = os.stat(self.path)
                if st.st_ino != inode or st.st_size < where:
                    try:
                        f.close()
                    except OSError:
                        pass
                    f, inode = None, None
                    self.from_start = True   # read the fresh file from its top
                    buf = ""
                    continue
            except OSError:
                try:
                    f.close()
                except OSError:
                    pass
                f, inode = None, None
                self.alive_file = False
            time.sleep(self.poll)
        if f:
            try:
                f.close()
            except OSError:
                pass
