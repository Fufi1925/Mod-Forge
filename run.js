require('dotenv').config();

const { BOT_TOKEN, devBanner, devPrint } = require('./bot/config');
const { ModForge } = require('./bot/bot');

async function main() {
  if (!BOT_TOKEN) {
    devPrint('DISCORD_TOKEN fehlt! Bitte in .env oder Umgebung setzen.', 'error', 'Startup');
    process.exit(1);
  }

  const bot = new ModForge();
  global.BOT_REF = bot;

  devBanner('ModForge startet', 'Version: v3.0.0-node', 'Web-Dashboard: Python/Flask bleibt separat', 'Discord-Bot: wird verbunden', 'info', 'Startup');
  await bot.start(BOT_TOKEN);
}

main().catch((error) => {
  console.error('❌ ModForge konnte nicht starten:', error);
  process.exit(1);
});
