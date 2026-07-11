require('dotenv').config();

const { BOT_TOKEN, devBanner, devPrint } = require('./bot/config');
const { ModForge } = require('./bot/bot');
const { startNodeWeb } = require('./web/server');

async function closeHttpServer(server) {
  if (!server?.listening) return;
  await new Promise((resolve) => server.close(() => resolve()));
}

function validateEnvironment() {
  const required = ['DISCORD_TOKEN', 'MONGO_URL'];
  if (process.env.NODE_ENV === 'production') {
    required.push('DISCORD_CLIENT_ID', 'DISCORD_CLIENT_SECRET', 'ADMIN_USERNAME', 'ADMIN_PASSWORD');
  }
  const missing = required.filter(name => !String(process.env[name] || '').trim());
  if (missing.length) {
    devPrint(`Fehlende Umgebungsvariablen: ${missing.join(', ')}`, 'error', 'Startup');
    devPrint('Setze die Variablen in Railway unter Service → Variables und starte das Deployment neu.', 'error', 'Startup');
    return false;
  }
  return true;
}

async function main() {
  if (!BOT_TOKEN || !validateEnvironment()) {
    process.exitCode = 1;
    return;
  }

  const bot = new ModForge();
  global.BOT_REF = bot;
  const webServer = startNodeWeb(bot);
  let shuttingDown = false;
  let reconnectTimer = null;

  async function shutdown(signal, exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    devPrint(`${signal}: ModForge wird sauber beendet.`, 'warning', 'Startup');

    const forceTimer = setTimeout(() => {
      devPrint('Graceful-Shutdown-Zeit überschritten; Prozess wird beendet.', 'error', 'Startup');
      process.exit(1);
    }, 15_000);
    forceTimer.unref();

    try {
      await closeHttpServer(webServer);
      if (bot.isReady()) bot.destroy();
      await bot.db.close().catch(() => null);
      clearTimeout(forceTimer);
      process.exit(exitCode);
    } catch (error) {
      devPrint(`Fehler beim Beenden: ${error.stack || error.message}`, 'error', 'Startup');
      clearTimeout(forceTimer);
      process.exit(1);
    }
  }

  process.once('SIGTERM', () => void shutdown('SIGTERM'));
  process.once('SIGINT', () => void shutdown('SIGINT'));
  process.on('unhandledRejection', (reason) => {
    devPrint(`Unbehandelte Promise-Ablehnung: ${reason?.stack || reason}`, 'error', 'Startup');
  });
  process.on('uncaughtException', (error) => {
    devPrint(`Unbehandelte Exception: ${error.stack || error.message}`, 'error', 'Startup');
    void shutdown('uncaughtException', 1);
  });

  async function connectBot() {
    if (shuttingDown || bot.isReady()) return;
    try {
      await bot.start(BOT_TOKEN);
      devPrint('Discord-Bot erfolgreich verbunden.', 'success', 'Startup');
    } catch (error) {
      devPrint(`Discord-/MongoDB-Verbindung fehlgeschlagen: ${error.stack || error.message}`, 'error', 'Startup');
      devPrint('Website bleibt online; neuer Verbindungsversuch in 30 Sekunden.', 'warning', 'Startup');
      reconnectTimer = setTimeout(() => void connectBot(), 30_000);
      reconnectTimer.unref();
    }
  }

  devBanner('ModForge startet', 'Version: v3.0.0-node', 'Web-Dashboard: Node/Express aktiv', 'Discord-Bot: wird verbunden', 'info', 'Startup');
  await connectBot();
}

main().catch((error) => {
  console.error('❌ ModForge konnte nicht starten:', error);
  process.exit(1);
});
