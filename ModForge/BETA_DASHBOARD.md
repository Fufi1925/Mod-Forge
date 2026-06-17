# ModForge BETA Dashboard - Implementation Report

Datum: 2026-06-17

## Neue Dashboard-Tab "BETA"

URL: `/dashboard/<guild_id>/beta`

### Was wurde implementiert:

#### 1. Theme-System (8 Themes) 🎨
- 🌙 Dark (Standard)
- ☀️ Light
- 🌌 Midnight
- 🌅 Sunset
- 🌲 Forest
- ⚡ Neon
- 🌊 Ocean
- 💜 Lavender

Theme wird in MongoDB Collection `server_themes` gespeichert.
Überlebt Neustarts.

#### 2. Toggle-Einstellungen ⚙️
- 🔔 **Auto-DM bei Strafen** - User bekommen DM bei Ban/Kick/Timeout/Warn
- ⏱️ **Smart Timeout Suggestions** - Bot schlägt Timeout-Dauer vor
- 🚨 **Risk-Alerts** - Mods werden bei hohem Risk-Score benachrichtigt

Gespeichert in `cfg.beta_features` der Guild-Config (überlebt Neustart).

#### 3. Ban-Appeals Verwaltung 📋
- Liste aller Appeals aus MongoDB Collection `appeals`
- Buttons: ✓ Annehmen, ✗ Ablehnen, 🗑 Löschen
- Status-Tracking (pending/approved/rejected)
- Persistiert in MongoDB

#### 4. Staff-Bewerbungen Verwaltung 📝
- Liste aller Bewerbungen aus MongoDB Collection `staff_applications`
- Buttons: ✓ Annehmen, ✗ Ablehnen, 🗑 Löschen
- Status-Tracking (pending/approved/rejected)
- Persistiert in MongoDB

### API-Endpoints

```
POST /api/guild/<guild_id>/beta/theme         - Theme speichern
POST /api/guild/<guild_id>/beta/settings      - Toggle-Einstellungen
POST /api/guild/<guild_id>/beta/appeals/<id>  - Appeal Aktion
POST /api/guild/<guild_id>/beta/staff/<id>     - Staff Aktion
GET  /api/guild/<guild_id>/beta/risk/<user>   - Risk-Profil
```

### Datenbank-Erweiterungen

**Neue Collections in `Database.__init__`:**
- `appeals`
- `staff_applications`
- `server_themes`

**Neue Methoden (11 Stück):**
- `aget_all_appeals(guild_id, limit)`
- `aget_appeal_by_id(appeal_id)`
- `aupdate_appeal_status(appeal_id, status, reviewer_id)`
- `adelete_appeal(appeal_id)`
- `acount_appeals(guild_id, status)`
- `aget_all_staff_applications(guild_id, limit)`
- `aget_staff_application_by_id(app_id)`
- `aupdate_staff_application_status(app_id, status, reviewer_id, notes)`
- `adelete_staff_application(app_id)`
- `acount_staff_applications(guild_id, status)`
- `acount_server_themes(guild_id)`

### Navigation

Sidebar in `_base.html` UND `_nav.html` haben jetzt den Beta-Tab:
- Icon: 🧪
- BETA-Badge in Orange
- Markiert als experimentelles Feature

### Bug-Fixes

1. **`events.py`**: `check_phishing_url` wurde aus `bot.embed_config` importiert (falsch). Korrekt: aus `bot.utils`.
2. **`verification.py`**: `generate_captcha` wurde aus `bot.embed_config` importiert (falsch). Korrekt: aus `bot.utils`.
3. **`bot/utils.py`**: `safe_dm` Funktion hinzugefügt (war nur in `bot.bot.py`).
4. **`database/db.py`**: Fehlende Collections `appeals`, `staff_applications`, `server_themes` zum `__init__` hinzugefügt.
5. **`database/db.py`**: Kaputtes `return {...}` Statement in `aget_server_theme` repariert.

### Verifikation

```
✓ 13/13 cogs laden
✓ Alle DB-Methoden vorhanden
✓ Alle DB-Collections initialisiert
✓ Alle 6 Routen registriert
✓ beta.html Template existiert (317 Zeilen)
✓ Navigation in beiden Templates aktualisiert
✓ Flask-Test-Client funktioniert (Status 200, Redirects OK)
```

### Hinweise für Benutzer

⚠️ **Alle Beta-Features** sind als experimentell markiert. Es können Fehler auftreten.
📊 **Datenpersistenz**: Alle Einstellungen werden in MongoDB gespeichert.
🔄 **Nach Neustart**: Alle Themes, Toggles, Appeals und Bewerbungen bleiben erhalten.
