# 🛡️ ModForge – Feature-Vorschläge (Moderation-Fokus)

> Alles bleibt ein **Mod-Bot**. Keine Gimmicks – nur Features die Moderatoren **wirklich** brauchen.

---

## 🔴 PRIO 1 — Fehlt am meisten

### 1. `/userinfo` & `/serverinfo`
Jeder Mod braucht diese Commands täglich.
```
/userinfo @User
→ Account-Alter, Join-Datum, Rollen, Cases-Anzahl, Timeout-Status,
  Voice-Status, höchste Rolle, Nitro-Boost, Risk-Score
  
/serverinfo
→ Member-Count, Rollen-Anzahl, Channels, Boosts, Security-Level,
  ModForge-Module aktiv/inaktiv, Top-Moderatoren
```

### 2. `/modstats` – Moderator-Statistiken
Zeigt wer wie viel moderiert hat.
```
/modstats [@mod] [zeitraum]
→ Bans: 12 | Kicks: 5 | Warns: 34 | Mutes: 18
→ Letzter Case: vor 2h
→ Ranking unter allen Mods
```

### 3. `/history` / `/modlog` – User Mod-History
Alle Moderation-Aktionen zu einem User auf einen Blick.
```
/history @User
→ Case #14: Warn – Spam (von @Mod1, 3d ago)
→ Case #11: Timeout 1h – Beleidigung (von @Mod2, 1w ago)
→ Case #7: Kick – Wiederholter Verstoß (von @Mod1, 2w ago)
```

### 4. `/note` – Interne Moderator-Notizen
Notizen zu Usern die nicht als Warn zählen, aber Mods informieren.
```
/note @User "Alt-Account von xyz, beobachten"
/notes @User → Zeigt alle Notizen
/delnote @User <id> → Löscht eine Notiz
```

---

## 🟡 PRIO 2 — Sehr nützlich

### 5. Anti-Alt / Alt-Detection
Erkennt Alt-Accounts automatisch.
```
- Account < X Tage alt → Warn an Mod-Log
- Kein Avatar + Kein Banner + Username-Pattern → Markierung
- Optional: Auto-Kick / Quarantäne-Rolle
- /altscan → Scannt alle Member nach verdächtigen Accounts
```

### 6. `/softban` – Kick + Message-Purge
Bannt und entbannt sofort (löscht Nachrichten).
```
/softban @User [days] [reason]
→ Bannt User (löscht X Tage Nachrichten)
→ Entbannt sofort wieder
→ Logged als "Softban" Case
```

### 7. `/snipe` & `/editsnipe`
Zeigt zuletzt gelöschte/editierte Nachricht.
```
/snipe [#channel] → Zeigt letzte gelöschte Nachricht
/editsnipe [#channel] → Zeigt Original vor Edit
(Auto-Löschen nach 5 Min, nur für Mods)
```

### 8. Raid-Mode Verbesserungen
```
/raidmode on [dauer] → Manueller Raid-Modus
  → Alle neuen Joins bekommen Quarantäne-Rolle
  → Nur verifizierte User können schreiben
  → DM an neue Member: "Server ist im Raid-Modus"
  
/raidmode off → Deaktiviert + gibt Quarantäne-Usern Zugang
/raidmode status → Zeigt aktuellen Status
```

### 9. `/purge` Erweiterungen
```
/purge user @User [amount] → Nur von einem User
/purge bots [amount] → Nur Bot-Nachrichten
/purge links [amount] → Nur Nachrichten mit Links
/purge images [amount] → Nur Bilder/Attachments
/purge embeds [amount] → Nur Embeds
/purge mentions [amount] → Nur mit Mentions
/purge after <message_id> → Alles nach einer Nachricht
/purge between <id1> <id2> → Zwischen zwei Nachrichten
```

### 10. Auto-Mod Regex Rules im Dashboard
```
/automod addrule <name> <regex> <action>
/automod rules → Zeigt alle Regeln
/automod delrule <name>
/automod testrule <name> "Test Nachricht"
→ Im Dashboard: Visual Regex Builder
```

---

## 🟢 PRIO 3 — Nice to have

### 11. Channel-Quarantäne
```
/quarantine #channel → Alle können lesen, niemand schreiben
/quarantine @User → User kann nichts schreiben (überall)
/unquarantine → Hebt auf
```

