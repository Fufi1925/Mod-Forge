# ModForge – Komplettes Changelog · 28. Mai 2026

> Zusammenfassung **aller** Änderungen, Fixes und neuen Features die heute eingebaut wurden.

---

## Inhaltsverzeichnis

1. [Bug-Fixes](#1-bug-fixes)
2. [Discord OAuth2 Login Fix](#2-discord-oauth2-login-fix)
3. [Fehlende HTML-Templates](#3-fehlende-html-templates)
4. [Style.css Erweiterungen](#4-stylecss-erweiterungen)
5. [Bot Voice-Logging](#5-bot-voice-logging)
6. [Neue Commands](#6-neue-commands)
7. [Gelöschte Commands](#7-gelöschte-commands)
8. [No-Prefix System](#8-no-prefix-system)
9. [Anti-Nuke Verbesserungen](#9-anti-nuke-verbesserungen)
10. [DM-System für Mod-Aktionen](#10-dm-system-für-mod-aktionen)
11. [Auto-Ban-Appeal](#11-auto-ban-appeal)
12. [Bot-Selbstschutz](#12-bot-selbstschutz)
13. [HELP_DATA Update](#13-help_data-update)
14. [Dateien-Übersicht](#14-dateien-übersicht)

---

## 1. Bug-Fixes

### `web/config.py` — Falscher Env-Variablen-Name
```python
# VORHER (Bug):
DISCORD_CLIENT_SECRET = os.getenv("I18whwiwvwjwk")   # ❌ Zufälliger String

# NACHHER (Fix):
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")  # ✅
```
**Auswirkung:** Der gesamte Discord-Login war kaputt, weil das Client-Secret nie geladen wurde.

### `web/app.py` — Doppelte `run_flask()` Definition
- `run_flask()` war **2x definiert** (Zeile 75 und 86)
- Die zweite überschrieb die erste → `background_emitter` wurde nie gestartet
- **Fix:** Eine saubere Definition, `socketio.start_background_task()` korrekt eingebaut

### `web/routes.py` — Falsche Funktionsaufrufe
```python
# VORHER (Bug):
_build_overview(guild_id)           # ❌ Fehlendes cfg Argument
_build_module_form(guild_id)        # ❌ Fehlende section + cfg
_build_welcome_content(guild_id)    # ❌ Fehlendes cfg Argument

# NACHHER (Fix):
cfg = _get_guild_config(guild_id)
_build_overview(cfg, guild_id)                      # ✅
_build_module_form(section, cfg, guild_id)           # ✅
_build_welcome_content(cfg, guild_id)                # ✅
```

### `.env` — Aufgeräumt
- `DISCORD_CLIENT_ID` auf `1491447622442160248` gesetzt
- `DASHBOARD_BASE_URL` und `OAUTH2_REDIRECT` korrekt eingetragen
- Keine unnötigen Variablen mehr

---

## 2. Discord OAuth2 Login Fix

**Problem:** Login schlug immer fehl mit "API-Fehler. Bitte erneut versuchen."

**3 Ursachen gefunden und behoben:**

| Problem | Fix |
|---------|-----|
| Kein `User-Agent` Header | Discord API blockiert Requests ohne User-Agent → Header hinzugefügt |
| `guilds.join` Scope | Dieser Scope braucht Bot-Token, nicht User-Token → Entfernt, nur `identify guilds` |
| Generische Fehlermeldung | Jetzt zeigt die Login-Seite den **echten** Discord-Fehler (Token, Profil, Guilds separat) |

**Zusätzliche Verbesserungen in `auth.py`:**
- Detailliertes Logging mit `logging.getLogger("ModForge.Auth")`
- `error` und `error_description` von Discord werden ausgewertet
- State-Mismatch gibt jetzt "Session abgelaufen" statt generischer Fehler
- `secure` Cookie-Flag dynamisch (`request.is_secure`)
- Guild-Liste Typ-Prüfung (fallback auf leere Liste)

---

## 3. Fehlende HTML-Templates

**50 neue HTML-Dateien** erstellt die in `routes.py` referenziert wurden aber nicht existierten:

### Hauptseiten (21)
| Datei | Route | Beschreibung |
|-------|-------|-------------|
| `features.html` | `/features` | Feature-Übersicht mit Karten |
| `commands.html` | `/commands` | Command-Liste mit Live-Suche |
| `ai.html` | `/ai` | KI-Features |
| `economy.html` | `/economy` | Economy System |
| `badges.html` | `/badges` | Badge-System mit Raritäten |
| `security.html` | `/security` | Security-Module |
| `pricing.html` | `/pricing` | Free/Premium/Enterprise Preise |
| `templates.html` | `/templates` | Server-Templates |
| `integrations.html` | `/integrations` | Tool-Integrationen |
| `widgets.html` | `/widgets` | Embeddable Widgets |
| `migrate.html` | `/migrate` | Bot-Migration |
| `emojis.html` | `/emojis` | Emoji Manager |
| `api-docs.html` | `/api-docs` | API Dokumentation |
| `branding.html` | `/branding` | Brand Assets |
| `tutorials.html` | `/tutorials` | Tutorial-Übersicht |
| `faq.html` | `/faq` | FAQ mit Accordion |
| `roadmap.html` | `/roadmap` | Feature-Roadmap |
| `blog.html` | `/blog` | Blog |
| `downloads.html` | `/downloads` | Downloads & Ressourcen |
| `uptime.html` | `/uptime` | Uptime Monitor |
| `legal.html` | `/legal` | Rechtliches |

### Community (10)
`partners.html`, `affiliate.html`, `suggest.html`, `contact.html`, `showcase.html`, `testimonials.html`, `leaderboard.html`, `jobs.html`, `events.html`, `support.html`

### Docs (6)
`docs.html`, `docs/setup.html`, `docs/automod.html`, `docs/moderation.html`, `docs/tickets.html`, `docs/music.html`

### Status (2)
`status/incidents.html`, `status/maintenance.html`

### Error Pages (3)
`errors/404.html`, `errors/403.html`, `errors/500.html`

### Admin Panel (5)
`admin/login.html`, `admin/dashboard.html`, `admin/guilds.html`, `admin/guild_detail.html`, `admin/stats.html`

### User Dashboard (3)
`dashboard/overview.html`, `dashboard/modules.html`, `dashboard/welcome.html`

**Alle 17 bestehenden Templates blieben 1:1 unverändert.**

---

## 4. Style.css Erweiterungen

**662 neue Zeilen** (1513 → 2175 Zeilen). Neue CSS-Klassen:

| Klasse | Zweck |
|--------|-------|
| `.glass-card` | Universelle Glassmorphism-Karte mit Hover-Effekt |
| `.cmd-item` | Command-Einträge auf der Commands-Seite |
| `.admin-nav`, `.admin-body` | Admin-Panel Navigation und Layout |
| `.dash-nav`, `.dash-body` | User-Dashboard Navigation und Layout |
| `.stat-card`, `.stat-value`, `.stat-label` | Statistik-Karten (Admin, Uptime) |
| `.login-card`, `.login-input`, `.login-error` | Admin-Login Formular |
| `.guild-row` | Admin Guild-Liste mit Hover |
| `.blog-card` | Blog-Karten mit Bild |
| `.lb-row`, `.lb-rank` | Leaderboard-Einträge |
| `.roadmap-item` | Roadmap Timeline-Einträge |
| `.api-method`, `.api-endpoint`, `.api-response` | API-Docs Styling |
| `.badge-rarity` (.legendary/.epic/.rare/.exclusive) | Badge-Raritäten |
| `.event-status` (.active/.ended/.planned) | Event-Status-Tags |
| `.job-tag`, `.job-status` | Job-Listen Tags |
| `.status-dot` (.ok/.warn/.error/.info) | Status-Punkte mit Animation |
| `.form-group` | Formular-Gruppen (Contact/Suggest) |
| `.docs-back` | Docs-Breadcrumb-Link |
| `.color-swatch` | Branding Farbfelder |
| `.widget-code` | Widget Code-Blöcke |
| `.uptime-bar` | Uptime-Verlauf Balken |
| `.error-page`, `.error-code` | Error-Seiten |
| `.migrate-row` | Migration-Einträge |
| `.pricing-popular` | Pricing Glow-Border |
| Responsive `@media` | Admin + Dashboard für Mobile |

---

## 5. Bot Voice-Logging

**20 neue Log-Events** im `on_voice_state_update`:

| Event | Log-Nachricht | Audit-Log |
|-------|--------------|-----------|
| 📤 Voice Disconnect | User aus Call gekickt | ✅ Wer |
| ↔️ Voice Verschoben | In anderen Channel bewegt | ✅ Wer |
| 🔇 Server Mute | Mikrofon stummgeschaltet | ✅ Wer + Grund |
| 🔊 Server Unmute | Mikrofon entstummgeschaltet | ✅ Wer |
| 🔇 Server Deafen | Audio taubgeschaltet | ✅ Wer + Grund |
| 🔊 Server Undeafen | Taub aufgehoben | ✅ Wer |
| 🔇 Self Mute | Selbst stummgeschaltet | — |
| 🔊 Self Unmute | Selbst entstummgeschaltet | — |
| 🔇 Self Deafen | Selbst taubgeschaltet | — |
| 🔊 Self Undeafen | Selbst Taub aufgehoben | — |
| 📺 Stream gestartet | User streamt | — |
| 📺 Stream beendet | Stream beendet | — |
| 📹 Kamera an | Kamera eingeschaltet | — |
| 📹 Kamera aus | Kamera ausgeschaltet | — |
| 🎙️ Zum Zuhörer | Stage-Channel | — |
| 🎙️ Zum Sprecher | Stage-Channel | — |

**+ 2 Events in `on_member_update`:**
| Event | Details |
|-------|---------|
| 🔇 Timeout gesetzt | Wer + Grund + Dauer + Discord-Timestamp |
| 🔊 Timeout aufgehoben | Wer + ob manuell oder abgelaufen |

---

## 6. Neue Commands

### Slash-Commands (neu)

| Command | Beschreibung | Prefix |
|---------|-------------|--------|
| `/userinfo [@user]` | Account-Alter, Risk-Score, Cases, Voice-Status, Rollen | `!userinfo` |
| `/serverinfo` | Members, Channels, Boosts, ModForge-Module | `!serverinfo` |
| `/modstats [@mod]` | Bans/Kicks/Warns/Mutes pro Mod + Ranking | `!modstats` |
| `/softban @user [days] [grund]` | Ban+Unban (löscht Nachrichten) | `!softban` |
| `/report @user <grund>` | Meldet User ans Mod-Team | `!report` |
| `/report_setup #channel` | Setzt Report-Kanal | `!report_setup` |
| `/invites [@user]` | Invite-Statistiken | `!invites` |
| `/invites_leaderboard` | Top-Einlader | — |
| `/lockall [grund]` | Sperrt ALLE Text-Kanäle | `!lockall` |
| `/unlockall` | Entsperrt alle Kanäle | `!unlockall` |
| `/autoresponse_add <trigger> <antwort>` | Auto-Antwort hinzufügen | — |
| `/autoresponse_list` | Alle Auto-Antworten | — |
| `/autoresponse_del <index>` | Auto-Antwort löschen | — |
| `/warndecay <tage>` | Warns verfallen nach X Tagen | `!warndecay` |
| `/noprefix [on/off]` | No-Prefix-Modus | `!noprefix` |
| `/noprefix_add @user` | User zur No-Prefix Whitelist | `!noprefix add @user` |
| `/noprefix_remove @user` | User von Whitelist entfernen | `!noprefix remove @user` |
| `/noprefix_list` | Whitelist anzeigen | `!noprefix list` |
| `/autobanappeal [on/off]` | Auto Ban-Appeal DMs | `!autobanappeal` |

### Neue Prefix-Commands (die vorher fehlten)

`!tempban`, `!tempmute`, `!case`, `!cases`, `!status`, `!stats`, `!help`, `!panic`, `!unlockdown`, `!autorole`, `!massban`, `!report_setup`, `!autobanappeal`

---

## 7. Gelöschte Commands

| Command | Grund |
|---------|-------|
| `/vote` | Kein top.gg Link konfiguriert |
| `/vote_setup` | Gehört zum Vote-System |
| `/vote_status` | Gehört zum Vote-System |
| `/tempkick` | Sinnlos (Kick ist schon temporär) |
| `vote_reward_role` Config | Nicht mehr benötigt |

---

## 8. No-Prefix System

Mods können ohne `!` oder `/` direkt moderieren:

```
ban @User Spam          ← statt !ban @User Spam
kick @User Beleidigung  ← statt /kick
userinfo @User          ← sofort Info
```

**Whitelist-System:**
- `/noprefix true` → Aktiviert
- `/noprefix_add @User` → Fügt User zur Whitelist hinzu
- `/noprefix_remove @User` → Entfernt User
- `/noprefix_list` → Zeigt Whitelist
- **Ohne Whitelist:** Alle mit `Manage Messages` dürfen No-Prefix nutzen
- **Mit Whitelist:** Nur gelistete User

**Erlaubte No-Prefix Commands:**
`ban`, `kick`, `warn`, `mute`, `unmute`, `clear`, `lock`, `unlock`, `nick`, `softban`, `lockall`, `unlockall`, `slowmode`, `tempban`, `tempmute`, `unban`, `userinfo`, `serverinfo`, `modstats`, `invites`, `report`, `cases`, `case`, `status`, `stats`, `help`, `panic`, `unlockdown`, `massban`, `autorole`, `warnings`, `clearwarnings`

Konfigurierbar im Dashboard über `POST /api/guild/<id>/noprefix`.

---

## 9. Anti-Nuke Verbesserungen

### Hierarchie-Check
```
1. Bot prüft: Ist meine Rolle hoch genug um den Angreifer zu bestrafen?
2. NEIN → Owner bekommt SOFORT DM:
   ⚠️ ANTI-NUKE ALARM — Bot kann nicht handeln!
   • Wer der Angreifer ist
   • Was er getan hat
   • WARUM der Bot nicht handeln kann (Rollen-Hierarchie)
   • 4 konkrete Handlungsanweisungen
3. JA → Normale Bestrafung + Lockdown + Owner-DM
```

### Nie gegen sich selbst oder Owner
```python
# _nuke_check prüft jetzt ZUERST:
if executor.id == bot.user.id:    # Bin ich das?  → return
if executor.id == guild.owner_id:  # Ist das der Owner? → return
```

### Owner-DM Duplikat-Schutz
- `safe_dm()` mit 60s Cooldown für Nuke-Alerts
- `safe_dm()` mit 120s Cooldown für Hierarchie-Warnungen
- Selbe DM wird NIE doppelt gesendet

---

## 10. DM-System für Mod-Aktionen

### `safe_dm()` — Neue Hilfsfunktion
```python
await safe_dm(user, embed, cooldown_key="warn:123:456", cooldown_seconds=30)
```
- Duplikat-Schutz per `cooldown_key`
- Standard: 30 Sekunden Cooldown
- Automatische Cleanup alter Einträge (>5 min)
- Gibt `True/False` zurück ob gesendet
- Fängt `Forbidden` und `HTTPException` ab

### User-DMs bei allen Mod-Aktionen

| Aktion | DM-Inhalt | Zeitpunkt |
|--------|-----------|-----------|
| **Warn** | Grund + Anzahl Verwarnungen + Server | Nach dem Warn |
| **Kick** | Grund + Server | **VOR** dem Kick (danach unmöglich) |
| **Ban** | Grund + Server + Appeal-Info (wenn aktiv) | **VOR** dem Ban |
| **Timeout gesetzt** | Dauer + Grund + Ablaufzeit + Moderator | Via `on_member_update` |
| **Timeout aufgehoben** | Wer/ob automatisch + Server | Via `on_member_update` |

---

## 11. Auto-Ban-Appeal

```
/autobanappeal true   → Aktiviert
/autobanappeal false  → Deaktiviert
!autobanappeal        → Toggle
```

Wenn aktiviert bekommt jeder gebannte User eine DM:
```
🔨 Du wurdest gebannt
Server: Gaming Hub DE
Grund: Spam

📋 Ban-Appeal:
Du kannst einen Entbannungsantrag stellen.
Sende !start in diese DM um den Prozess zu starten.
```
Nutzt das bestehende `!banappeal` System für den Appeal-Prozess.

---

## 12. Bot-Selbstschutz

`is_whitelisted()` prüft jetzt **immer zuerst**:
```python
if member.id == self.user.id:         # → True (Bot ist immer whitelisted)
if member.id == member.guild.owner_id: # → True (Owner immer geschützt)
```

Der Bot wird **niemals**:
- Sich selbst bannen, kicken, warnen, muten
- Den Server-Owner bestrafen
- Gegen sich selbst im Anti-Nuke, Anti-Spam etc. handeln

---

## 13. HELP_DATA Update

Komplett neu geschrieben mit **9 Kategorien**:

| Kategorie | Commands |
|-----------|----------|
| 🛡️ Moderation | ban, tempban, softban, kick, warn, warnings, clearwarning, clearwarnings, mute, tempmute, unmute, clear, slowmode, lock, unlock, lockall, unlockall, unban, nick, massban |
| 👥 Info & Stats | userinfo, serverinfo, modstats, status, stats, case, cases, reason, addproof |
| 🔒 Security | security_level, panic, unlockdown, warnsetup, warndecay |
| 🤖 AutoMod & Filter | autoresponse_add, autoresponse_list, autoresponse_del |
| 📢 Logging | logs, logset, logreset, logview, logmodules, report, report_setup |
| ⚙️ Setup & System | setup, help, noprefix, setup_verify, verify_roles, setup_tickets, forcereset |
| 🔧 Tools & Extras | invites, invites_leaderboard, autorole, autorole_remove, stickyrole, stickyrole_remove, reactionrole, tempvoice_setup, welcome_setup, welcome_channel, leave_channel |
| 🛡️ Backup | backup, backup_create, backup_list, backup_restore, backup_delete, backup_autosetup |
| 👑 Admin | massunban, massrole_remove, audit-perms, setarchive |

---

## 14. Dateien-Übersicht

### Geänderte Dateien

| Datei | Zeilen | Änderung |
|-------|--------|----------|
| `bot/bot.py` | 6.705 | Voice-Logging, 20 neue Commands, DM-System, Anti-Nuke Fixes, safe_dm, Selbstschutz |
| `bot/config.py` | 476 | HELP_DATA neu, 8 neue Config-Felder, Vote entfernt |
| `web/auth.py` | 215 | Komplett neu: User-Agent, Logging, Error-Handling, Scope-Fix |
| `web/config.py` | 8 | `DISCORD_CLIENT_SECRET` Env-Fix |
| `web/app.py` | 80 | Doppelte `run_flask()` gefixt |
| `web/routes.py` | 1.030 | Funktionsaufrufe gefixt, API-Endpoints für No-Prefix |
| `web/static/style.css` | 2.175 | 662 neue Zeilen für alle neuen Templates |

### Neue Dateien

| Datei | Beschreibung |
|-------|-------------|
| 50 HTML-Templates | Siehe [Abschnitt 3](#3-fehlende-html-templates) |
| `.env` | Aufgeräumt mit korrekten Variablen |

### Gesamtstatistik

| Metrik | Wert |
|--------|------|
| Python-Dateien | 13 |
| HTML-Templates | 67 |
| CSS-Zeilen | 2.175 |
| Slash-Commands | 82 |
| Prefix-Commands | 38 |
| Event-Handler | 20 |
| Syntax-Fehler | 0 ✅ |
