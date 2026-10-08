#!/usr/bin/env python3
"""Life Tracker server.

Serves the web UI (static/index.html) and stores all data in a SQLite file.
Python standard library only (3.8+). Run:  python3 server.py
GUIDE.md explains what every part of this file does.
"""
import argparse
import base64
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

# ---------------------------------------------------------------- 1. CONFIG
BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("TRACKER_DATA", BASE / "data"))  # ALL your data lives here
DB_PATH, FILES, BACKUPS = DATA / "tracker.db", DATA / "files", DATA / "backups"
STATIC = BASE / "static"
MAX_DOC = 2 * 1024 * 1024            # biggest single JSON document
MAX_UPLOAD = 50 * 1024 * 1024        # biggest uploaded file
ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg"}
HISTORY_KEEP = 30                    # old versions kept per document
HISTORY_MIN_GAP = 600                # seconds between saved old versions
DAILY_BACKUPS_KEEP = 30

# --------------------------------------------- 2. DATABASE SCHEMA (APPEND ONLY)
# Never edit or delete an existing entry. To change the schema, ADD a new entry
# at the end. The server applies only the entries your database has not seen yet.
MIGRATIONS = [
    # v1: documents (all app data), their history, and uploaded-file records
    """
    CREATE TABLE docs(
        name TEXT PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TEXT NOT NULL);
    CREATE TABLE doc_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        data TEXT NOT NULL,
        saved_at TEXT NOT NULL);
    CREATE INDEX idx_history_name ON doc_history(name, id);
    CREATE TABLE files(
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size INTEGER NOT NULL,
        created_at TEXT NOT NULL);
    """,
]


def now():
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ------------------------------------------------- 3. MIGRATIONS AND BACKUPS
def backup(label):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"tracker-{datetime.now():%Y%m%d-%H%M%S}-{label}.db"
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return dest


def daily_backup():
    today = f"{datetime.now():%Y%m%d}"
    if any(BACKUPS.glob(f"tracker-{today}-*-daily.db")):
        return
    backup("daily")
    for old in sorted(BACKUPS.glob("tracker-*-daily.db"))[:-DAILY_BACKUPS_KEEP]:
        old.unlink()


def migrate():
    DATA.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    have = con.execute("PRAGMA user_version").fetchone()[0]
    if have > len(MIGRATIONS):
        sys.exit("This database is from a newer server version. Update server.py first.")
    if have < len(MIGRATIONS):
        if have > 0:
            backup(f"before-migration-v{have + 1}")  # safety copy before any change
        for i in range(have, len(MIGRATIONS)):
            try:
                con.executescript(f"BEGIN;{MIGRATIONS[i]};PRAGMA user_version={i + 1};COMMIT;")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
    con.close()


def backup_loop():
    while True:
        time.sleep(3600)
        try:
            daily_backup()
        except Exception:
            pass


# ----------------------------------------------------------- 4. DATA ACCESS
def put_doc(con, name, obj):
    """Save one document. The previous version is kept in doc_history."""
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    old = con.execute("SELECT data FROM docs WHERE name=?", (name,)).fetchone()
    if old and old["data"] == text:
        return False
    if old:
        last = con.execute(
            "SELECT saved_at FROM doc_history WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        gap_ok = (not last) or (
            (datetime.now() - datetime.fromisoformat(last["saved_at"])).total_seconds() > HISTORY_MIN_GAP
        )
        if gap_ok:
            con.execute(
                "INSERT INTO doc_history(name,data,saved_at) VALUES(?,?,?)", (name, old["data"], now())
            )
            con.execute(
                "DELETE FROM doc_history WHERE name=? AND id NOT IN "
                "(SELECT id FROM doc_history WHERE name=? ORDER BY id DESC LIMIT ?)",
                (name, name, HISTORY_KEEP),
            )
    con.execute(
        "INSERT INTO docs(name,data,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (name, text, now()),
    )
    return True


