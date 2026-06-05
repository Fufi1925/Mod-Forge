import re

with open('web/routes.py', 'r', encoding='utf-8') as f:
    text = f.read()

# wir ersetzen den ticker filter:
# Alle Server mit > 100 Membern sollen in den payload.
ticker_logic_old = """    # Check ticker guilds in DB
    ticker_ids = []
    if bot_ready() and db:
        try:
            doc = safe_async(db.data.find_one({"type": "ticker_guilds"}), None)
            if doc and "guilds" in doc:
                ticker_ids = [str(x) for x in doc["guilds"]]
        except Exception as e:
            log.error(f"[TICKER FETCH ERROR] {e}")

    # Filter payload
    guilds_payload = [g for g in guilds_payload if str(g["id"]) in ticker_ids]
    guilds_payload.sort(key=lambda x: x["members"], reverse=True)

    if not guilds_payload:
        guilds_payload = [
            {'name':'ModForge Support', 'members':1, 'online':1, 'security':'100%', 'avatar_url':'https://cdn.discordapp.com/embed/avatars/0.png'}
        ]"""

ticker_logic_new = """    # Filter payload: Nur Server mit >= 100 Mitgliedern
    guilds_payload = [g for g in guilds_payload if g.get("members", 0) >= 100]
    guilds_payload.sort(key=lambda x: x["members"], reverse=True)
    
    # Fallback, falls der Bot noch auf keinem Server mit >100 Usern ist
    if not guilds_payload:
        guilds_payload = [
            {'name':'ModForge Support', 'members':125, 'online':42, 'security':'100%', 'avatar_url':'https://cdn.discordapp.com/embed/avatars/0.png'}
        ]"""

text = text.replace(ticker_logic_old, ticker_logic_new)

with open('web/routes.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("routes.py gepatcht für ticker >= 100")
