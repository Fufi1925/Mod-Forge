from dotenv import load_dotenv
load_dotenv()

from web.app import keep_alive
from bot.config import BOT_TOKEN, log
from bot.bot import bot

if __name__ == "__main__":
    if not BOT_TOKEN:
        log.error("DISCORD_TOKEN fehlt!")
        keep_alive()
        import sys

        sys.exit(1)
    keep_alive()
    log.info("ModForge v3.0.0 startet…")
    bot.run(BOT_TOKEN, log_handler=None)
