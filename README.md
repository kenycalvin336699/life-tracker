# Life Tracker

A personal life-tracking web app that runs entirely on your own machine. One small Python server, one SQLite file, one HTML page. No frameworks, no `pip install`, no accounts, no cloud.

Pages: **Home · Health · College · Self · Plan · Stats · Money**, plus **UI Options** and **Settings**.

## Highlights

- **Zero dependencies.** The backend uses only the Python standard library (3.8+).
- **Your data stays with you.** Everything lives in a single `data/` folder.
- **Safe by design.** Every save keeps the previous version, the database is backed up daily, and schema changes are backed up before they run.
- **Offline-tolerant UI.** Changes are cached in the browser and re-sent to the server if a save fails.
- **Phone friendly.** Serve it on your home Wi-Fi and open it from your phone, optionally behind a password.
- **PDF and image uploads** (PNG, JPG, up to 50 MB each), stored on disk.
- **Portable.** Export everything to JSON and import it on another machine.

## Quick start

Requires Python 3.8 or newer (`python3 --version`).

```bash
cd life-tracker
python3 server.py
```

Then open <http://127.0.0.1:8000>.

On first run the server creates `data/` next to `server.py`, builds the database and takes a first backup.

### Options

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to listen on. Use `0.0.0.0` to allow other devices. |
| `--port` | `8000` | Port to listen on. |

```bash
python3 server.py --host 0.0.0.0 --port 8080
```

### Environment variables

| Variable | Description |
|---|---|
| `TRACKER_PASSWORD` | If set, every request requires HTTP Basic auth. Any username works; the password must match. |
| `TRACKER_DATA` | Folder for the database, uploads and backups. Defaults to `./data`. |

```bash
TRACKER_PASSWORD='change-me' TRACKER_DATA=~/life-tracker-data python3 server.py --host 0.0.0.0
```

## Using it on your phone

1. Start the server with `--host 0.0.0.0`. It prints your computer's LAN address, e.g. `http://192.168.1.20:8000`.
2. Open that address in your phone's browser (same Wi-Fi network).
3. Set `TRACKER_PASSWORD` unless you fully trust the network. Traffic is plain HTTP, so don't expose the server to the internet directly.

## Your data

Everything is under the data folder:

```
data/
├── tracker.db     # SQLite database (all app data and file records)
├── files/         # uploaded PDFs and images
└── backups/       # automatic database snapshots
```

**Backups**
- One snapshot per day (`tracker-YYYYMMDD-HHMMSS-daily-….db`), the newest 30 kept.
- A snapshot is also taken before any database migration.
- To restore, stop the server and replace `data/tracker.db` with a backup file.

**Version history**
- Each document keeps its last 30 previous versions, saved at most once every 10 minutes.

**Export and import**
- Export: open `/api/export` in your browser to download `tracker-export.json`.
- Import: `POST` an export file to `/api/import`:

  ```bash
  curl -X POST --data-binary @tracker-export.json http://127.0.0.1:8000/api/import
  ```

  Export covers app data; uploaded files are in `data/files/`, so copy that folder too when moving machines. Add `-u :PASSWORD` to the curl command if a password is set.

The simplest full backup is copying the whole `data/` folder while the server is stopped.

## How it works

The browser UI stores data as named JSON **documents**. The server saves each one in SQLite and keeps its history.

- Per-day data is split into small shards (`days-YYYY-MM`), so saves stay fast. Older yearly documents (`days-YYYY`) are migrated automatically.
- Document names may contain letters, digits, `_` and `-` (max 64 characters).
- Size limits: 2 MB per document (8 MB for legacy yearly day documents), 50 MB per upload.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | The web UI |
| `GET` | `/api/ping` | Health check |
| `GET` | `/api/docs` | List document names |
| `GET` | `/api/doc/<name>` | Read a document |
| `PUT` | `/api/doc/<name>` | Save a document (JSON object body) |
| `GET` | `/api/doc/<name>/history` | List saved previous versions |
| `GET` | `/api/history/<id>` | Read one previous version |
| `POST` | `/api/files` | Upload a PDF/PNG/JPG (`Content-Type` set, `X-Filename` header) |
| `GET` | `/files/<id>` | Download or view an uploaded file |
| `DELETE` | `/api/files/<id>` | Delete an uploaded file |
| `GET` | `/api/export` | Download all documents as JSON |
| `POST` | `/api/import` | Import an export file |

## Deploying on a WSGI host

`wsgi.py` exposes the same API through a standard WSGI `application` object, reusing the database code in `server.py`. It suits hosts such as PythonAnywhere.

1. Upload the project and point the host's WSGI configuration at `wsgi.py` (`application`).
2. Set `TRACKER_PASSWORD` and, if you want data outside the project folder, `TRACKER_DATA` **before** the module is imported (in the WSGI config file).
3. Serve over HTTPS and always set a password when the app is reachable from the internet.

WSGI hosts have no background threads, so the daily backup runs on the first request each day.

## Project structure

```
life-tracker/
├── server.py          # stdlib HTTP server, SQLite schema and migrations, backups, API
├── wsgi.py            # WSGI adapter exposing the same API
├── static/
│   └── index.html     # the entire frontend (HTML, CSS and JS in one file)
├── README.md
└── .gitignore         # ignores data/ and Python cache files
```

## Troubleshooting

- **`Address already in use`**: another process is on that port; use `--port 8001`.
- **Can't reach it from your phone**: start with `--host 0.0.0.0`, make sure both devices are on the same network, and allow the port through your firewall.
- **"database is from a newer server version"**: the data was written by a newer `server.py`. Update `server.py` rather than downgrading.
- **Fonts look different offline**: the UI loads Google Fonts when online and falls back to system fonts without internet. Everything else works offline.
- **Changes not saving**: the UI shows a banner when the server is unreachable and keeps unsaved edits in the browser; they are sent once the server is back. Keep the tab open until it clears.

## Development

Edit `static/index.html` and refresh; it is served with `no-cache`. Server changes need a restart. Database changes go in as a **new entry appended to `MIGRATIONS`** in `server.py`; never edit existing entries.
