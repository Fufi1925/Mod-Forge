import re

with open('web/routes.py', 'r', encoding='utf-8') as f:
    text = f.read()

# wir müssen ticker server array machen
# db in python

ticker_logic = """
    guilds_payload.sort(key=lambda x: x["members"], reverse=True)

    db = get_db()
"""

new_ticker_logic = """
    db = get_db()
    
    # Check ticker guilds in DB
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

"""
text = text.replace(ticker_logic, new_ticker_logic)

with open('web/routes.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("routes.py gepatcht")
