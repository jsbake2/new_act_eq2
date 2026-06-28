"""Entry point:  python -m eq2act [--log PATH] [--me NAME] [--port N] ...

Starts the parser engine, begins tailing your EQ2 log (if configured), and
serves the dashboard. Everything else is configured live from the web UI.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import threading

from .config import Settings
from .discover import (LatestLogWatcher, char_from_path, find_latest_log,
                       find_log_dir)
from .engine import Engine
from .server import serve
from .tailer import LogTailer

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eq2act", description="EQ2 combat tracker")
    ap.add_argument("--log", help="path to eq2log_<Character>.txt")
    ap.add_argument("--me", help="your character name (expands YOU/YOUR)")
    ap.add_argument("--mode", choices=["solo", "group", "raid", "all"])
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--from-start", action="store_true",
                    help="replay the whole log file on launch (default: live only)")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't auto-open the dashboard in a browser")
    args = ap.parse_args(argv)

    settings = Settings(CONFIG_DIR / "settings.json")
    for key, val in (("log_path", args.log), ("me", args.me), ("mode", args.mode),
                     ("host", args.host), ("port", args.port)):
        if val is not None:
            settings.data[key] = val
    if args.from_start:
        settings.data["from_start"] = True
    settings.save()

    DATA_DIR.mkdir(exist_ok=True)

    # ---- resolve which log to follow ---------------------------------------
    log_dir = find_log_dir(settings.get("log_dir"))
    settings.data["log_dir"] = log_dir
    # follow-latest mode = no explicit character/log was requested
    follow_latest = not (args.log or args.me)
    log_path = ""
    if args.log:
        log_path = args.log
        settings.data["me"] = args.me or char_from_path(args.log)
    elif args.me:
        cand = Path(log_dir) / f"eq2log_{args.me}.txt" if log_dir else None
        log_path = str(cand) if cand and cand.exists() else settings.get("log_path")
    else:
        latest = find_latest_log(log_dir) if log_dir else None
        if latest:
            log_path = latest[0]
            settings.data["me"] = char_from_path(log_path)
    if log_path:
        settings.data["log_path"] = log_path
    settings.save()

    engine = Engine(settings,
                    triggers_path=CONFIG_DIR / "triggers.json",
                    db_path=DATA_DIR / "fights.db")
    engine.log_dir = log_dir

    tailer = None
    if log_path and Path(log_path).exists():
        zone = engine.prime_from_log(log_path)   # seed current zone before tailing
        tailer = LogTailer(log_path, engine.feed_line,
                           from_start=bool(settings.get("from_start")))
        tailer.start()
        print(f"  tailing log -> {log_path}  (character: {settings.get('me')}"
              + (f", zone: {zone}" if zone else "") + ")")
    else:
        print("  no log found yet — pick a character in the dashboard, or run /log on.")

    # ---- let the dashboard / watcher repoint the tailer live ----------------
    def do_switch(new_path, character):
        nonlocal tailer
        print(f"  switching -> {character}  ({new_path})")
        engine.switch_character(character, new_path)
        engine.prime_from_log(new_path)          # seed the new character's zone
        if tailer:
            tailer.change_path(new_path, from_start=False)
        else:
            tailer = LogTailer(new_path, engine.feed_line, from_start=False)
            tailer.start()
    engine.switch_handler = do_switch

    watch_stop = threading.Event()
    if follow_latest and log_dir:
        watcher = LatestLogWatcher(log_dir, on_switch=do_switch, current=log_path)
        threading.Thread(target=watcher.run, args=(watch_stop,), daemon=True,
                         name="latest-log-watcher").start()
        print(f"  follow-latest: watching {log_dir} for the active character")

    host = settings.get("host")
    port = int(settings.get("port"))
    url = f"http://{host}:{port}"
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    print("\n  EQ2ACT — Advanced Combat Tracker for EverQuest II")
    print("  " + "-" * 48)
    try:
        serve(engine, host, port)
    finally:
        watch_stop.set()
        if tailer:
            tailer.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
