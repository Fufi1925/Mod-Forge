# -*- coding: utf-8 -*-
"""ModForge Backup Cog – Server-Backup & Restore System."""
import asyncio
import datetime
import uuid

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_INFO, E, log
from bot.utils import create_embed
from bot.embed_config import get_embed


class BackupCog(commands.Cog):
    """Komplettes Server-Backup & Restore mit Auto-Backup."""

    def __init__(self, bot):
        self.bot = bot
        self.auto_backup_loop.start()

    def cog_unload(self):
        self.auto_backup_loop.cancel()

    async def _collect_backup_data(self, guild: discord.Guild) -> dict:
        """Sammelt alle Server-Daten für ein Backup."""
        roles = []
        for r in sorted(guild.roles, key=lambda x: x.position, reverse=True):
            if r.is_default() or r.managed:
                continue
            roles.append({
                "name": r.name, "color": r.color.value, "permissions": r.permissions.value,
                "hoist": r.hoist, "mentionable": r.mentionable, "position": r.position,
                "role_id": r.id,
            })

        categories = []
        for cat in guild.categories:
            overwrites = {}
            for target, perms in cat.overwrites.items():
                key = f"role:{target.id}" if isinstance(target, discord.Role) else f"member:{target.id}"
                overwrites[key] = {"allow": perms.pair()[0].value, "deny": perms.pair()[1].value}
            categories.append({"name": cat.name, "position": cat.position, "overwrites": overwrites, "id": cat.id})

        channels = []
        for ch in guild.channels:
            if isinstance(ch, discord.CategoryChannel):
                continue
            ch_data = {
                "name": ch.name, "type": str(ch.type), "position": ch.position,
                "category_id": ch.category_id,
            }
            if hasattr(ch, "topic"):
                ch_data["topic"] = ch.topic
            if hasattr(ch, "slowmode_delay"):
                ch_data["slowmode_delay"] = ch.slowmode_delay
            if hasattr(ch, "nsfw"):
                ch_data["nsfw"] = ch.nsfw
            if hasattr(ch, "bitrate"):
                ch_data["bitrate"] = ch.bitrate
            if hasattr(ch, "user_limit"):
                ch_data["user_limit"] = ch.user_limit
            channels.append(ch_data)

        return {
            "guild_id": guild.id, "guild_name": guild.name,
            "roles": roles, "categories": categories, "channels": channels,
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }

    async def _backup_db_save(self, backup_data: dict, created_by: int,
                               label: str = None, password_hash: str = None) -> str:
        backup_id = str(uuid.uuid4())[:8]
        doc = {
            "backup_id": backup_id,
            "guild_id": backup_data["guild_id"],
            "guild_id_str": str(backup_data["guild_id"]),
            "guild_name": backup_data.get("guild_name"),
            "data": backup_data,
            "created_by": created_by,
            "created_at": datetime.datetime.utcnow(),
            "label": label,
            "password_hash": password_hash,
        }
        col = self.bot.db.client["ModForge"]["backups"]
        await col.insert_one(doc)
        return backup_id

    async def _backup_db_get(self, guild_id: int, backup_id: str) -> dict:
        col = self.bot.db.client["ModForge"]["backups"]
        variants = [guild_id, str(guild_id)]
        return await col.find_one({
            "backup_id": backup_id,
            "$or": [
                {"guild_id": {"$in": variants}},
                {"guild_id_str": str(guild_id)},
                {"data.guild_id": {"$in": variants}},
            ],
        })

    async def _backup_db_get_any(self, backup_id: str) -> dict:
        col = self.bot.db.client["ModForge"]["backups"]
        return await col.find_one({"backup_id": backup_id})

    async def _restore_from_backup(self, guild: discord.Guild, backup: dict,
                                    interaction: discord.Interaction = None) -> dict:
        """Stellt einen Server aus einem Backup wieder her."""
        report = {"roles_created": 0, "channels_created": 0, "errors": []}
        role_map = {}

        # Rollen erstellen
        for role_data in reversed(backup.get("roles", [])):
            try:
                existing = guild.get_role(role_data.get("role_id"))
                if existing:
                    role_map[role_data["role_id"]] = existing
                    continue
                new_role = await guild.create_role(
                    name=role_data["name"],
                    color=discord.Color(role_data.get("color", 0)),
                    permissions=discord.Permissions(role_data.get("permissions", 0)),
                    hoist=role_data.get("hoist", False),
                    mentionable=role_data.get("mentionable", False),
                    reason="Backup-Wiederherstellung")
                role_map[role_data["role_id"]] = new_role
                report["roles_created"] += 1
                await asyncio.sleep(0.5)
            except (discord.Forbidden, discord.HTTPException) as e:
                report["errors"].append(f"Rolle {role_data['name']}: {e}")

        # Kategorien + Kanäle erstellen
        cat_map = {}
        for cat_data in backup.get("categories", []):
            try:
                existing = discord.utils.get(guild.categories, name=cat_data["name"])
                if existing:
                    cat_map[cat_data["id"]] = existing
                    continue
                new_cat = await guild.create_category(name=cat_data["name"], reason="Backup-Wiederherstellung")
                cat_map[cat_data["id"]] = new_cat
                await asyncio.sleep(0.3)
            except (discord.Forbidden, discord.HTTPException) as e:
                report["errors"].append(f"Kategorie {cat_data['name']}: {e}")

        for ch_data in backup.get("channels", []):
            try:
                existing = discord.utils.get(guild.channels, name=ch_data["name"])
                if existing:
                    continue
                category = cat_map.get(ch_data.get("category_id"))
                ch_type = ch_data.get("type", "text")
                if "voice" in ch_type:
                    await guild.create_voice_channel(name=ch_data["name"], category=category, reason="Backup")
                else:
                    kw = {}
                    if ch_data.get("topic"):
                        kw["topic"] = ch_data["topic"]
                    if ch_data.get("slowmode_delay"):
                        kw["slowmode_delay"] = ch_data["slowmode_delay"]
                    await guild.create_text_channel(name=ch_data["name"], category=category, reason="Backup", **kw)
                report["channels_created"] += 1
                await asyncio.sleep(0.3)
            except (discord.Forbidden, discord.HTTPException) as e:
                report["errors"].append(f"Kanal {ch_data['name']}: {e}")

        return report

    # ── SLASH COMMANDS ──
    @app_commands.command(name="backup_create", description="Erstellt ein Server-Backup")
    @app_commands.describe(label="Optionales Label")
    @app_commands.default_permissions(administrator=True)
    async def slash_backup_create(self, interaction: discord.Interaction, label: str = None):
        await interaction.response.defer()
        try:
            data = await self._collect_backup_data(interaction.guild)
            backup_id = await self._backup_db_save(data, interaction.user.id, label)
            await interaction.followup.send(embed=create_embed(
                f"{E.SAVE} Backup erstellt",
                f"**ID:** `{backup_id}`\n**Label:** {label or '—'}\n"
                f"**Rollen:** {len(data['roles'])}\n**Kanäle:** {len(data['channels'])}\n"
                f"**Kategorien:** {len(data['categories'])}",
                COLOR_SUCCESS))
            await self.bot.log_action(interaction.guild, f"{E.SAVE} Backup erstellt",
                f"ID: `{backup_id}` von {interaction.user.mention}", COLOR_SUCCESS,
                user=interaction.user, module="backup")
        except Exception as e:
            await interaction.followup.send(embed=create_embed(f"{E.FAIL}", f"Fehler: {e}", COLOR_DANGER))

    @app_commands.command(name="backup_list", description="Zeigt alle Backups")
    @app_commands.default_permissions(administrator=True)
    async def slash_backup_list(self, interaction: discord.Interaction):
        col = self.bot.db.client["ModForge"]["backups"]
        variants = [interaction.guild.id, str(interaction.guild.id)]
        docs = await col.find({"$or": [
            {"guild_id": {"$in": variants}},
            {"guild_id_str": str(interaction.guild.id)},
            {"data.guild_id": {"$in": variants}},
        ]}).sort("created_at", -1).to_list(20)
        if not docs:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FOLDER}", "Keine Backups vorhanden.", COLOR_INFO))
        lines = []
        for doc in docs:
            label = doc.get("label") or "—"
            bid = doc.get("backup_id", "?")
            created = doc.get("created_at", "?")
            if hasattr(created, "strftime"):
                created = created.strftime("%d.%m.%Y %H:%M")
            roles_count = len(doc.get("data", {}).get("roles", []))
            channels_count = len(doc.get("data", {}).get("channels", []))
            lines.append(f"`{bid}` | {label} | {roles_count}R/{channels_count}C | {created}")
        await interaction.response.send_message(embed=create_embed(
            f"{E.FOLDER} Backups ({len(docs)})", "\n".join(lines), COLOR_PRIMARY))

    @app_commands.command(name="backup_restore", description="Stellt ein Backup wieder her")
    @app_commands.describe(backup_id="Backup-ID")
    @app_commands.default_permissions(administrator=True)
    async def slash_backup_restore(self, interaction: discord.Interaction, backup_id: str):
        await interaction.response.defer()
        doc = await self._backup_db_get(interaction.guild.id, backup_id)
        if not doc:
            return await interaction.followup.send(embed=create_embed(
                f"{E.FAIL}", "Backup nicht gefunden.", COLOR_DANGER))
        report = await self._restore_from_backup(interaction.guild, doc["data"], interaction)
        errors_text = "\n".join(report["errors"][:10]) if report["errors"] else "Keine"
        await interaction.followup.send(embed=create_embed(
            f"{E.OK} Backup wiederhergestellt",
            f"**Rollen erstellt:** {report['roles_created']}\n"
            f"**Kanäle erstellt:** {report['channels_created']}\n"
            f"**Fehler:** {len(report['errors'])}\n\n{errors_text}",
            COLOR_SUCCESS))

    @app_commands.command(name="backup_delete", description="Löscht ein Backup")
    @app_commands.describe(backup_id="Backup-ID")
    @app_commands.default_permissions(administrator=True)
    async def slash_backup_delete(self, interaction: discord.Interaction, backup_id: str):
        col = self.bot.db.client["ModForge"]["backups"]
        variants = [interaction.guild.id, str(interaction.guild.id)]
        result = await col.delete_one({"backup_id": backup_id, "$or": [
            {"guild_id": {"$in": variants}},
            {"guild_id_str": str(interaction.guild.id)},
            {"data.guild_id": {"$in": variants}},
        ]})
        if result.deleted_count:
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"Backup `{backup_id}` gelöscht.", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Backup nicht gefunden.", COLOR_DANGER), ephemeral=True)

    # ── AUTO-BACKUP TASK ──
    @tasks.loop(hours=6)
    async def auto_backup_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                cfg = self.bot.db.get_config(guild.id)
                backup_cfg = cfg.get("backup_system", {})
                if not backup_cfg.get("auto_enabled"):
                    continue
                interval = backup_cfg.get("auto_interval_hours", 24)
                last = backup_cfg.get("auto_last_backup")
                if last:
                    try:
                        last_dt = datetime.datetime.fromisoformat(str(last))
                        if (datetime.datetime.utcnow() - last_dt).total_seconds() < interval * 3600:
                            continue
                    except Exception:
                        pass
                data = await self._collect_backup_data(guild)
                backup_id = await self._backup_db_save(data, self.bot.user.id, "Auto-Backup")
                cfg["backup_system"]["auto_last_backup"] = datetime.datetime.utcnow().isoformat()
                await self.bot.db.set_config(guild.id, cfg)
                # Cleanup old auto-backups
                max_backups = backup_cfg.get("auto_max_backups", 5)
                col = self.bot.db.client["ModForge"]["backups"]
                auto_docs = await col.find(
                    {"guild_id": guild.id, "label": "Auto-Backup"}
                ).sort("created_at", -1).to_list(100)
                if len(auto_docs) > max_backups:
                    for old_doc in auto_docs[max_backups:]:
                        await col.delete_one({"_id": old_doc["_id"]})
                log.info(f"Auto-Backup für {guild.name}: {backup_id}")
            except Exception as e:
                log.debug(f"Auto-Backup Fehler für {guild.id}: {e}")


# Make backup functions importable for routes.py
_backup_cog_instance = None

async def setup(bot):
    global _backup_cog_instance
    cog = BackupCog(bot)
    _backup_cog_instance = cog
    await bot.add_cog(cog)