### 12. `/massaction` – Bulk-Moderation
```
/masskick <role> [reason] → Kickt alle mit einer Rolle
/masstimeout <role> <duration> → Timeout für alle mit Rolle
/massrole_add <from_role> <to_role> → Rolle allen geben die X haben
```

### 13. Scheduled Actions / Timed Commands
```
/schedule warn @User "Spam" in 2h → Warn in 2 Stunden
/schedule lock #channel in 30m → Channel locken in 30 Min
/schedule unlock #channel at 18:00 → Channel um 18:00 freigeben
/schedule purge #channel 100 every 24h → Auto-Purge
/schedules → Zeigt alle geplanten Aktionen
```

### 14. `/report` – User-Report-System
```
/report @User <reason> → Meldet User ans Mod-Team
→ Mod-Log bekommt Embed mit Report
→ Reaction-Buttons: ✅ Handled | ❌ Dismiss | 🔨 Action
→ /reports → Zeigt offene Reports
```

### 15. Role-Persist (Sticky Roles V2)
```
→ Rollen bleiben auch bei Leave+Rejoin
→ Besonders für Mute-Rollen: User kann nicht "unmuten" durch Leave
→ Log: "Sticky-Rollen wiederhergestellt für @User: @Muted, @Verified"
```

### 16. Logging Dashboard Erweiterungen
```
/logfilter set <modul> ignore_bots:true → Bots ignorieren
/logfilter set <modul> ignore_roles:@role → Rolle ignorieren
/logfilter set <modul> only_channels:#ch → Nur bestimmte Channels
→ Im Web-Dashboard: Drag & Drop Log-Config
```

### 17. `/embed` – Embed Builder Command
```
/embed create #channel → Öffnet Modal für Title, Desc, Color, etc.
/embed edit <message_id> → Bearbeitet existierendes Embed
/embed send #channel <json> → Sendet rohes Embed-JSON
→ Für Regel-Channels, Announcements etc.
```

### 18. Invite Tracker
```
/invites @User → Zeigt wer wie viele eingeladen hat
/invites leaderboard → Top-Einlader
/invites reset → Tracker zurücksetzen
→ Log: "User123 hat Server über Invite XYZ von Mod1 betreten"
→ Fake-Invite-Erkennung (Leave+Rejoin)
```

### 19. AFK System
```
/afk [grund] → Setzt User als AFK
→ Bei Mention: "User ist AFK: Grund"
→ Bei nächster Nachricht: Auto-Unafk + "Welcome back"
```

### 20. `/lockall` / `/unlockall`
```
/lockall [reason] → Sperrt ALLE Text-Channels
/unlockall → Entsperrt alle
→ Nützlich bei Raids
→ Log zeigt alle betroffenen Channels
```

---

## 🔵 Dashboard/Web Features

### 21. Case-Explorer im Web-Dashboard
```
→ Alle Cases durchsuchbar (User, Mod, Typ, Datum)
→ Filtern: Nur Bans / Warns / Mutes
→ Case bearbeiten (Grund ändern, Proof hinzufügen)
→ Export als CSV
```

### 22. Mod-Action Heatmap
```
→ Zeigt wann am meisten moderiert wird (Stunde/Tag)
→ Hilft bei Mod-Schichtplanung
→ "Sonntags 20-23h meiste Aktionen"
```

### 23. Auto-Response System (im Dashboard)
```
→ Trigger-Wort/Regex → Auto-Antwort
→ z.B. "wie beitreten" → "Nutze /ticket für Support"
→ Configurable per Dashboard
→ Cooldown pro User
```

### 24. Warn-Decay System
```
→ Warns verfallen nach X Tagen automatisch
→ /warndecay set 30d → Warns verfallen nach 30 Tagen
→ Oder: "Warn-Gewicht" sinkt über Zeit (3→2→1→0)
→ Thresholds basieren auf aktivem Warn-Gewicht
```

---

## Empfehlung: Reihenfolge

| Phase | Features | Aufwand |
|-------|----------|---------|
| **Sofort** | userinfo, serverinfo, modstats, history, note | Mittel |
| **Woche 1** | purge-Erweiterungen, softban, snipe, embed builder | Klein |
| **Woche 2** | Alt-Detection, Raid-Mode V2, report-system | Mittel |
| **Woche 3** | Scheduled Actions, invite-tracker, warn-decay | Groß |
| **Woche 4** | Dashboard: Case-Explorer, Heatmap, Auto-Response | Groß |
