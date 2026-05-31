# ModForge – Changelog 29. Mai 2026

## Neues komplettes Dashboard mit 15 Seiten

Das User-Dashboard hatte bisher nur 3 Seiten (Übersicht, Module, Welcome).
Jetzt gibt es **15 Seiten** – jedes einzelne Bot-Modul ist im Browser konfigurierbar.

### Neue Dashboard-Seiten

| Seite | URL | Was man dort einstellen kann |
|-------|-----|------------------------------|
| **Security Center** | `/dashboard/<id>/security` | Alle 6 Security-Module auf einer Seite: Anti-Spam (Nachrichtenlimit, Zeitfenster, CAPS-Schwelle, Emoji-Max, Bestrafung), Anti-Nuke (Schwelle, Window, Bestrafung), Anti-Raid (Join-Limit, Account-Alter), Anti-Mention (Max Mentions), Anti-Scam (An/Aus, Bestrafung), AutoMod (Bestrafung). Security Level 0-3 mit Buttons. Whitelist-Übersicht. |
| **AutoMod** | `/dashboard/<id>/automod` | Verbotene Wörter hinzufügen/löschen mit Tags. Regex-Regeln mit Live-Editor. Erlaubte Domains verwalten. Invite-Filter, Link-Filter, Zalgo-Filter, Phishing-Check jeweils als Toggle. Bestrafung wählen. |
| **Log-Konfiguration** | `/dashboard/<id>/logs` | Standard-Log-Kanal setzen. Für jedes der 25+ Module einen eigenen Kanal zuweisen: Moderation, Anti-Spam, Anti-Nuke, Anti-Raid, Voice, Members, Nicknames, Channels, Roles, Webhooks, Tickets, Verify, Warns, Cases, Backup, Welcome, Messages, Leave, Errors, Audit, Appeal, Permissions. |
| **Case-Explorer** | `/dashboard/<id>/cases` | Alle Cases in einer Tabelle mit Spalten: ID, Aktion (farbiger Badge), User-ID, Moderator-ID, Grund, Datum. Live-Suche über User-ID und Grund. Filter nach Aktionstyp (Ban, Kick, Warn, Timeout, Softban, Tempban, Tempmute). |
| **Warn-System** | `/dashboard/<id>/warns` | Warn-Schwellen visuell einstellen: Bei X Warns → Timeout/Kick/Ban. Neue Schwellen hinzufügen mit Dropdown. Warn-Decay: Toggle + Tage-Eingabe (Warns verfallen nach X Tagen). |
| **Ticket-System** | `/dashboard/<id>/tickets` | Ticket-System An/Aus Toggle. Ticket-Kategorie wählen (Dropdown aller Kategorien). Log-Kanal für Transkripte setzen. |
| **Auto-Antworten** | `/dashboard/<id>/autoresponse` | Neue Trigger + Antwort hinzufügen. Alle aktiven Antworten als Liste mit Toggle An/Aus und Löschen-Button. |
| **Rollen-Manager** | `/dashboard/<id>/roles` | Auto-Roles: Rollen die neue Member automatisch bekommen (hinzufügen/löschen aus Dropdown). Sticky-Roles: Rollen die nach Leave+Rejoin zurückkommen. Verify-System: Modus (One-Click/Captcha) und Aktiv-Toggle. |
| **Backup-Manager** | `/dashboard/<id>/backup` | Übersicht aller Backups mit Label, ID, Datum. Stats: Anzahl Backups, Auto-Backup Status, Intervall. Auto-Backup Einstellungen: Toggle, Intervall (Stunden), Max. Backups. |
| **Einstellungen** | `/dashboard/<id>/settings` | Prefix ändern. No-Prefix Modus Toggle + User-Whitelist verwalten. Report-Kanal und Appeal-Kanal setzen. Auto Ban-Appeal Toggle. Invite-Tracking Toggle. Nachrichtenarchiv Toggle. Gefahrenzone: Config komplett zurücksetzen. |

### Dashboard-Navigation

Alle 15 Seiten haben jetzt eine **einheitliche Navigation** oben mit Links zu: Übersicht, Security, AutoMod, Logs, Cases, Warns, Module, Welcome, Rollen, Auto-Antworten, Tickets, Backup, Settings. Plus User-Avatar, Username und Logout.

### Save-System

Jede Dashboard-Seite hat eine **Save-Bar** unten die erscheint sobald man etwas ändert. "Speichern" sendet die Änderungen an die API. "Verwerfen" lädt die Seite neu.

---

## 5 neue API-Endpoints

| Methode | URL | Zweck |
|---------|-----|-------|
| `POST` | `/api/guild/<id>/config` | Universal-Config-Endpoint: Kann Security-Module, Warn-System, Logging, Prefix, No-Prefix, Channels und alle Einstellungen auf einmal setzen. Unterstützt `_reset` für Config-Reset. |
| `POST` | `/api/guild/<id>/automod` | Bad-Words, Regex-Regeln und erlaubte Domains hinzufügen/löschen |
| `POST` | `/api/guild/<id>/autoresponse` | Auto-Antworten hinzufügen, löschen, togglen |
| `POST` | `/api/guild/<id>/roles` | Auto-Roles und Sticky-Roles hinzufügen/löschen |
| `POST` | `/api/guild/<id>/noprefix` | No-Prefix Whitelist User hinzufügen/löschen |

---

## 2 neue öffentliche Seiten

| Seite | URL | Inhalt |
|-------|-----|--------|
| **Bot-Vergleich** | `/compare` | Feature-Matrix: ModForge vs. MEE6 vs. Carl-bot vs. Dyno. 16 Features verglichen mit ✅/⚠️/❌. ModForge hat alle 16 Features, MEE6 nur 3, Carl-bot 5, Dyno 4. Preis-Vergleich am Ende. |
| **Öffentliche Statistiken** | `/public-stats` | Live-Zahlen: Server, Mitglieder, Uptime, Latenz, Cases, Shards. Wird direkt vom Bot aktualisiert. |

---

## Admin-Panel Erweiterung

| Seite | URL | Inhalt |
|-------|-----|--------|
| **System-Logs** | `/admin/logs` | Bot-Logs im Browser. Filter nach Level (ERROR/WARNING/INFO). Textsuche. Farblich hervorgehoben. |

---

## Zusammenfassung in Zahlen

| Vorher | Nachher |
|--------|---------|
| 67 Templates | **82 Templates** (+15) |
| 3 Dashboard-Seiten | **15 Dashboard-Seiten** (+12) |
| 2 API-Endpoints | **7 API-Endpoints** (+5) |
| 65 Routes | **81 Routes** (+16) |
| Kein Modul im Dashboard konfigurierbar | **Jedes Modul** im Dashboard konfigurierbar |
