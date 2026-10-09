"""WSGI adapter for Life Tracker (for PythonAnywhere and other WSGI hosts).

It reuses server.py (database, migrations, backups, put_doc) and offers the
exact same API, so static/index.html and your data work unchanged.
Set TRACKER_PASSWORD (and optionally TRACKER_DATA) in the environment BEFORE
this module is imported (see DEPLOY-PYTHONANYWHERE.md).
"""
import base64
import hmac
import json
import os
import re
import secrets
import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server as S  # noqa: E402  (server.py is import-safe: main() only runs as a script)

_init_lock = threading.Lock()
_ready = False
_last_backup_day = ""


def _startup():
    global _ready
    with _init_lock:
        if not _ready:
            S.migrate()
            _ready = True


def _daily_backup_once():
    """No background thread on WSGI hosts: check once per day on a request."""
    global _last_backup_day
    today = f"{datetime.now():%Y%m%d}"
    if today != _last_backup_day:
        _last_backup_day = today
        try:
            S.daily_backup()
        except Exception:
            pass


STATUS = {200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized", 404: "404 Not Found",
          413: "413 Payload Too Large", 415: "415 Unsupported Media Type"}


def application(environ, start_response):
    _startup()
    _daily_backup_once()

    def send(code, body=b"", ctype="application/json", extra=None):
        headers = [("Content-Type", ctype), ("Content-Length", str(len(body))),
                   ("X-Content-Type-Options", "nosniff")] + list((extra or {}).items())
        start_response(STATUS[code], headers)
        return [body]

    def js(code, obj):
        return send(code, json.dumps(obj).encode())

    # ---- password (same rule as server.py)
    pw = os.environ.get("TRACKER_PASSWORD")
    if pw:
        header = environ.get("HTTP_AUTHORIZATION", "")
        ok = False
        if header.startswith("Basic "):
            try:
                given = base64.b64decode(header[6:]).decode().split(":", 1)[1]
            except Exception:
                given = ""
            ok = hmac.compare_digest(given.encode(), pw.encode())
        if not ok:
            return send(401, b"", "text/plain", {"WWW-Authenticate": 'Basic realm="Life Tracker"'})

    method = environ["REQUEST_METHOD"]
    path = environ.get("PATH_INFO", "/")  # already URL-decoded by the server

    try:
        n = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        n = -1
    body_in = environ["wsgi.input"]

    # ---------------------------------------------------------------- GET
    if method == "GET":
        if path in ("/", "/index.html"):
            return send(200, (S.STATIC / "index.html").read_bytes(), "text/html; charset=utf-8",
                        {"Cache-Control": "no-cache"})
        if path == "/api/ping":
            return js(200, {"ok": True})
        if path == "/api/export":
            with S.conn() as con:
                docs = {r["name"]: json.loads(r["data"]) for r in con.execute("SELECT name,data FROM docs")}
                files = [dict(r) for r in con.execute("SELECT id,name,content_type,size,created_at FROM files")]
            out = json.dumps({"exported_at": S.now(), "docs": docs, "files": files},
                             indent=1, ensure_ascii=False).encode()
            return send(200, out, "application/json; charset=utf-8",
                        {"Content-Disposition": "attachment; filename=tracker-export.json"})
        m = re.fullmatch(r"/api/doc/([A-Za-z0-9_-]{1,64})", path)
        if m:
            with S.conn() as con:
                r = con.execute("SELECT data FROM docs WHERE name=?", (m[1],)).fetchone()
            return send(200, r["data"].encode()) if r else js(404, {"error": "not found"})
        m = re.fullmatch(r"/api/doc/([A-Za-z0-9_-]{1,64})/history", path)
        if m:
            with S.conn() as con:
                rows = con.execute("SELECT id,saved_at FROM doc_history WHERE name=? ORDER BY id DESC",
                                   (m[1],)).fetchall()
            return js(200, [dict(r) for r in rows])
        m = re.fullmatch(r"/api/history/(\d+)", path)
        if m:
            with S.conn() as con:
                r = con.execute("SELECT data FROM doc_history WHERE id=?", (int(m[1]),)).fetchone()
            return send(200, r["data"].encode()) if r else js(404, {"error": "not found"})
        m = re.fullmatch(r"/files/([a-f0-9]{16})", path)
        if m:
            with S.conn() as con:
                r = con.execute("SELECT name,content_type FROM files WHERE id=?", (m[1],)).fetchone()
            f = S.FILES / m[1]
            if not r or not f.exists():
                return js(404, {"error": "not found"})
            return send(200, f.read_bytes(), r["content_type"], {
                "Content-Disposition": "inline; filename*=UTF-8''" + quote(r["name"]),
                "Cache-Control": "private, max-age=3600"})
        return js(404, {"error": "not found"})

    # ---------------------------------------------------------------- PUT
    if method == "PUT":
        m = re.fullmatch(r"/api/doc/([A-Za-z0-9_-]{1,64})", path)
        if not m:
            return js(404, {"error": "not found"})
        if n < 0 or n > S.MAX_DOC:
            return js(413, {"error": "document too large"})
        try:
            obj = json.loads(body_in.read(n))
            assert isinstance(obj, dict)
        except Exception:
            return js(400, {"error": "body must be a JSON object"})
        with S.conn() as con:
            changed = S.put_doc(con, m[1], obj)
        return js(200, {"ok": True, "changed": changed})

    # --------------------------------------------------------------- POST
    if method == "POST":
        if path == "/api/files":
            ctype = (environ.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
            if ctype not in S.ALLOWED_TYPES:
                return js(415, {"error": "only PDF, PNG and JPG files are allowed"})
            if n <= 0 or n > S.MAX_UPLOAD:
                return js(413, {"error": "file too large (max 50 MB)"})
            name = unquote(environ.get("HTTP_X_FILENAME") or "file")[:200]
            fid = secrets.token_hex(8)
            tmp, left = S.FILES / (fid + ".part"), n
            with open(tmp, "wb") as out:
                while left > 0:
                    chunk = body_in.read(min(1 << 20, left))
                    if not chunk:
                        break
                    out.write(chunk)
                    left -= len(chunk)
            if left > 0:
                tmp.unlink()
                return js(400, {"error": "upload interrupted"})
            tmp.rename(S.FILES / fid)
            with S.conn() as con:
                con.execute("INSERT INTO files(id,name,content_type,size,created_at) VALUES(?,?,?,?,?)",
                            (fid, name, ctype, n, S.now()))
            return js(200, {"id": fid, "name": name, "size": n})
        if path == "/api/import":
            if n < 0 or n > 20 * 1024 * 1024:
                return js(413, {"error": "too large"})
            try:
                docs = json.loads(body_in.read(n))["docs"]
                assert isinstance(docs, dict)
            except Exception:
                return js(400, {"error": "expected an export file with a docs object"})
            with S.conn() as con:
                for name, obj in docs.items():
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) and isinstance(obj, dict):
                        S.put_doc(con, name, obj)
            return js(200, {"ok": True, "documents": len(docs)})
        return js(404, {"error": "not found"})

    # ------------------------------------------------------------- DELETE
    if method == "DELETE":
        m = re.fullmatch(r"/api/files/([a-f0-9]{16})", path)
        if not m:
            return js(404, {"error": "not found"})
        with S.conn() as con:
            con.execute("DELETE FROM files WHERE id=?", (m[1],))
        (S.FILES / m[1]).unlink(missing_ok=True)
        return js(200, {"ok": True})

    return js(404, {"error": "not found"})
