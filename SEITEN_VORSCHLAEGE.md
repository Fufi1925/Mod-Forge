# ModForge – Welche Seiten kann man noch hinzufügen?

---

## 🔴 Dashboard-Seiten (fehlen am meisten)

Das User-Dashboard hat aktuell nur **3 Unterseiten** (Overview, Modules, Welcome).
Der Bot hat aber **24 konfigurierbare Module**. Diese Seiten fehlen:

### 1. `/dashboard/<id>/logs` — Log-Konfiguration
> Drag & Drop Kanal-Zuweisung für alle 25+ Log-Module
- Welcher Kanal bekommt welche Logs?
- Module per Toggle an/aus
- Filter pro Modul (Bots ignorieren, nur bestimmte Channels)
- Live-Vorschau der letzten Log-Einträge

### 2. `/dashboard/<id>/automod` — AutoMod Regeln
> Visueller Editor für alle AutoMod-Einstellungen
- Bad-Words Liste verwalten (hinzufügen/löschen)
- Regex-Regeln erstellen mit Live-Test
- Link-Filter: Erlaubte Domains verwalten
- Spam-Limits einstellen (Slider)
- CAPS/Emoji-Schwellwerte
- Bestrafung pro Regel wählen (Dropdown)

### 3. `/dashboard/<id>/security` — Security Center
> Übersicht aller Security-Module auf einen Blick
- Anti-Nuke: Threshold, Window, Bestrafung
- Anti-Raid: Join-Limit, Account-Alter, Auto-Lockdown
- Anti-Spam: Nachrichtenlimit, Duplikat-Filter
- Anti-Mention: Max Mentions
- Anti-Scam: An/Aus, Bestrafung
- Security Level (0-3) Slider
- Whitelist verwalten (User/Rollen/Channels)

### 4. `/dashboard/<id>/cases` — Case-Explorer
> Alle Moderation-Cases durchsuchen und verwalten
- Tabelle mit Filtern (User, Mod, Typ, Datum)
- Case-Details anklicken
- Grund bearbeiten
- Proof-URLs hinzufügen
- Export als CSV
- Statistik: Cases pro Tag/Woche (Chart)

### 5. `/dashboard/<id>/tickets` — Ticket-System
> Ticket-Einstellungen im Browser
- Kategorie wählen
- Log-Channel setzen
- Ticket-Panel anpassen (Titel, Beschreibung, Emoji)
- Aktive Tickets anzeigen

### 6. `/dashboard/<id>/warns` — Warn-System
> Warn-Schwellen und Decay konfigurieren
- Schwellen-Editor: Bei 3 Warns → Timeout, bei 5 → Kick, bei 7 → Ban
- Warn-Decay: Nach X Tagen automatisch verfallen
- Warn-Historie pro User durchsuchen

### 7. `/dashboard/<id>/autoresponse` — Auto-Antworten
> Auto-Responses verwalten ohne Discord-Commands
- Trigger hinzufügen/löschen
- Antwort bearbeiten
- Toggle aktiv/inaktiv
- Cooldown pro Trigger einstellen
- Test-Funktion

### 8. `/dashboard/<id>/roles` — Rollen-Manager
> Auto-Roles, Sticky-Roles, Reaction-Roles
- Auto-Roles: Welche Rollen bei Join?
- Sticky-Roles: Welche Rollen bleiben nach Rejoin?
- Reaction-Roles: Panel erstellen
- Verify-Rollen konfigurieren

### 9. `/dashboard/<id>/backup` — Backup-Manager
> Backups erstellen, anschauen, wiederherstellen
- Alle Backups als Liste
- Backup-Details mit allen gesicherten Daten
- Auto-Backup Zeitplan einstellen
- Ein-Klick Restore
- Cross-Server Restore mit Passwort

### 10. `/dashboard/<id>/settings` — Allgemeine Einstellungen
> Grundeinstellungen des Bots für diesen Server
- Prefix ändern
- No-Prefix Modus + Whitelist
- Bot-Sprache
- Report-Channel
- Appeal-Channel
- Auto-Ban-Appeal Toggle
- Invite-Tracking Toggle

