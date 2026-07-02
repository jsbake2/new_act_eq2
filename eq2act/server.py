"""Standard-library HTTP server: REST API + Server-Sent Events live feed +
static web dashboard.  No external dependencies.

SSE (one-way server->browser push) is all we need: the browser pulls config via
plain GET/POST and receives live DPS updates + trigger dings over /events.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .engine import Engine
from .pastable import format_parse

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    engine: Engine = None        # injected on the server class
    server_version = "EQ2ACT/0.1"
    protocol_version = "HTTP/1.1"

    # -- helpers --------------------------------------------------------------
    def log_message(self, *a):    # keep the console clean
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, code=200, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        target = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR not in target.parents and target != WEB_DIR:
            self._send_text("forbidden", 403)
            return
        if not target.is_file():
            self._send_text("not found", 404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         _CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # -- SSE ------------------------------------------------------------------
    def _serve_events(self):
        q = queue.Queue(maxsize=256)

        def listener(msg):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

        self.engine.add_listener(listener)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    payload = "data: %s\n\n" % json.dumps(msg)
                    self.wfile.write(payload.encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.engine.remove_listener(listener)

    # -- routing --------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        eng = self.engine
        try:
            if path == "/events":
                return self._serve_events()
            if path == "/api/status":
                return self._send_json(eng.status())
            if path == "/api/live":
                return self._send_json(eng.live_summary())
            if path == "/api/fights":
                return self._send_json(eng.fight_list())
            if path.startswith("/api/fights/"):
                rest = path[len("/api/fights/"):]
                if rest.endswith("/paste"):
                    fid = rest[:-len("/paste")]
                    detail = eng.fight_detail(fid if fid == "live" else fid)
                    if not detail:
                        return self._send_json({"error": "not found"}, 404)
                    txt = format_parse(detail["summary"],
                                       top=int(eng.settings.get("paste_top")),
                                       title=eng.settings.get("paste_title"))
                    return self._send_json({"text": txt})
                detail = eng.fight_detail(rest)
                if not detail:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_json(detail)
            if path == "/api/harvest":
                return self._send_json(eng.harvest_snapshot())
            if path == "/api/archive":
                return self._send_json(eng.archive_info())
            if path == "/api/triggers":
                return self._send_json(eng.triggers.list())
            if path == "/api/settings":
                return self._send_json(eng.settings.data)
            if path == "/api/characters":
                return self._send_json({"characters": eng.list_characters(),
                                        "current": eng.settings.get("me"),
                                        "log_dir": eng.log_dir})
            return self._serve_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        eng = self.engine
        try:
            if path == "/api/settings":
                eng.apply_settings(self._read_json())
                return self._send_json({"ok": True, "settings": eng.settings.data})
            if path == "/api/triggers":
                items = self._read_json()
                if isinstance(items, dict):
                    items = items.get("triggers", [])
                eng.triggers.replace_all(items)
                return self._send_json({"ok": True, "triggers": eng.triggers.list()})
            if path == "/api/triggers/test":
                body = self._read_json()
                import re
                try:
                    rx = re.compile(body.get("pattern", ""))
                    m = rx.search(body.get("sample", ""))
                    return self._send_json({"ok": True, "matched": bool(m),
                                            "groups": list(m.groups()) if m else []})
                except re.error as e:
                    return self._send_json({"ok": False, "error": str(e)})
            if path == "/api/feed":
                body = self._read_json()
                for ln in (body.get("lines") or
                           ([body["line"]] if body.get("line") else [])):
                    eng.feed_line(ln)
                return self._send_json({"ok": True})
            if path == "/api/switch":
                body = self._read_json()
                ok = eng.request_switch(character=body.get("character", ""),
                                        path=body.get("path", ""))
                return self._send_json({"ok": ok, "me": eng.settings.get("me")})
            if path == "/api/import":
                body = self._read_json()
                # character (no path) spans archives + live log; explicit path = single file
                res = eng.import_range(
                    body.get("path", ""), me=body.get("me", ""),
                    character=body.get("character", ""),
                    start_ts=float(body.get("start_ts") or 0),
                    end_ts=float(body.get("end_ts") or 0),
                    mode=body.get("mode", "all"))
                return self._send_json(res)
            if path == "/api/harvest/import":
                body = self._read_json()
                res = eng.import_harvests(
                    body.get("path", ""), me=body.get("me", ""),
                    character=body.get("character", ""),
                    start_ts=float(body.get("start_ts") or 0),
                    end_ts=float(body.get("end_ts") or 0))
                return self._send_json(res)
            if path == "/api/harvest/clear":
                eng.clear_harvests()
                return self._send_json({"ok": True})
            if path == "/api/archive/rotate":
                return self._send_json(eng.rotate_now(reason="manual"))
            if path == "/api/aggregate":
                body = self._read_json()
                ids = body.get("ids")
                if body.get("zone") is not None:
                    z = body["zone"]
                    ids = [f["id"] for f in eng.fight_list()
                           if (f.get("zone") or "") == z]
                res = eng.aggregate(ids or [])
                if not res:
                    return self._send_json({"error": "no fights"}, 404)
                return self._send_json(res)
            if path == "/api/control/end":
                if eng.encounters.current and not eng.encounters.current.closed:
                    eng.encounters.current.close()
                    eng.encounters.history.append(eng.encounters.current)
                    eng.encounters.current = None
                    eng._on_fight_closed()
                return self._send_json({"ok": True})
            if path == "/api/control/clear":
                eng.store.clear()
                eng.encounters.history.clear()
                eng._closed_ids.clear()
                eng._broadcast({"type": "fight_closed"})
                return self._send_json({"ok": True})
            if path.startswith("/api/fights/") and path.endswith("/delete"):
                fid = path[len("/api/fights/"):-len("/delete")]
                eng.store.delete(int(fid))
                eng._broadcast({"type": "fight_closed"})
                return self._send_json({"ok": True})
            return self._send_json({"error": "unknown endpoint"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _ticker(engine: Engine, stop: threading.Event):
    while not stop.is_set():
        time.sleep(1.0)
        try:
            engine.tick()
        except Exception:
            pass


def serve(engine: Engine, host: str, port: int):
    Handler.engine = engine
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    stop = threading.Event()
    t = threading.Thread(target=_ticker, args=(engine, stop), daemon=True)
    t.start()
    print(f"  EQ2ACT dashboard -> http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
