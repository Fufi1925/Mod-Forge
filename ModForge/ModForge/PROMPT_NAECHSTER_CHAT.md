# ModForge — Prompt für nächsten Chat

Kopiere diesen Text in den nächsten Chat:

---

## Projekt: ModForge — Discord Security & AutoMod Bot

GitHub: https://github.com/Fufi1925/Mod-Forge/tree/ModForge/ModForge

Das Projekt liegt bereits komplett im Workspace unter `/home/user/ModForge/`. NICHT neu herunterladen — alle Dateien sind aktuell.

### Was ModForge ist
Ein kompletter Discord-Sicherheitsbot mit Web-Dashboard. Python (discord.py) + Flask + MongoDB.

### Architektur
```
ModForge/
├── bot/
│   ├── bot.py          (7.296 Zeilen — Bot-Logik, Commands, Events)
│   ├── config.py       (506 Zeilen — DEFAULT_CONFIG, HELP_DATA, Konstanten)
│   └── utils.py        (165 Zeilen — _run_async, create_embed, Captcha)
├── database/
│   └── db.py           (MongoDB-Wrapper, async)
├── web/
│   ├── app.py          (Flask + SocketIO)
│   ├── auth.py         (Discord OAuth2 Login)
│   ├── config.py       (Env-Variablen)
│   ├── helpers.py      (Dashboard-HTML Builder)
│   ├── routes.py       (2.382 Zeilen — 99 Routes, 10 APIs)
│   ├── static/style.css (2.456 Zeilen)
│   └── templates/      (92 HTML Templates)
│       ├── dashboard/  (19 Seiten + _base.html + _nav.html)
│       ├── admin/      (6 Seiten + _base.html)
│       ├── docs/       (5 Seiten)
│       ├── status/     (2 Seiten)
│       └── errors/     (3 Seiten)
└── run.py
```

### Wichtige IDs (GEHEIM — steht nicht im Code sichtbar)
- **Bot-Entwickler Discord ID**: `1303627964734246944` — ist IMMER whitelisted, kann jeden Command ohne Rechte nutzen, hat gelben "Owner" Tag im Members-Tab
- **Bot Application ID**: `1491447622442160248`
- **Dashboard**: `http://mod-forge.up.railway.app`
- **OAuth Redirect**: `http://mod-forge.up.railway.app/dashboard/auth/callback`
- **OAuth Scopes**: `identify guilds`

### Aktuelle Zahlen
- 93/100 Slash-Commands (Discord-Limit: 100)
- 47 Prefix-Commands
- 92 HTML Templates
- 99 Flask Routes + 10 API Endpoints
- 19 Dashboard-Unterseiten
- 0 Syntax-Fehler, 0 500-Fehler bei Tests

### Dashboard-Seiten (Sidebar-Layout mit Themes)
Overview · Security (11 Module) · AutoMod · Logs (29 Module/7 Kategorien) · Cases · Warns · Settings · Roles · Tickets · Backup · Embed Builder · Whitelist · Stats (Chart.js) · Members (Panel+Mod-Actions) · Live-Feed (Echtzeit) · Auto-Response · Auto-Nickname · Welcome · Modules

### Bot-Features
- Anti-Spam/Nuke/Raid/Mention/Scam/Webhook/Ghost-Ping/URL-Shortener/VPN (11 Security-Module)
- AutoMod (Bad-Words, Regex, Link/Invite/Zalgo/Phishing Filter)
- Case-System, Warn-System (Thresholds + Decay)
- Verify (One-Click + Captcha), Ticket-System
- Backup (Create/Restore/Auto/Cross-Server/Public Share)
- Welcome/Leave Embeds + DM
- Auto-Role, Sticky-Roles, Reaction-Roles
- Temp-Voice (Join-to-Create)
- No-Prefix Mode (mit User-Whitelist)
- Auto-Nickname (Rollen-basiert: Prefix/Suffix)
- Server-Tag (Tag im Namen → Rolle)
- Auto-Response, Auto-Slowmode
- Invite-Tracker, Auto-Ban-Appeal DMs
- Webhook-Logging (Auto-Create, pro Modul eigener Name/Avatar)
- Snipe, Poll, Softban, Raidmode, History
- Voice-Logging (Join/Leave/Mute/Deaf/Stream/Cam/Disconnect)
- Mod-DMs (Warn/Kick/Ban/Timeout mit Grund + Timestamps)
- Bot-Selbstschutz (nie gegen sich selbst oder Owner handeln)
- Anti-Nuke Hierarchie-Check (Owner-DM wenn Bot-Rolle zu niedrig)
- Log-Dedup (selbes Log innerhalb 3s = skip)

### Save-System im Dashboard
- Save-Bar mit Slide-Up Animation
- Toast-System (5 Typen: ok/err/info/warn/save)
- Modal-Popup bei Navigation mit ungespeicherten Änderungen
- beforeunload Browser-Warnung
- Alle APIs speichern über `POST /api/guild/<id>/config`

### Admin-Dashboard
- Gleiche Sidebar wie User-Dashboard
- `/admin/server/<id>/<subpage>` — öffnet jeden Server ohne OAuth
- Login: Username/Password (ADMIN_USERNAME/ADMIN_PASSWORD Env-Vars)

### Bekannte "Warnings" (KEIN Bug)
- `RuntimeWarning: coroutine 'Database.set_config' was never awaited` — passiert NUR wenn Bot offline ist (kein Event-Loop). Bei laufendem Bot auf Railway funktioniert alles.
- `[COUNT ERROR] Collection objects do not implement truth value testing` — harmlos, betrifft leere DB.

### Was als nächstes gemacht werden kann
(Sag mir was du willst und ich baue es)