---

## 🟡 Öffentliche Seiten (nice to have)

### 11. `/compare` — Bot-Vergleich
> ModForge vs. MEE6 vs. Carl-bot vs. Dyno
- Feature-Matrix als Tabelle
- ✅/❌ für jeden Bot
- Highlights wo ModForge besser ist
- "Wechsel jetzt" Button

### 12. `/changelog/<version>` — Einzelne Changelog-Seiten
> Jede Version als eigene Seite mit Details
- Aktuell: Eine Seite für alle Versionen
- Besser: Einzelseiten mit Screenshots, GIFs
- Verlinkbar (z.B. in Discord Announcements)

### 13. `/stats` (öffentlich) — Globale Bot-Statistiken
> Öffentliche Statistik-Seite mit Live-Zahlen
- Gesamte Server
- Gesamte Mitglieder
- Cases heute/diese Woche
- Geblockte Spam-Nachrichten
- Uptime-Verlauf (Chart)
- Reaktionszeit-Graph

### 14. `/demo` — Interaktive Demo
> Teste ModForge-Features ohne Discord
- Simulierter Chat mit Spam → AutoMod blockt
- Simulierter Nuke-Angriff → Anti-Nuke reagiert
- Dashboard-Preview (Screenshots/GIFs)
- "Überzeugt? Bot einladen" CTA

### 15. `/server-check` — Server Security Audit
> Öffentliches Tool: Wie sicher ist mein Server?
- User loggt sich ein
- Bot analysiert seinen Server
- Gibt einen Security-Score (0-100)
- Empfehlungen was aktiviert werden sollte
- "Ein Klick Setup" Buttons

---

## 🟢 Admin-Panel Erweiterungen

### 16. `/admin/logs` — System-Logs
> Alle Bot-Logs im Browser lesen
- Filter nach Level (ERROR, WARNING, INFO)
- Suche nach Guild/User
- Live-Tail (neue Logs in Echtzeit)

### 17. `/admin/users` — User-Verwaltung
> Globale User-Datenbank durchsuchen
- User-ID suchen
- Alle Cases/Warns über alle Server
- Globaler Ban (wenn der Bot auf mehreren Servern ist)

### 18. `/admin/config` — Config-Editor
> Server-Configs direkt im Browser bearbeiten
- JSON-Editor mit Syntax-Highlighting
- Validierung bevor gespeichert wird
- Reset auf Default

---

## 🔵 Meine Empfehlung — Reihenfolge

| Prio | Seite | Warum |
|------|-------|-------|
| **1** | `/dashboard/<id>/security` | Das Dashboard ist der Hauptgrund warum Leute ModForge nutzen — aktuell kann man Security dort nicht konfigurieren |
| **2** | `/dashboard/<id>/logs` | Logs konfigurieren ist der #1 Use-Case nach dem Einladen |
| **3** | `/dashboard/<id>/cases` | Case-Explorer ist das was Mods täglich brauchen |
| **4** | `/dashboard/<id>/automod` | AutoMod-Regeln im Browser bearbeiten statt per Command |
| **5** | `/dashboard/<id>/settings` | No-Prefix, Report-Channel, Prefix — alles zentral |
| **6** | `/dashboard/<id>/warns` | Warn-Schwellen visuell einstellen |
| **7** | `/dashboard/<id>/autoresponse` | Auto-Responses ohne Commands |
| **8** | `/dashboard/<id>/roles` | Rollen-Management zentral |
| **9** | `/dashboard/<id>/tickets` | Ticket-System per Browser |
| **10** | `/dashboard/<id>/backup` | Backups visuell verwalten |
| **11** | `/compare` | Marketing-Seite die User überzeugt |
| **12** | `/stats` (öffentlich) | Vertrauen aufbauen mit echten Zahlen |
| **13** | `/demo` | Nutzer überzeugen ohne Discord |
| **14** | `/server-check` | Viraler Content — Leute teilen ihren Score |
