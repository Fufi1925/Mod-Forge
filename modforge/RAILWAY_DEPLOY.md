# ModForge automatisch auf Railway deployen

Das Repository ist so vorbereitet, dass Railway es direkt aus dem Repository-Hauptordner bauen kann. Ein manuelles Root Directory ist nicht erforderlich.

## 1. Repository zu GitHub hochladen

Im Repository-Hauptordner:

```bash
git add .
git commit -m "Make Node dashboard and Railway deployment production ready"
git push origin ModForge
```

Falls ein anderer Produktionsbranch verwendet wird, diesen statt `ModForge` pushen.

## 2. Railway-Projekt verbinden

1. In Railway ein neues Projekt öffnen.
2. **Deploy from GitHub repo** auswählen.
3. Das Repository `Fufi1925/Mod-Forge` auswählen.
4. Als Produktionsbranch `ModForge` auswählen.
5. Kein Root Directory eintragen. Railway findet `/railway.json` und `/Dockerfile` automatisch.
6. Unter **Settings → Networking** eine öffentliche Domain erzeugen.

Jeder weitere Push auf den in Railway ausgewählten Branch löst danach automatisch einen neuen Build und ein Deployment aus.

## 3. Railway-Variablen setzen

Unter **Service → Variables** müssen mindestens diese Variablen gesetzt werden:

```env
DISCORD_TOKEN=dein_discord_bot_token
DISCORD_CLIENT_ID=deine_discord_application_id
DISCORD_CLIENT_SECRET=dein_discord_oauth_client_secret
MONGO_URL=deine_mongodb_verbindungsurl
ADMIN_USERNAME=admin
ADMIN_PASSWORD=ein_sehr_langes_zufaelliges_passwort
DASHBOARD_BASE_URL=https://deine-railway-domain.up.railway.app
PUBLIC_BASE_URL=https://deine-railway-domain.up.railway.app
NODE_ENV=production
DASHBOARD_SESSION_TTL=2592000
```

`PORT` wird von Railway automatisch gesetzt und muss dort nicht manuell angelegt werden.

Keine echten Secrets in `.env.example`, Git oder GitHub Actions eintragen.

## 4. Discord OAuth2 konfigurieren

Im Discord Developer Portal unter **OAuth2 → Redirects** exakt diese URL eintragen:

```text
https://deine-railway-domain.up.railway.app/dashboard/auth/callback
```

Die URL muss exakt mit `DASHBOARD_BASE_URL` übereinstimmen. Kein abschließender Slash.

Unter **Bot → Privileged Gateway Intents** aktivieren:

- Presence Intent, falls Online-Status angezeigt werden soll
- Server Members Intent
- Message Content Intent

## 5. MongoDB vorbereiten

Eine erreichbare MongoDB-Instanz verwenden, beispielsweise MongoDB Atlas. Bei Atlas:

1. Datenbankbenutzer erstellen.
2. Netzwerkzugriff für Railway ermöglichen.
3. Verbindungszeichenfolge als `MONGO_URL` setzen.
4. Sonderzeichen im Benutzernamen oder Passwort URL-kodieren.

Die Anwendung verwendet die Datenbank `ModForge` und erstellt benötigte Collections und Indizes automatisch.

## 6. Automatische Prüfungen

GitHub Actions führt bei jedem Push aus:

- reproduzierbare Installation mit `npm ci`
- `npm audit --audit-level=high`
- Syntaxprüfung aller JavaScript-Dateien
- Laden und Serialisieren aller 75 Discord-Commands
- Rendering aller 30 Dashboard-Templates
- Rendering aller 29 regulären Dashboard-Seitenkontexte
- Syntaxprüfung der in den Templates eingebetteten JavaScript-Blöcke
- vollständigen Docker-Build

In Railway kann zusätzlich **Wait for CI** aktiviert werden, damit nur Commits mit erfolgreicher GitHub Action produktiv ausgerollt werden.

## 7. Healthcheck

Railway prüft automatisch:

```text
GET /health
```

Der Healthcheck ist in `railway.json` und im Dockerfile konfiguriert. Bei einem Prozessfehler startet Railway den Service gemäß Restart Policy neu.

## 8. Nach dem ersten Deployment prüfen

- `/health` liefert HTTP 200 und JSON.
- `/` zeigt die Website.
- `/dashboard/login` leitet zu Discord OAuth2 weiter.
- `/dashboard` zeigt die verwaltbaren Discord-Server.
- Ein Server-Tab wie `/dashboard/SERVER_ID/members` rendert das vollständige Members-Template.
- Der Bot erscheint in Discord online.
- Railway-Logs enthalten keine OAuth-, MongoDB- oder Intent-Fehler.

## Häufige Fehler

### `DISCORD_TOKEN fehlt`

`DISCORD_TOKEN` fehlt in Railway Variables oder enthält einen falschen Namen.

### OAuth `invalid redirect_uri`

Discord-Redirect und `DASHBOARD_BASE_URL` stimmen nicht exakt überein.

### MongoDB Timeout

Atlas-Netzwerkzugriff, Benutzer, Passwort und URL-Encoding prüfen.

### Bot startet, Member fehlen

Server Members Intent im Discord Developer Portal aktivieren und anschließend neu deployen.

### Railway baut aus dem falschen Ordner

Root Directory leer lassen. Die aktive Node.js-Anwendung liegt vollständig im Repository-Hauptordner. Dort befinden sich `package.json`, `package-lock.json`, `run.js`, `Dockerfile` und `railway.json`.

Railway soll bevorzugt den Root-Dockerfile verwenden. Falls im Railway-Dashboard manuelle Befehle gesetzt werden müssen:

```text
Build Command: npm ci --omit=dev
Start Command: node run.js
```

Bei Dockerfile-Deployment müssen Build Command und Start Command leer bleiben, weil der Dockerfile beides selbst festlegt.
