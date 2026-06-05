import re

# 1. Update bot/config.py
with open("bot/config.py", "r", encoding="utf-8") as f:
    text = f.read()

if '"temp_voice":' not in text:
    tv_config = """    "temp_voice": {
        "enabled": False,
        "category_id": None,
        "hub_channel_id": None,
        "interface_channel_id": None,
        "name_template": "🔊 {user}'s Kanal"
    },
    "anti_spam": {"""
    text = text.replace('"anti_spam": {', tv_config)
    with open("bot/config.py", "w", encoding="utf-8") as f:
        f.write(text)

# 2. Update database/db.py
with open("database/db.py", "r", encoding="utf-8") as f:
    text = f.read()

if 'def aadd_temp_voice' not in text:
    tv_db = """    # ── Temp Voice ─────────────────────────────────────────
    async def aadd_temp_voice(self, guild_id: int, channel_id: int, owner_id: int) -> None:
        try:
            await self.data.insert_one({
                "type": "temp_voice",
                "guild_id": guild_id,
                "channel_id": channel_id,
                "owner_id": owner_id,
                "created_at": datetime.datetime.utcnow()
            })
        except PyMongoError as e:
            log.error(f"DB aadd_temp_voice Fehler: {e}")

    async def aget_temp_voice(self, channel_id: int) -> Optional[dict]:
        try:
            return await self.data.find_one({"type": "temp_voice", "channel_id": channel_id})
        except PyMongoError:
            return None

    async def aremove_temp_voice(self, channel_id: int) -> None:
        try:
            await self.data.delete_one({"type": "temp_voice", "channel_id": channel_id})
        except PyMongoError:
            pass
            
    async def aupdate_temp_voice_owner(self, channel_id: int, new_owner_id: int) -> None:
        try:
            await self.data.update_one({"type": "temp_voice", "channel_id": channel_id}, {"$set": {"owner_id": new_owner_id}})
        except PyMongoError:
            pass

    # ── TempActions ─────────────────────────────────────────"""
    text = text.replace("    # ── TempActions ─────────────────────────────────────────", tv_db)
    with open("database/db.py", "w", encoding="utf-8") as f:
        f.write(text)

print("Config and DB patched.")
