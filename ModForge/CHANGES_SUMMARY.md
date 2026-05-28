# ModForge – Änderungen & Fixes

## 🐛 Gefixte Bugs

### 1. `web/config.py` – Falscher Env-Variable-Name
```python
# VORHER (Bug):
DISCORD_CLIENT_SECRET = os.getenv("I18whwiwvwjwk")  # ❌ Falscher Key!

# NACHHER (Fix):
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")  # ✅ Korrekt
```

### 2. `web/app.py` – Doppelte `run_flask()` Definition
- `run_flask()` war 2x definiert (Zeile 75 und 86)
- Die erste Definition wurde von der zweiten überschrieben
- `background_emitter` wurde nie gestartet
- **Fix:** Eine saubere `run_flask()` mit `socketio.start_background_task()`

### 3. `web/routes.py` – Falsche Funktionsaufrufe für Guild-Dashboard
```python
# VORHER (Bug):
overview = _build_overview(guild_id)           # ❌ Fehlende cfg
form = _build_module_form(guild_id)            # ❌ Fehlende section + cfg
content = _build_welcome_content(guild_id)     # ❌ Fehlende cfg

# NACHHER (Fix):
cfg = _get_guild_config(guild_id)
overview = _build_overview(cfg, guild_id)                          # ✅
form = _build_module_form(section, cfg, guild_id)                  # ✅
content = _build_welcome_content(cfg, guild_id)                    # ✅
```

### 4. `web/auth.py` – Verbesserte Fehlerbehandlung
- Bessere Fehlerbehandlung bei OAuth2 Callback
- `error` Parameter von Discord wird jetzt abgefangen
- `access_token` Validation hinzugefügt
- `secure` Cookie-Flag dynamisch gesetzt
- Guild-Liste Typ-Prüfung hinzugefügt
- Logging bei Fehlern

## 📄 Neu erstellte HTML-Templates (48 Dateien)

### Hauptseiten (21 Dateien)
| Datei | Route | Beschreibung |
|-------|-------|-------------|
| `features.html` | `/features` | Feature-Übersicht mit Karten |
| `commands.html` | `/commands` | Command-Liste mit Suche |
| `ai.html` | `/ai` | KI-Features Vorstellung |
| `economy.html` | `/economy` | Economy System |
| `badges.html` | `/badges` | Badge-System mit Raritäten |
| `security.html` | `/security` | Security-Module Übersicht |
| `pricing.html` | `/pricing` | Preisübersicht (Free/Premium/Enterprise) |
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
| `blog.html` | `/blog` | Blog-Übersicht |
| `downloads.html` | `/downloads` | Downloads & Ressourcen |
| `uptime.html` | `/uptime` | Uptime Monitor |
| `legal.html` | `/legal` | Rechtliche Infos |

### Community-Seiten (9 Dateien)
| Datei | Route |
|-------|-------|
| `partners.html` | `/partners` |
| `affiliate.html` | `/affiliate` |
| `suggest.html` | `/suggest` |
| `contact.html` | `/contact` |
| `showcase.html` | `/showcase` |
| `testimonials.html` | `/testimonials` |
| `leaderboard.html` | `/leaderboard` |
| `jobs.html` | `/jobs` |
| `events.html` | `/events` |
| `support.html` | `/support` |

### Docs Unterseiten (6 Dateien)
| Datei | Route |
|-------|-------|
| `docs.html` | `/docs` |
| `docs/setup.html` | `/docs/setup` |
| `docs/automod.html` | `/docs/automod` |
| `docs/moderation.html` | `/docs/moderation` |
| `docs/tickets.html` | `/docs/tickets` |
| `docs/music.html` | `/docs/music` |

### Status Unterseiten (2 Dateien)
| Datei | Route |
|-------|-------|
| `status/incidents.html` | `/status/incidents` |
| `status/maintenance.html` | `/status/maintenance` |

### Error Pages (3 Dateien)
| Datei | HTTP Code |
|-------|-----------|
| `errors/404.html` | 404 Not Found |
| `errors/403.html` | 403 Forbidden |
| `errors/500.html` | 500 Internal Error |

### Admin Panel (4 Dateien)
| Datei | Route |
|-------|-------|
| `admin/login.html` | `/admin/login` |
| `admin/dashboard.html` | `/admin/dashboard` |
| `admin/guilds.html` | `/admin/guilds` |
| `admin/guild_detail.html` | `/admin/guilds/<id>` |
| `admin/stats.html` | `/admin/stats` |

### User Dashboard (3 Dateien)
| Datei | Route |
|-------|-------|
| `dashboard/overview.html` | `/dashboard/<guild_id>` |
| `dashboard/modules.html` | `/dashboard/<guild_id>/modules` |
| `dashboard/welcome.html` | `/dashboard/<guild_id>/welcome` |

## 🔐 Discord OAuth2 Login

Der Login-Flow funktioniert so:
1. User klickt "Mit Discord anmelden" auf `/login`
2. → Redirect zu `/dashboard/login`
3. → Discord OAuth2 Authorization
4. → Callback auf `/dashboard/auth/callback`
5. → Session Cookie wird gesetzt
6. → Redirect zu `/dashboard`

**Wichtige Env-Variablen für Discord OAuth2:**
- `DISCORD_CLIENT_ID` – Discord Application Client ID
- `DISCORD_CLIENT_SECRET` – Discord Application Client Secret
- `DASHBOARD_BASE_URL` – Die Basis-URL (z.B. `https://mod-forge.up.railway.app`)

**Discord Developer Portal Einstellung:**
- Redirect URI muss auf `{DASHBOARD_BASE_URL}/dashboard/auth/callback` zeigen
