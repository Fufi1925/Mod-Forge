# database/db.py
import asyncio
import datetime
import logging
import os
import time
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument, DESCENDING, ASCENDING
from cachetools import TTLCache

log = logging.getLogger("ModForge.DB")


class Database:
    CONFIG_CACHE_TTL = 300  # 5 Minuten
    CONFIG_CACHE_MAXSIZE = 10000
    WHITELIST_CACHE_TTL = 300
    WHITELIST_CACHE_MAXSIZE = 10000

    def __init__(self, mongo_url: str = None) -> None:
        mongo_url = os.getenv("MONGO_URL") or mongo_url or "mongodb://localhost:27017"
        self.client: AsyncIOMotorClient = AsyncIOMotorClient(
            mongo_url, serverSelectionTimeoutMS=8000, tlsAllowInvalidCertificates=True
        )
        self.db = self.client["ModForge"]

        self.config: AsyncIOMotorCollection = self.db["config"]
        self.whitelist: AsyncIOMotorCollection = self.db["whitelist"]
        self.data: AsyncIOMotorCollection = self.db["data"]
        self.tempactions: AsyncIOMotorCollection = self.db["tempactions"]
        self.cases: AsyncIOMotorCollection = self.db["cases"]
        self.counters: AsyncIOMotorCollection = self.db["counters"]
        self.message_archive: AsyncIOMotorCollection = self.db["message_archive"]
        self.guild_events: AsyncIOMotorCollection = self.db["guild_events"]
        self.server_accounts: AsyncIOMotorCollection = self.db["server_accounts"]

        self._config_cache: TTLCache = TTLCache(
            maxsize=self.CONFIG_CACHE_MAXSIZE, ttl=self.CONFIG_CACHE_TTL
        )
        self._whitelist_cache: TTLCache = TTLCache(
            maxsize=self.WHITELIST_CACHE_MAXSIZE, ttl=self.WHITELIST_CACHE_TTL
        )

        self._config_locks: Dict[int, asyncio.Lock] = {}
        self._whitelist_locks: Dict[int, asyncio.Lock] = {}

    # ── Hilfsfunktionen ─────────────────────────────────────
    def _trim_locks(
        self, locks_dict: Dict[int, asyncio.Lock], max_size: int = 100
    ) -> None:
        """Entfernt die ältesten Einträge, wenn die Map zu groß wird."""
        if len(locks_dict) > max_size:
            keys = list(locks_dict.keys())[:-max_size]
            for k in keys:
                del locks_dict[k]

    def _config_lock(self, guild_id: int) -> asyncio.Lock:
        self._trim_locks(self._config_locks)
        lock = self._config_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._config_locks[guild_id] = lock
        return lock

    def _whitelist_lock(self, guild_id: int) -> asyncio.Lock:
        self._trim_locks(self._whitelist_locks)
        lock = self._whitelist_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._whitelist_locks[guild_id] = lock
        return lock

    @staticmethod
    def _empty_whitelist() -> dict:
        return {
            "users": [],
            "roles": [],
            "channels": [],
            "bypass_antispam": [],
            "bypass_antinuke": [],
        }

    @staticmethod
    def _ensure_defaults(cfg: dict) -> dict:
        """Stellt sicher, dass alle Standard-Keys vorhanden sind. Erzeugt eine Kopie."""
        from bot.config import DEFAULT_CONFIG

        cfg = dict(cfg)  # Shallow Copy, tiefe Werte sind unveränderlich
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v.copy() if isinstance(v, (dict, list)) else v
            elif isinstance(v, dict) and isinstance(cfg[k], dict):
                for sub_k, sub_v in v.items():
                    cfg[k].setdefault(sub_k, sub_v)
        cfg.pop("_id", None)
        return cfg

    # ── Verbindungsprüfung (optional, wird in setup_hook aufgerufen) ──
    async def test_connection(self) -> bool:
        try:
            await self.client.admin.command("ping")
            log.info("MongoDB‑Verbindung erfolgreich getestet.")
            return True
        except PyMongoError as e:
            log.error(f"MongoDB‑Verbindungstest fehlgeschlagen: {e}")
            return False

    # ── Config ──────────────────────────────────────────────
    def get_config(self, guild_id: int) -> dict:
        """Synchroner Cache‑Lookup, Fallback Defaults."""
        cached = self._config_cache.get(guild_id)
        if cached is not None:
            return cached
        from bot.config import DEFAULT_CONFIG

        default = self._ensure_defaults(DEFAULT_CONFIG.copy())
        self._config_cache[guild_id] = default
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.fetch_config(guild_id))
        except RuntimeError:
            pass
        return default

    async def fetch_config(self, guild_id: int) -> dict:
        async with self._config_lock(guild_id):
            try:
                data = await self.config.find_one({"_id": guild_id})
            except PyMongoError as e:
                log.error(f"DB fetch_config Fehler: {e}")
                data = None
            if not data:
                from bot.config import DEFAULT_CONFIG

                data = DEFAULT_CONFIG.copy()
                data["_id"] = guild_id
                try:
                    await self.config.insert_one(data)
                except PyMongoError as e:
                    log.error(f"DB insert_one (config) Fehler: {e}")
            cleaned = self._ensure_defaults(data)
            self._config_cache[guild_id] = cleaned
            return cleaned

    async def set_config(self, guild_id: int, cfg: dict) -> None:
        cfg = dict(cfg)
        cfg["_id"] = guild_id
        try:
            await self.config.update_one({"_id": guild_id}, {"$set": cfg}, upsert=True)
        except PyMongoError as e:
            log.error(f"DB set_config Fehler: {e}")
        self._config_cache[guild_id] = self._ensure_defaults(cfg)

    async def update_module(
        self, guild_id: int, module: str, key: str, value: Any
    ) -> None:
        cfg = self._config_cache.get(guild_id) or await self.fetch_config(guild_id)
        cfg = dict(cfg)
        cfg.setdefault(module, {})
        if isinstance(cfg[module], dict):
            cfg[module] = {**cfg[module], key: value}
        else:
            cfg[module] = value
        await self.set_config(guild_id, cfg)

    async def aget_config(self, guild_id: int) -> dict:
        cached = self._config_cache.get(guild_id)
        if cached is not None:
            return cached
        return await self.fetch_config(guild_id)

    async def aset_config(self, guild_id: int, cfg: dict) -> None:
        await self.set_config(guild_id, cfg)

    async def aupdate_module(
        self, guild_id: int, module: str, key: str, value: Any
    ) -> None:
        await self.update_module(guild_id, module, key, value)

    # ── Whitelist ──────────────────────────────────────────
    def get_whitelist(self, guild_id: int) -> dict:
        cached = self._whitelist_cache.get(guild_id)
        if cached is not None:
            return cached
        empty = self._empty_whitelist()
        self._whitelist_cache[guild_id] = empty
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.fetch_whitelist(guild_id))
        except RuntimeError:
            pass
        return empty

    async def fetch_whitelist(self, guild_id: int) -> dict:
        async with self._whitelist_lock(guild_id):
            try:
                data = await self.whitelist.find_one({"_id": guild_id})
            except PyMongoError as e:
                log.error(f"DB fetch_whitelist Fehler: {e}")
                data = None
            if not data:
                data = self._empty_whitelist()
            for k in (
                "users",
                "roles",
                "channels",
                "bypass_antispam",
                "bypass_antinuke",
            ):
                data.setdefault(k, [])
            data.pop("_id", None)
            self._whitelist_cache[guild_id] = data
            return data

    async def set_whitelist(self, guild_id: int, whitelist: dict) -> None:
        whitelist = dict(whitelist)
        whitelist["_id"] = guild_id
        try:
            await self.whitelist.update_one(
                {"_id": guild_id}, {"$set": whitelist}, upsert=True
            )
        except PyMongoError as e:
            log.error(f"DB set_whitelist Fehler: {e}")
        whitelist.pop("_id", None)
        self._whitelist_cache[guild_id] = whitelist

    async def add_whitelist(self, guild_id: int, category: str, entry_id: int) -> None:
        data = await self.aget_whitelist(guild_id)
        data = dict(data)
        data.setdefault(category, [])
        if entry_id not in data[category]:
            data[category] = data[category] + [entry_id]
        await self.set_whitelist(guild_id, data)

    async def remove_whitelist(
        self, guild_id: int, category: str, entry_id: int
    ) -> None:
        data = await self.aget_whitelist(guild_id)
        data = dict(data)
        if category in data:
            data[category] = [x for x in data[category] if x != entry_id]
        await self.set_whitelist(guild_id, data)

    async def aget_whitelist(self, guild_id: int) -> dict:
        cached = self._whitelist_cache.get(guild_id)
        if cached is not None:
            return cached
        return await self.fetch_whitelist(guild_id)

    async def aadd_whitelist(self, guild_id: int, category: str, entry_id: int) -> None:
        await self.add_whitelist(guild_id, category, entry_id)

    async def aremove_whitelist(
        self, guild_id: int, category: str, entry_id: int
    ) -> None:
        await self.remove_whitelist(guild_id, category, entry_id)

    # ── Warnungen ───────────────────────────────────────────
    async def aadd_warning(
        self, guild_id: int, user_id: int, reason: str, mod_id: int
    ) -> int:
        try:
            await self.data.insert_one(
                {
                    "type": "warning",
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "reason": reason,
                    "mod_id": mod_id,
                    "timestamp": datetime.datetime.utcnow(),
                }
            )
        except PyMongoError as e:
            log.error(f"DB aadd_warning Fehler: {e}")
        warns = await self.aget_warnings(guild_id, user_id)
        return len(warns)

    async def aget_warnings(self, guild_id: int, user_id: int) -> List[dict]:
        try:
            cursor = self.data.find(
                {"type": "warning", "guild_id": guild_id, "user_id": user_id}
            )
            return await cursor.to_list(length=1000)
        except PyMongoError as e:
            log.error(f"DB aget_warnings Fehler: {e}")
            return []

    async def aclear_warnings(self, guild_id: int, user_id: int) -> int:
        try:
            res = await self.data.delete_many(
                {"type": "warning", "guild_id": guild_id, "user_id": user_id}
            )
            return res.deleted_count
        except PyMongoError as e:
            log.error(f"DB aclear_warnings Fehler: {e}")
            return 0

    async def aremove_warning(self, guild_id: int, user_id: int, index: int) -> bool:
        warns = await self.aget_warnings(guild_id, user_id)
        if 0 <= index < len(warns):
            try:
                await self.data.delete_one({"_id": warns[index]["_id"]})
                return True
            except PyMongoError as e:
                log.error(f"DB aremove_warning Fehler: {e}")
        return False

    # ── Mutes ───────────────────────────────────────────────
    async def aadd_mute(
        self,
        guild_id: int,
        user_id: int,
        reason: str,
        mod_id: int,
        duration: Optional[int] = None,
    ) -> None:
        end = None
        if duration:
            end = datetime.datetime.utcnow() + datetime.timedelta(seconds=duration)
        try:
            await self.data.update_one(
                {
                    "type": "mute",
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "active": True,
                },
                {
                    "$set": {
                        "type": "mute",
                        "guild_id": guild_id,
                        "user_id": user_id,
                        "reason": reason,
                        "mod_id": mod_id,
                        "duration": duration,
                        "end_time": end,
                        "active": True,
                        "timestamp": datetime.datetime.utcnow(),
                    }
                },
                upsert=True,
            )
        except PyMongoError as e:
            log.error(f"DB aadd_mute Fehler: {e}")

    async def aget_active_mutes(self) -> List[dict]:
        try:
            cursor = self.data.find({"type": "mute", "active": True})
            return await cursor.to_list(length=10000)
        except PyMongoError as e:
            log.error(f"DB aget_active_mutes Fehler: {e}")
            return []

    async def adeactivate_mute(self, guild_id: int, user_id: int) -> None:
        try:
            await self.data.update_many(
                {
                    "type": "mute",
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "active": True,
                },
                {"$set": {"active": False}},
            )
        except PyMongoError as e:
            log.error(f"DB adeactivate_mute Fehler: {e}")

    # ── TempActions ─────────────────────────────────────────
    async def aadd_tempaction(
        self,
        action: str,
        guild_id: int,
        user_id: int,
        end_time: datetime.datetime,
        reason: str,
        mod_id: int,
    ) -> None:
        try:
            await self.tempactions.insert_one(
                {
                    "action": action,
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "end_time": end_time,
                    "reason": reason,
                    "mod_id": mod_id,
                    "active": True,
                    "created": datetime.datetime.utcnow(),
                }
            )
        except PyMongoError as e:
            log.error(f"DB aadd_tempaction Fehler: {e}")

    async def aget_due_tempactions(self) -> List[dict]:
        try:
            cursor = self.tempactions.find(
                {
                    "active": True,
                    "end_time": {"$lte": datetime.datetime.utcnow()},
                }
            )
            return await cursor.to_list(length=1000)
        except PyMongoError as e:
            log.error(f"DB aget_due_tempactions Fehler: {e}")
            return []

    async def adeactivate_tempaction(self, _id: Any) -> None:
        try:
            await self.tempactions.update_one({"_id": _id}, {"$set": {"active": False}})
        except PyMongoError as e:
            log.error(f"DB adeactivate_tempaction Fehler: {e}")

    # ── Indexes ─────────────────────────────────────────────
    async def ensure_indexes(self) -> None:
        try:
            await self.message_archive.create_index(
                "timestamp", expireAfterSeconds=48 * 3600, name="ttl_archive_48h"
            )
            await self.message_archive.create_index(
                [
                    ("guild_id", ASCENDING),
                    ("user_id", ASCENDING),
                    ("timestamp", DESCENDING),
                ],
                name="archive_user_lookup",
            )
            await self.cases.create_index(
                [("guild_id", ASCENDING), ("case_id", ASCENDING)],
                unique=True,
                name="cases_unique_per_guild",
            )
            await self.cases.create_index(
                [("guild_id", ASCENDING), ("user_id", ASCENDING)],
                name="cases_user_lookup",
            )
            await self.guild_events.create_index(
                [("timestamp", DESCENDING)], name="events_recent"
            )
            await self.server_accounts.create_index(
                "guild_id", unique=True, name="sa_guild_unique"
            )
            # Backup-Collection Indizes
            try:
                backup_col = self.client["ModForge"]["backups"]
                await backup_col.create_index(
                    [("guild_id", 1), ("backup_id", 1)],
                    unique=True,
                    name="backup_guild_id_unique",
                )
                await backup_col.create_index(
                    [("guild_id", 1), ("created_at", -1)], name="backup_guild_created"
                )
            except Exception as e:
                log.warning(f"Backup-Index Fehler (nicht kritisch): {e}")
            log.info("MongoDB-Indizes erstellt/verifiziert.")
        except PyMongoError as e:
            log.error(f"DB ensure_indexes Fehler: {e}")

    # ── Cases ───────────────────────────────────────────────
    async def anext_case_id(self, guild_id: int) -> int:
        try:
            doc = await self.counters.find_one_and_update(
                {"_id": f"case_{guild_id}"},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            return int(doc["seq"])
        except PyMongoError as e:
            log.error(f"DB anext_case_id Fehler: {e}")
            return int(time.time())

    async def acreate_case(
        self,
        guild_id: int,
        user_id: int,
        mod_id: int,
        action: str,
        reason: str,
        duration: Optional[int] = None,
    ) -> int:
        case_id = await self.anext_case_id(guild_id)
        doc = {
            "case_id": case_id,
            "guild_id": guild_id,
            "user_id": user_id,
            "mod_id": mod_id,
            "action": action,
            "reason": reason,
            "duration": duration,
            "created_at": datetime.datetime.utcnow(),
            "evidence": [],
            "message_archive": [],
            "reason_history": [],
        }
        try:
            await self.cases.insert_one(doc)
        except PyMongoError as e:
            log.error(f"DB acreate_case Fehler: {e}")
        return case_id

    async def aget_case(self, guild_id: int, case_id: int) -> Optional[dict]:
        try:
            return await self.cases.find_one({"guild_id": guild_id, "case_id": case_id})
        except PyMongoError as e:
            log.error(f"DB aget_case Fehler: {e}")
            return None

    async def aget_recent_cases(self, guild_id: int, limit: int = 20) -> List[dict]:
        try:
            cursor = (
                self.cases.find({"guild_id": guild_id})
                .sort("case_id", DESCENDING)
                .limit(limit)
            )
            return await cursor.to_list(length=limit)
        except PyMongoError as e:
            log.error(f"DB aget_recent_cases Fehler: {e}")
            return []

    async def aupdate_case_reason(
        self, guild_id: int, case_id: int, new_reason: str, mod_id: int
    ) -> bool:
        try:
            existing = await self.aget_case(guild_id, case_id)
            if not existing:
                return False
            history_entry = {
                "old_reason": existing.get("reason", ""),
                "changed_by": mod_id,
                "changed_at": datetime.datetime.utcnow(),
            }
            await self.cases.update_one(
                {"guild_id": guild_id, "case_id": case_id},
                {
                    "$set": {"reason": new_reason},
                    "$push": {"reason_history": history_entry},
                },
            )
            return True
        except PyMongoError as e:
            log.error(f"DB aupdate_case_reason Fehler: {e}")
            return False

    async def aadd_case_evidence(
        self, guild_id: int, case_id: int, url: str, added_by: int, note: str = ""
    ) -> bool:
        try:
            res = await self.cases.update_one(
                {"guild_id": guild_id, "case_id": case_id},
                {
                    "$push": {
                        "evidence": {
                            "url": url,
                            "note": note,
                            "added_by": added_by,
                            "added_at": datetime.datetime.utcnow(),
                        }
                    }
                },
            )
            return res.modified_count > 0
        except PyMongoError as e:
            log.error(f"DB aadd_case_evidence Fehler: {e}")
            return False

    async def aattach_messages_to_case(
        self, guild_id: int, case_id: int, messages: List[dict]
    ) -> None:
        try:
            await self.cases.update_one(
                {"guild_id": guild_id, "case_id": case_id},
                {"$set": {"message_archive": messages}},
            )
        except PyMongoError as e:
            log.error(f"DB aattach_messages_to_case Fehler: {e}")

    # ── Message-Archiv ─────────────────────────────────────
    async def arecord_message(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        user_id: int,
        content: str,
        attachments: List[str],
    ) -> None:
        try:
            await self.message_archive.insert_one(
                {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "user_id": user_id,
                    "content": content[:4000],
                    "attachments": attachments[:10],
                    "timestamp": datetime.datetime.utcnow(),
                    "deleted": False,
                    "edits": [],
                }
            )
        except PyMongoError as e:
            log.error(f"DB arecord_message Fehler: {e}")

    async def amark_message_deleted(self, guild_id: int, message_id: int) -> None:
        try:
            await self.message_archive.update_one(
                {"guild_id": guild_id, "message_id": message_id},
                {"$set": {"deleted": True, "deleted_at": datetime.datetime.utcnow()}},
            )
        except PyMongoError as e:
            log.error(f"DB amark_message_deleted Fehler: {e}")

    async def aappend_message_edit(
        self, guild_id: int, message_id: int, old_content: str
    ) -> None:
        try:
            await self.message_archive.update_one(
                {"guild_id": guild_id, "message_id": message_id},
                {
                    "$push": {
                        "edits": {
                            "old_content": old_content[:4000],
                            "edited_at": datetime.datetime.utcnow(),
                        }
                    }
                },
            )
        except PyMongoError as e:
            log.error(f"DB aappend_message_edit Fehler: {e}")

    async def aget_user_messages(
        self, guild_id: int, user_id: int, hours: int = 48, limit: int = 500
    ) -> List[dict]:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        try:
            cursor = (
                self.message_archive.find(
                    {
                        "guild_id": guild_id,
                        "user_id": user_id,
                        "timestamp": {"$gte": cutoff},
                    }
                )
                .sort("timestamp", DESCENDING)
                .limit(limit)
            )
            return await cursor.to_list(length=limit)
        except PyMongoError as e:
            log.error(f"DB aget_user_messages Fehler: {e}")
            return []

    # ── Guild-Events ────────────────────────────────────────
    async def arecord_guild_event(
        self, guild_id: int, guild_name: str, member_count: int, event: str
    ) -> None:
        try:
            await self.guild_events.insert_one(
                {
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "member_count": member_count,
                    "event": event,
                    "timestamp": datetime.datetime.utcnow(),
                }
            )
        except PyMongoError as e:
            log.error(f"DB arecord_guild_event Fehler: {e}")

    async def aget_recent_guild_events(self, limit: int = 30) -> List[dict]:
        try:
            cursor = self.guild_events.find().sort("timestamp", DESCENDING).limit(limit)
            return await cursor.to_list(length=limit)
        except PyMongoError as e:
            log.error(f"DB aget_recent_guild_events Fehler: {e}")
            return []
