# Life Tracker: code guide

What each file and function does, where your data lives, and how to change things without losing past data.

## 1. Files

```
life-tracker/
├── server.py          Backend: web server, API, database, backups
├── static/
│   └── index.html     Frontend: all screens and logic (HTML + CSS + JavaScript)
├── data/              YOUR DATA (created on first run). Never overwritten by code updates.
│   ├── tracker.db     SQLite database (all your records)
│   ├── files/         Uploaded PDFs and images
│   └── backups/       Automatic database backups
├── README.md          Setup and run instructions
└── GUIDE.md           This file
```

**Golden rule:** code (`server.py`, `static/`) and data (`data/`) are separate. You can replace the code any time and your data stays.

## 2. How data is stored

All app data is saved as small **documents** (JSON) in one database table. The frontend loads a document, changes it, and saves it back. Adding a feature rarely needs a database change.

| Document name | Holds | Shape |
|---|---|---|
| `health` | Health settings and weekly plans | `{wake, sleep, wmin, wmax, protein, budget, ex:{mon:[..]..sun:[..]}, fd:{mon:[..]..sun:[..]}}` |
| `college` | Semesters, subjects, plan | `{sems:[{id,name}], subs:[{id,sem,n,bl,ch:[{id,t,d}],as:[{id,t,d}],fl:[{id,n,k,a}]}], plan:{mon:[{s,h}]..}}` |
| `self` | Self topics: schedule, resources, notes | `{topics:[{id,n,sch:{mon:{h,at}..},res:[{id,t,u}],notes:[{id,t,d,dt}]}]}` |
| `days-2026` (one per year) | Daily records | `{days:{"2026-10-08":{done:{key:true}, water, protein, wake, sdone:{subjectId:true}}}}` |
| `money-2026-10` (one per month) | Money entries | `{items:[{id,d,t,a,c,n}]}` (date, in/out, amount, category, note) |

Short field names in `college`: `n` name, `bl` backlog state (0 regular, 1 pending, 2 cleared), `ch` chapters, `as` assignments, `t` title, `d` done, `fl` files (`k` is `syl` or `pyq`, `a` is the file id), `s` subject id, `h` hours.

In `self`: `n` topic name, `sch` schedule per weekday (`h` hours, `at` start time `HH:MM`), `res` resources (`t` title, `u` optional link), `notes` things you missed (`d` covered, `dt` date added). Daily ticks for Self topics are saved in the day record as `pdone`.

Daily checklist keys in `done`: `wake`, `sleep`, `e:<exercise text>`, `f:<food text>`. Note: if you rename an exercise or meal in the plan, old days no longer match it. That is expected.

The database also has `doc_history` (older versions of each document) and `files` (records of uploads).

## 3. Backend: `server.py`

| Section | What it does |
|---|---|
| 1. CONFIG | Folder paths, size limits, allowed upload types |
| 2. MIGRATIONS | **Append-only** list of database changes. Each entry has a version number (its position). |
| 3. MIGRATIONS AND BACKUPS | `migrate()` applies only new entries, after making a backup. `backup()`, `daily_backup()` copy the database. |
| 4. DATA ACCESS | `put_doc()` saves a document and keeps the previous version in `doc_history` |
| 5. HTTP SERVER | `Handler` class: `do_GET`, `do_PUT`, `do_POST`, `do_DELETE` serve pages, the API and files. `_auth()` checks the optional password. |
| 6. START | `main()` reads options, runs migrations, starts the server |

### API

| Method and path | Purpose |
|---|---|
| `GET /` | The app (`static/index.html`) |
| `GET /api/ping` | Health check |
| `GET /api/doc/<name>` | Read a document (404 if it does not exist yet) |
| `PUT /api/doc/<name>` | Save a document (JSON object) |
| `GET /api/doc/<name>/history` | List older versions of a document |
| `GET /api/history/<id>` | Read one older version |
| `POST /api/files` | Upload a PDF, PNG or JPG (raw body, `X-Filename` header) |
| `GET /files/<id>` | Open an uploaded file |
| `DELETE /api/files/<id>` | Delete an uploaded file |
| `GET /api/export` | Download all documents as one JSON file |
| `POST /api/import` | Restore documents from an export file |

## 4. Frontend: `static/index.html`

Inside the `<script>` tag, in this order:

| Part | Functions and variables | What it does |
|---|---|---|
| Helpers | `$`, `esc`, `iso`, `parse`, `addD`, `shiftMon`, `fmt`, `uid0` | Dates, escaping text, currency, random ids |
| State | `S.s` (health), `S.c` (college), `S.days`, `S.money` | Data in memory. `cur` is the selected date, `tab` the open screen. |
| Storage | `init`, `load`, `save`, `flush`, `banner`, `ensureYear`, `ensureMon`, `saveDays`, `saveMoney`, `saveSet`, `saveCol` | Talks to the server. Saves are sent after 400 ms and retried every 5 s if the server is off. |
| Health logic | `DEF`, `dk`, `isRest`, `items`, `pct`, `streak`, `xp` | Default settings, today's checklist, score, streak, XP and level |
| Health screens | `vHealth`, `vEdit`, `meter`, `chk`, `capture` | Health page and the plan editor |
| Home | `vHome`, `colTile` | Level bar and the three boxes |
| College | `CDEF`, `sub`, `sylP`, `asgLeft`, `planSum`, `vCollege`, `cMain`, `cSem`, `cSub`, `cPlan`, `colClick`, `colChange` | Semesters, subjects, syllabus, assignments, backlog, study plan, PDF upload |
| Self | `SDEF`, `tp`, `hrsWeek`, `selfPlan`, `selfTile`, `vSelf`, `sMain`, `sTop`, `selfClick`, `selfChange` | Topics, weekly schedule, resources, missed-notes, today's growth ticks, button to Money |
| Stats | `vStats` | Week, month and year views |
| Money | `vMoney`, `sum` | Income, spending, budget |
| App core | `render`, the `click` and `change` listeners, the boot function at the bottom | Draws the current screen and handles every button |

Buttons use `data-act="name"`. The click listener calls the matching code. To add a button, give it a `data-act` and handle it in `colClick`, `colChange` or the main listeners.

## 5. Rules that protect your data

1. **Never rename or remove a field** in a document. Only add new fields.
2. **Always give new fields a default.** Load with defaults, like `S.c=Object.assign(CDEF(),await load('college',{}))`. Old records without the new field then keep working.
3. **New feature, new document name.** Example: a Self section uses its own document `self`. This never touches existing data.
4. **Database changes (rare):** only add a new entry at the end of `MIGRATIONS`. Never edit or reorder old entries. The server backs up before applying it.
5. **Copy `data/` before big changes.** It is just a folder.
6. **Do not delete `data/`** when updating. Replace only `server.py` and `static/index.html`.
7. If you must change how a document is shaped, write a small conversion that runs on load and keeps the old fields until you are sure.

## 6. Adding a feature: how the Self section was added (repeat these steps for the next feature)

1. Choose a document name: `self`. (Avoid names like `top` for variables: the browser already uses them. Self uses `tp`.)
2. Add defaults and state:
   ```js
   const SDEF=()=>({habits:[],notes:[]});
   // in the boot function at the bottom:
   S.f=Object.assign(SDEF(),await load('self',{}));
   const saveSelf=()=>save('self',S.f);
   ```
3. Write the screen as a function that returns HTML: `function vSelf(){ return \`...\` }`.
4. Register it in `render`: add `self:vSelf` to the view map and `self:'Self'` to the `nm` list.
5. Make the Self box on the home screen open it: `data-act="go" data-t="self"`.
6. Handle its buttons (`data-act`) in a new `selfClick` function, like `colClick`.
7. Wire the click and change handlers: add `else if(selfClick(b,a)){}` after the `colClick` line in the click listener, and `else if(selfChange(t,a)){}` after the `colChange` line in the change listener.
8. If your delete button uses the two-tap check, add its action name to the pattern `/^del(f|sub|sem|tp)$/` in `colClick`.
9. Refresh the browser. Old data is untouched because `self` is a new document.

No server change is needed for this.

## 7. Backups and recovery

| Situation | What to do |
|---|---|
| Normal safety | Automatic daily copies in `data/backups/` (30 kept) |
| Before a database change | `before-migration-vN` copy is made automatically |
| Restore a backup | Stop the server, copy a file from `data/backups/` over `data/tracker.db`, start again |
| Undo a bad edit to one document | Open `http://127.0.0.1:8000/api/doc/<name>/history`, then `/api/history/<id>` to read the old version, and save it back with `PUT` |
| Full export | Open `http://127.0.0.1:8000/api/export` and save the file. Uploaded files are in `data/files/`. |
| Move computers | Copy the `data/` folder to the new `life-tracker/` folder |

Old versions in `doc_history` are saved at most every 10 minutes per document (last 30 kept). Use the daily backups for longer-term recovery.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "Server offline" red bar | The server stopped. Start it again. Changes made meanwhile are kept in the browser and sent when it returns. |
| Port already in use | `python3 server.py --port 9000` |
| Phone cannot connect | Use `--host 0.0.0.0`, same Wi-Fi, and allow the port in your firewall |
| Upload fails | Use a PDF, PNG or JPG up to 50 MB |
| "database is from a newer server version" | You are running an older `server.py` on newer data. Use the newer `server.py`. |