# ------------------------------------------------------------ 5. HTTP SERVER
class Handler(BaseHTTPRequestHandler):
    server_version = "LifeTracker/1.0"

    def log_message(self, fmt, *args):
        pass

    # --- helpers
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode())

    def _path(self):
        return unquote(urlparse(self.path).path)

    def _length(self):
        try:
            return int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return -1

    def _auth(self):
        pw = os.environ.get("TRACKER_PASSWORD")
        if not pw:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                given = base64.b64decode(header[6:]).decode().split(":", 1)[1]
            except Exception:
                given = ""
            if hmac.compare_digest(given.encode(), pw.encode()):
                return True
        self._send(401, b"", "text/plain", {"WWW-Authenticate": 'Basic realm="Life Tracker"'})
        return False

    # --- GET
    def do_GET(self):
        if not self._auth():
            return
        path = self._path()
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(),
                              "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
        if path == "/api/ping":
            return self._json(200, {"ok": True})
        if path == "/api/export":
            with conn() as con:
                docs = {r["name"]: json.loads(r["data"]) for r in con.execute("SELECT name,data FROM docs")}
                files = [dict(r) for r in con.execute("SELECT id,name,content_type,size,created_at FROM files")]
            body = json.dumps({"exported_at": now(), "docs": docs, "files": files},
                              indent=1, ensure_ascii=False).encode()
            return self._send(200, body, "application/json; charset=utf-8",
                              {"Content-Disposition": "attachment; filename=tracker-export.json"})
        m = re.fullmatch(r"/api/doc/([A-Za-z0-9_-]{1,64})", path)
        if m:
            with conn() as con:
                r = con.execute("SELECT data FROM docs WHERE name=?", (m[1],)).fetchone()
            return self._send(200, r["data"].encode()) if r else self._json(404, {"error": "not found"})
        m = re.fullmatch(r"/api/doc/([A-Za-z0-9_-]{1,64})/history", path)
        if m:
            with conn() as con:
                rows = con.execute("SELECT id,saved_at FROM doc_history WHERE name=? ORDER BY id DESC",
                                   (m[1],)).fetchall()
            return self._json(200, [dict(r) for r in rows])
        m = re.fullmatch(r"/api/history/(\d+)", path)
        if m:
            with conn() as con:
                r = con.execute("SELECT data FROM doc_history WHERE id=?", (int(m[1]),)).fetchone()
            return self._send(200, r["data"].encode()) if r else self._json(404, {"error": "not found"})
        m = re.fullmatch(r"/files/([a-f0-9]{16})", path)
        if m:
            with conn() as con:
                r = con.execute("SELECT name,content_type FROM files WHERE id=?", (m[1],)).fetchone()
            f = FILES / m[1]
            if not r or not f.exists():
                return self._json(404, {"error": "not found"})
            return self._send(200, f.read_bytes(), r["content_type"], {
                "Content-Disposition": "inline; filename*=UTF-8''" + quote(r["name"]),
                "Cache-Control": "private, max-age=3600"})
        self._json(404, {"error": "not found"})

    # --- PUT (save a document)
    def do_PUT(self):
        if not self._auth():
            return
        m = re.fullmatch(r"/api/doc/([A-Za-z0-9_-]{1,64})", self._path())
        if not m:
            return self._json(404, {"error": "not found"})
        n = self._length()
        if n < 0 or n > MAX_DOC:
            return self._json(413, {"error": "document too large"})
        try:
            obj = json.loads(self.rfile.read(n))
            assert isinstance(obj, dict)
        except Exception:
            return self._json(400, {"error": "body must be a JSON object"})
        with conn() as con:
            changed = put_doc(con, m[1], obj)
        self._json(200, {"ok": True, "changed": changed})

    # --- POST (upload a file / import a backup)
    def do_POST(self):
        if not self._auth():
            return
        path = self._path()
        if path == "/api/files":
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in ALLOWED_TYPES:
                return self._json(415, {"error": "only PDF, PNG and JPG files are allowed"})
            n = self._length()
            if n <= 0 or n > MAX_UPLOAD:
                return self._json(413, {"error": "file too large (max 50 MB)"})
            name = unquote(self.headers.get("X-Filename") or "file")[:200]
            fid = secrets.token_hex(8)
            tmp, left = FILES / (fid + ".part"), n
            with open(tmp, "wb") as out:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    out.write(chunk)
                    left -= len(chunk)
            if left > 0:
                tmp.unlink()
                return self._json(400, {"error": "upload interrupted"})
            tmp.rename(FILES / fid)
            with conn() as con:
                con.execute("INSERT INTO files(id,name,content_type,size,created_at) VALUES(?,?,?,?,?)",
                            (fid, name, ctype, n, now()))
            return self._json(200, {"id": fid, "name": name, "size": n})
        if path == "/api/import":
            n = self._length()
            if n < 0 or n > 20 * 1024 * 1024:
                return self._json(413, {"error": "too large"})
            try:
                docs = json.loads(self.rfile.read(n))["docs"]
                assert isinstance(docs, dict)
            except Exception:
                return self._json(400, {"error": "expected an export file with a docs object"})
            with conn() as con:
                for name, obj in docs.items():
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) and isinstance(obj, dict):
                        put_doc(con, name, obj)
            return self._json(200, {"ok": True, "documents": len(docs)})
        self._json(404, {"error": "not found"})

    # --- DELETE (remove an uploaded file)
    def do_DELETE(self):
        if not self._auth():
            return
        m = re.fullmatch(r"/api/files/([a-f0-9]{16})", self._path())
        if not m:
            return self._json(404, {"error": "not found"})
        with conn() as con:
            con.execute("DELETE FROM files WHERE id=?", (m[1],))
        (FILES / m[1]).unlink(missing_ok=True)
        self._json(200, {"ok": True})


# ---------------------------------------------------------------- 6. START
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "your-computer-ip"


def main():
    ap = argparse.ArgumentParser(description="Life Tracker server")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow your phone on the same Wi-Fi")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    migrate()
    daily_backup()
    threading.Thread(target=backup_loop, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"Life Tracker running.  Data folder: {DATA}")
    if args.host == "127.0.0.1":
        print(f"Open: http://127.0.0.1:{args.port}")
    else:
        print(f"Open on this computer: http://127.0.0.1:{args.port}")
        print(f"Open on your phone:    http://{lan_ip()}:{args.port}")
        if not os.environ.get("TRACKER_PASSWORD"):
            print("WARNING: no password set. Use this only on a trusted home network, "
                  "or set TRACKER_PASSWORD.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
