
with open('bot/bot.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. _send_webhook Port Exhaustion fix
old_wh = """                    import aiohttp

                    wh_name, wh_avatar = self.WEBHOOK_MODULES.get(
                        module, self.WEBHOOK_MODULES["default"]
                    )
                    if self.user and self.user.display_avatar:
                        wh_avatar = self.user.display_avatar.url
                    async with aiohttp.ClientSession() as session:
                        wh = discord.Webhook.from_url(_wh_url, session=session)
                        await wh.send(
                            embed=embed, username=wh_name, avatar_url=wh_avatar
                        )
                    return True"""

new_wh = """                    wh_name, wh_avatar = self.WEBHOOK_MODULES.get(
                        module, self.WEBHOOK_MODULES["default"]
                    )
                    if self.user and self.user.display_avatar:
                        wh_avatar = self.user.display_avatar.url
                    wh = discord.Webhook.from_url(_wh_url, client=self)
                    await wh.send(
                        embed=embed, username=wh_name, avatar_url=wh_avatar
                    )
                    return True"""
code = code.replace(old_wh, new_wh)

# 2. _send_channel Forbidden cleanup fix
old_ch = """            except discord.Forbidden:
                log.error(f"Keine Sende-Rechte in #{channel.name} ({channel.id})")
                self._cleanup_channel(cfg, guild.id, log_ch_id)
                return"""
new_ch = """            except discord.Forbidden:
                log.error(f"Keine Sende-Rechte in #{channel.name} ({channel.id}) - Breche ab, behalte aber Config!")
                return"""
code = code.replace(old_ch, new_ch)

# 3. verify modal fix (check if verified)
old_ver = """        cfg = self.bot.db.get_config(interaction.guild.id)["verify_system"]
        add_roles = cfg.get("add_roles", [])
        remove_roles = cfg.get("remove_roles", [])
        if cfg["mode"] == "one_click":"""
new_ver = """        cfg = self.bot.db.get_config(interaction.guild.id)["verify_system"]
        add_roles = cfg.get("add_roles", [])
        remove_roles = cfg.get("remove_roles", [])
        
        # Check if already verified
        already_verified = False
        if add_roles:
            already_verified = any(interaction.user.get_role(r_id) for r_id in add_roles)
        elif remove_roles:
            already_verified = not any(interaction.user.get_role(r_id) for r_id in remove_roles)

        if already_verified:
            embed = discord.Embed(
                title=f"{E.OK} Bereits verifiziert!",
                description="Du bist bereits auf diesem Server verifiziert und hast alle nötigen Rollen.",
                color=COLOR_SUCCESS
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if cfg["mode"] == "one_click":"""
code = code.replace(old_ver, new_ver)

# 4. _resolve_log_channel fix
old_res = """        log_channels = cfg.get("log_channels", {}) or {}
        # 1. Modul-spezifisch
        ch_id = log_channels.get(module)
        if ch_id:
            return int(ch_id)
        # 2. Default
        ch_id = log_channels.get("default")
        if ch_id:
            return int(ch_id)
        # 3. Global
        ch_id = cfg.get("log_channel")
        if ch_id:
            return int(ch_id)
        return None"""
new_res = """        log_channels = cfg.get("log_channels", {}) or {}
        # 1. Modul-spezifisch
        if module in log_channels:
            ch_id = log_channels[module]
            if str(ch_id) == "0":
                return None
            if ch_id:
                return int(ch_id)
        # 2. Default
        if "default" in log_channels:
            ch_id = log_channels["default"]
            if str(ch_id) == "0":
                return None
            if ch_id:
                return int(ch_id)
        # 3. Global
        ch_id = cfg.get("log_channel")
        if ch_id:
            return int(ch_id)
        return None"""
code = code.replace(old_res, new_res)

# 5. Remove _config_cache from init
code = code.replace("self._config_cache = {}  # Persistenter Config-Cache für alle Guilds\n", "")

# 6. _cache_refresh_loop update
old_loop = """    @tasks.loop(hours=1)
    async def _cache_refresh_loop(self) -> None:
        \"\"\"Refresh Config-Cache stündlich – hält Logs persistent über Neustarts.\"\"\"
        refreshed = 0
        failed = 0
        for guild in self.guilds:
            try:
                cfg = self.db.get_config(guild.id)
                self._config_cache[guild.id] = cfg
                refreshed += 1
            except Exception as e:
                log.error(f"Cache-Refresh Fehler für Guild {guild.id}: {e}")
                failed += 1
        if refreshed > 0:
            log.info(
                f"Config-Cache refresh: {refreshed} aktualisiert, {failed} fehlgeschlagen"
            )"""
new_loop = """    @tasks.loop(hours=1)
    async def _cache_refresh_loop(self) -> None:
        \"\"\"Keeps the DB cache warm.\"\"\"
        for guild in self.guilds:
            try:
                await self.db.aget_config(guild.id)
            except Exception:
                pass"""
code = code.replace(old_loop, new_loop)

# 7. log_action config cache loading fix
old_log = """        # ── Config laden (MIT PERSISTENTEM CACHE) ──
        cfg = self._config_cache.get(guild.id)
        if cfg is None:
            try:
                cfg = self.db.get_config(guild.id)
                self._config_cache[guild.id] = cfg
                log.debug(f"Config-Cache miss für Guild {guild.id}, frisch geladen.")
            except Exception as e:
                log.error(f"Config-Ladefehler für Guild {guild.id}: {e}")
                return"""
new_log = """        # ── Config laden ──
        try:
            cfg = await self.db.aget_config(guild.id)
        except Exception as e:
            log.error(f"Config-Ladefehler für Guild {guild.id}: {e}")
            return"""
code = code.replace(old_log, new_log)

# 8. Webhook-Cache-Speicherung
old_wh_s = """                    try:
                        await self.db.aset_config(guild_id, cfg)
                        self._config_cache[guild_id] = cfg
                    except Exception as e:"""
new_wh_s = """                    try:
                        await self.db.aset_config(guild_id, cfg)
                    except Exception as e:"""
code = code.replace(old_wh_s, new_wh_s)

# 9. _cleanup_channel cache remove
old_cu = """            try:
                asyncio.create_task(self.db.aset_config(guild_id, cfg))
                self._config_cache[guild_id] = cfg
            except Exception:"""
new_cu = """            try:
                asyncio.create_task(self.db.aset_config(guild_id, cfg))
            except Exception:"""
code = code.replace(old_cu, new_cu)

# 10. _warmup_caches
old_wu = """    async def _warmup_caches(self) -> None:
        \"\"\"Lädt alle Guild-Configs in persistenten Cache (überlebt Neustarts).\"\"\"
        loaded = 0
        failed = 0
        for guild in self.guilds:
            try:
                cfg = self.db.get_config(guild.id)
                self._config_cache[guild.id] = cfg
                loaded += 1
                try:
                    await self.db.fetch_whitelist(guild.id)
                except Exception:
                    pass
            except Exception as e:
                log.error(f"Cache-Warmup Fehler für Guild {guild.id}: {e}")
                failed += 1"""
new_wu = """    async def _warmup_caches(self) -> None:
        \"\"\"Lädt alle Guild-Configs asynchron in Memory.\"\"\"
        loaded = 0
        failed = 0
        for guild in self.guilds:
            try:
                await self.db.aget_config(guild.id)
                loaded += 1
                try:
                    await self.db.aget_whitelist(guild.id)
                except Exception:
                    pass
            except Exception as e:
                log.error(f"Cache-Warmup Fehler für Guild {guild.id}: {e}")
                failed += 1"""
code = code.replace(old_wu, new_wu)

# Write back
with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Applied functional fixes.")
