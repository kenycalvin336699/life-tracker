# Life Tracker: local setup

A small web app (Health, College, Stats, Money) with its own server and database.
It runs on your computer. No internet or extra installs needed.

## Requirements

- Python 3.8 or newer (check with `python3 --version`)

## Run it

```bash
cd life-tracker
python3 server.py
```

Open **http://127.0.0.1:8000** in your browser. Stop with `Ctrl+C`.

Your data is created automatically in the `data/` folder next to `server.py`.

## Use it on your phone (same Wi-Fi)

```bash
TRACKER_PASSWORD=choose-a-password python3 server.py --host 0.0.0.0
```

The terminal prints an address like `http://192.168.x.x:8000`. Open it on your phone.
Your browser asks for a password (any username, the password you chose).
Only do this on a trusted home network.

## Options

| Option | Example | Meaning |
|---|---|---|
| `--port` | `--port 9000` | Use a different port |
| `--host` | `--host 0.0.0.0` | Allow other devices on your network |
| `TRACKER_PASSWORD` | `TRACKER_PASSWORD=abc` | Ask for a password |
| `TRACKER_DATA` | `TRACKER_DATA=/home/me/tracker-data` | Keep data in another folder |

## Start automatically on Linux (optional)

Create `~/.config/systemd/user/life-tracker.service`:

```ini
[Unit]                                                                      
  Description=Life Tracker                                                    
  After=network-online.target                                                 
                                                                              
  [Service]                                                                   
  WorkingDirectory=/home/keny/life-tracker                                    
  Environment=TRACKER_PASSWORD=1234                                           
  ExecStart=/usr/bin/python3 server.py --host 0.0.0.0                         
  Restart=on-failure                                                          
                                                                              
  [Install]                                                                   
  WantedBy=default.target 
```

Then:

```bash
systemctl --user daemon-reload                
systemctl --user enable --now life-tracker
systemctl --user status life-tracker
```

## Your data is safe

- Everything lives in the `data/` folder. Updating `server.py` or `static/index.html` never touches it.
- A backup is made automatically every day in `data/backups/` (last 30 kept).
- A backup is also made before any database change.
- To back up manually, copy the whole `data/` folder.
- To move to another computer, copy `data/` into the new `life-tracker/` folder.

Read **GUIDE.md** before changing any code. It explains what each part does and how to add features without losing data.
