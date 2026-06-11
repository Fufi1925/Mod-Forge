from dotenv import load_dotenv
load_dotenv()

from web.app import keep_alive
from bot.config import BOT_TOKEN, dev_print, dev_banner
from bot.bot import bot

if __name__ == "__main__":
    if not BOT_TOKEN:
        dev_print("DISCORD_TOKEN fehlt! Bitte in .env oder Umgebung setzen.", "error", "Startup")
        keep_alive()
        import sys

        sys.exit(1)
    keep_alive()
    dev_banner("ModForge startet", "Version: v3.0.0", "Web-Dashboard: aktiv", "Discord-Bot: wird verbunden", level="info", area="Startup")
    bot.run(BOT_TOKEN, log_handler=None)
