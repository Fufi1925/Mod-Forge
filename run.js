require('dotenv').config();

const http = require('node:http');
const { BOT_TOKEN, devBanner, devPrint } = require('./bot/config');
const { ModForge } = require('./bot/bot');

function startWebStatus(bot) {
  const port = Number(process.env.PORT || 7860);
  const server = http.createServer((req, res) => {
    const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
    const ready = Boolean(bot?.isReady?.());
    const guilds = bot?.guilds?.cache?.size || 0;
    const members = bot?.guilds?.cache?.reduce?.((sum, guild) => sum + (guild.memberCount || 0), 0) || 0;
    const payload = {
      ok: true,
      service: 'ModForge Node Bot',
      bot_ready: ready,
      guilds,
      members,
      uptime: Math.floor(process.uptime()),
      timestamp: new Date().toISOString(),
    };

    if (url.pathname === '/health' || url.pathname === '/healthz' || url.pathname === '/api/status') {
      res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(payload, null, 2));
      return;
    }

    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(`<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ModForge Bot Status</title>
<style>
body{margin:0;min-height:100vh;background:radial-gradient(circle at top,#1e1b4b,#050510 60%);color:#f8fafc;font-family:Inter,system-ui,Segoe UI,sans-serif;display:grid;place-items:center}
.card{width:min(720px,calc(100% - 32px));background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:24px;padding:32px;box-shadow:0 24px 80px rgba(0,0,0,.35);backdrop-filter:blur(18px)}
h1{margin:0 0 8px;font-size:2rem}.muted{color:#94a3b8}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:24px}.stat{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:16px}.val{font-size:1.5rem;font-weight:900}.ok{color:#4ade80}.warn{color:#fbbf24}code{background:rgba(0,0,0,.35);padding:3px 7px;border-radius:8px}</style>
</head>
<body><main class="card">
<h1>🛡️ ModForge Node Bot</h1>
<p class="muted">Der Discord-Bot läuft über Node.js. Das alte Python-Dashboard muss separat deployed werden, wenn du das volle Web-Dashboard willst.</p>
<div class="grid">
<div class="stat"><div class="muted">Bot</div><div class="val ${ready ? 'ok' : 'warn'}">${ready ? 'Online' : 'Startet'}</div></div>
<div class="stat"><div class="muted">Server</div><div class="val">${guilds}</div></div>
<div class="stat"><div class="muted">Member</div><div class="val">${members.toLocaleString('de-DE')}</div></div>
<div class="stat"><div class="muted">Uptime</div><div class="val">${payload.uptime}s</div></div>
</div>
<p class="muted" style="margin-top:24px">Healthcheck: <code>/health</code></p>
</main></body></html>`);
  });

  server.listen(port, '0.0.0.0', () => {
    devPrint(`HTTP-Status-Webserver läuft auf Port ${port}`, 'success', 'Web');
  });
}

async function main() {
  if (!BOT_TOKEN) {
    devPrint('DISCORD_TOKEN fehlt! Bitte in .env oder Umgebung setzen.', 'error', 'Startup');
    process.exit(1);
  }

  const bot = new ModForge();
  global.BOT_REF = bot;
  startWebStatus(bot);

  devBanner('ModForge startet', 'Version: v3.0.0-node', 'Web-Dashboard: Python/Flask bleibt separat', 'Discord-Bot: wird verbunden', 'info', 'Startup');
  await bot.start(BOT_TOKEN);
}

main().catch((error) => {
  console.error('❌ ModForge konnte nicht starten:', error);
  process.exit(1);
});
