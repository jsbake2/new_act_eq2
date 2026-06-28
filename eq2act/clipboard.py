"""Copy text to the OS clipboard, best-effort, cross-platform.

Tries wl-copy (Wayland), xclip / xsel (X11), pbcopy (macOS), clip (Windows).
Returns the tool used, or "" if none worked. Never raises.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional, Tuple

_CANDIDATES: List[Tuple[str, list]] = [
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
    ("pbcopy", ["pbcopy"]),
    ("clip", ["clip"]),
]

_chosen: Optional[list] = None
_probed = False


def available() -> str:
    global _chosen, _probed
    if not _probed:
        _probed = True
        for name, cmd in _CANDIDATES:
            if shutil.which(cmd[0]):
                _chosen = cmd
                break
    return _chosen[0] if _chosen else ""


def copy(text: str) -> str:
    """Copy text to the clipboard. Returns the backend name, or "" on failure."""
    if not available():
        return ""
    try:
        p = subprocess.run(_chosen, input=text.encode("utf-8"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3)
        return _chosen[0] if p.returncode == 0 else ""
    except Exception:
        return ""
