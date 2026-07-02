"""Roll oversized EQ2 logs into archives and read them back transparently.

EQ2 appends to one `eq2log_<Char>.txt` forever — no rotation, no size cap (real
files reach 24 MB+ over weeks).  To cap a *live* log we use **copytruncate**:
copy the file's contents to an archive, then truncate the original in place.
Because the game holds the log open in append mode, *moving* it wouldn't help —
EQ2 would just keep writing to the moved inode and never recreate the original.
Truncating the same inode makes the next append land at offset 0, so the file
starts fresh while the game never notices.

Our own tailer already survives this (it detects the size-shrink and reopens
from the top — see tailer.py), so a live roll doesn't interrupt parsing.

Archives are named:

    eq2log_<Char>__<firstEpoch>-<lastEpoch>.txt

so a date-range query can pick the overlapping ones from the filename alone and
stitch archives + the live log back into one continuous stream.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import List, Optional

from .discover import char_from_path
from .parser import LINE_RE

ARCHIVE_SUBDIR = "eq2act_archive"
_ARCH_RE = re.compile(r"^eq2log_(?P<char>.+)__(?P<first>\d+)-(?P<last>\d+)\.txt$")
_CHUNK = 1 << 20            # 1 MiB copy chunk
_SCAN = 1 << 18            # 256 KiB head/tail scan window for span detection


def archive_dir_for(log_dir: str, configured: str = "") -> str:
    """Where archives live: the configured dir, else `<logs>/eq2act_archive`."""
    if configured:
        return configured
    return os.path.join(log_dir, ARCHIVE_SUBDIR) if log_dir else ""


def _read_head(path: str, n: int) -> str:
    with open(path, "rb") as f:
        return f.read(n).decode("utf-8", "replace")


def _read_tail(path: str, n: int) -> str:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > n:
            f.seek(size - n)
        return f.read().decode("utf-8", "replace")


def scan_span(path: str) -> tuple[float, float]:
    """(firstEpoch, lastEpoch) for a log file — cheap head+tail scan (epochs are
    monotonic, so the first line up top and the last line at the bottom suffice)."""
    first = last = 0.0
    try:
        for line in _read_head(path, _SCAN).splitlines():
            m = LINE_RE.match(line)
            if m:
                first = float(m.group("epoch"))
                break
        for line in _read_tail(path, _SCAN).splitlines():
            m = LINE_RE.match(line)
            if m:
                last = float(m.group("epoch"))
    except OSError:
        return 0.0, 0.0
    if not last:
        last = first
    return first, last


def rotate(log_path: str, archive_dir: str) -> Optional[dict]:
    """Copytruncate `log_path` into `archive_dir`. Returns archive info or None
    (missing/empty file). Safe to call while the game and our tailer are live."""
    p = Path(log_path)
    try:
        size = p.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    char = char_from_path(log_path)
    os.makedirs(archive_dir, exist_ok=True)
    tmp = Path(archive_dir) / (p.stem + ".rolling.tmp")
    # 1) copy exactly the [0, size) bytes we observed (bytes EQ2 appends past
    #    `size` during the copy stay in the live file and are simply not rolled).
    try:
        with open(p, "rb") as src, open(tmp, "wb") as dst:
            remaining = size
            while remaining > 0:
                chunk = src.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
        # 2) truncate the original in place — the game's append fd now writes at 0
        with open(p, "r+b") as f:
            f.truncate(0)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return None
    first, last = scan_span(str(tmp))
    final = Path(archive_dir) / f"eq2log_{char}__{int(first)}-{int(last)}.txt"
    # avoid clobbering an existing archive with the same span
    n = 1
    while final.exists():
        final = Path(archive_dir) / f"eq2log_{char}__{int(first)}-{int(last)}.{n}.txt"
        n += 1
    os.replace(tmp, final)
    return {"path": str(final), "character": char, "bytes": size,
            "first": first, "last": last}


def list_archives(archive_dir: str, character: str = "") -> List[dict]:
    """All archives (optionally for one character), sorted oldest-first."""
    out: List[dict] = []
    if not archive_dir or not os.path.isdir(archive_dir):
        return out
    for path in glob.glob(os.path.join(archive_dir, "eq2log_*.txt")):
        base = os.path.basename(path)
        m = _ARCH_RE.match(base)
        if not m:
            continue
        if character and m.group("char").lower() != character.lower():
            continue
        try:
            sz = os.path.getsize(path)
        except OSError:
            sz = 0
        out.append({"path": path, "character": m.group("char"),
                    "first": float(m.group("first")), "last": float(m.group("last")),
                    "bytes": sz})
    out.sort(key=lambda d: d["first"])
    return out


def prune(archive_dir: str, retention_days: float, now: float) -> List[dict]:
    """Delete archives whose newest data is older than `retention_days`.
    Returns the removed archives. `retention_days <= 0` keeps everything."""
    removed: List[dict] = []
    if retention_days is None or retention_days <= 0:
        return removed
    cutoff = now - retention_days * 86400.0
    for a in list_archives(archive_dir):
        # age by the archive's last-data epoch; fall back to file mtime
        age_ts = a["last"]
        if not age_ts:
            try:
                age_ts = os.path.getmtime(a["path"])
            except OSError:
                continue
        if age_ts < cutoff:
            try:
                os.remove(a["path"])
                removed.append(a)
            except OSError:
                pass
    return removed


def logs_for_range(character: str, live_path: str, archive_dir: str,
                   start_ts: float = 0.0, end_ts: float = 0.0) -> List[str]:
    """Ordered file list (archives that overlap [start,end], then the live log)
    to scan for a character's history — spans rolled logs transparently."""
    files: List[str] = []
    for a in list_archives(archive_dir, character):
        if start_ts and a["last"] and a["last"] < start_ts:
            continue
        if end_ts and a["first"] and a["first"] > end_ts:
            continue
        files.append(a["path"])
    if live_path and os.path.isfile(live_path) and live_path not in files:
        files.append(live_path)
    return files
