import re

with open("bot/bot.py", "r", encoding="utf-8") as f:
    text = f.read()

# ADD TEMP VOICE VIEWS AND COMMAND
tv_views = """
# ── TEMP VOICE VIEWS ──
class TempVoiceRenameModal(discord.ui.Modal, title="Kanal umbenennen"):
    name_input = discord.ui.TextInput(label="Neuer Name", placeholder="Z.B. Chill Lounge", max_length=30)
    
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=self.name_input.value)
            await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"Kanal in `{self.name_input.value}` umbenannt.", color=COLOR_SUCCESS), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)

class TempVoiceLimitModal(discord.ui.Modal, title="Nutzerlimit setzen"):
    limit_input = discord.ui.TextInput(label="Limit (0 für unbegrenzt)", placeholder="0-99", max_length=2)
    
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            if limit < 0 or limit > 99: raise ValueError
            await self.channel.edit(user_limit=limit)
            await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"Nutzerlimit auf `{limit}` gesetzt.", color=COLOR_SUCCESS), ephemeral=True)
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Bitte eine gültige Zahl zwischen 0 und 99 eingeben.", color=COLOR_DANGER), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)

class TempVoiceView(discord.ui.View):
    def __init__(self, bot_ref):
        super().__init__(timeout=None)
        self.bot = bot_ref

    async def _get_channel(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Du befindest dich in keinem Sprachkanal.", color=COLOR_DANGER), ephemeral=True)
            return None, None
        vc = interaction.user.voice.channel
        data = await self.bot.db.aget_temp_voice(vc.id)
        if not data:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Dies ist kein temporärer Kanal von ModForge.", color=COLOR_DANGER), ephemeral=True)
            return None, None
        if data["owner_id"] != interaction.user.id and interaction.custom_id != "tv_claim":
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Du bist nicht der Besitzer dieses Kanals.", color=COLOR_DANGER), ephemeral=True)
            return None, None
        return vc, data

    @discord.ui.button(label="Sperren", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="tv_lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False
        try:
            await vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description="Kanal gesperrt. Niemand Neues kann beitreten.", color=COLOR_SUCCESS), ephemeral=True)
        except Exception:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Mir fehlen die Rechte (Manage Channels).", color=COLOR_DANGER), ephemeral=True)

    @discord.ui.button(label="Entsperren", style=discord.ButtonStyle.secondary, emoji="🔓", custom_id="tv_unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(interaction.guild.default_role)
        overwrite.connect = None
        try:
            await vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description="Kanal entsperrt. Jeder kann wieder beitreten.", color=COLOR_SUCCESS), ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Verstecken", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="tv_hide")
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(interaction.guild.default_role)
        overwrite.view_channel = False
        try:
            await vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description="Kanal versteckt. Er ist nun unsichtbar für andere.", color=COLOR_SUCCESS), ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Sichtbar", style=discord.ButtonStyle.secondary, emoji="👁️‍🗨️", custom_id="tv_unhide")
    async def unhide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(interaction.guild.default_role)
        overwrite.view_channel = None
        try:
            await vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description="Kanal wieder sichtbar.", color=COLOR_SUCCESS), ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.primary, emoji="👥", custom_id="tv_limit")
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        await interaction.response.send_modal(TempVoiceLimitModal(vc))

    @discord.ui.button(label="Umbenennen", style=discord.ButtonStyle.primary, emoji="✏️", custom_id="tv_rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        await interaction.response.send_modal(TempVoiceRenameModal(vc))

    @discord.ui.button(label="Beanspruchen", style=discord.ButtonStyle.success, emoji="👑", custom_id="tv_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, data = await self._get_channel(interaction)
        if not vc: return
        if data["owner_id"] == interaction.user.id:
            return await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Du bist bereits der Besitzer.", color=COLOR_DANGER), ephemeral=True)
        owner = interaction.guild.get_member(data["owner_id"])
        if owner and owner in vc.members:
            return await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Der bisherige Besitzer ist noch im Kanal.", color=COLOR_DANGER), ephemeral=True)
        await self.bot.db.aupdate_temp_voice_owner(vc.id, interaction.user.id)
        await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description="Du bist nun der Besitzer dieses Kanals.", color=COLOR_SUCCESS), ephemeral=True)

@bot.tree.command(name="setup_tempvoice", description="Richtet das Join-to-Create System ein")
@app_commands.default_permissions(administrator=True)
async def setup_tempvoice(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    try:
        cat = await guild.create_category("🔊 Temp Voice")
        hub = await guild.create_voice_channel("➕ Join to Create", category=cat)
        interface = await guild.create_text_channel("⚙️ voice-interface", category=cat)
        
        embed = discord.Embed(
            title="🎤 Temp-Voice Interface",
            description="Erstelle deinen eigenen Sprachkanal, indem du dem **➕ Join to Create** Kanal beitrittst!\n\nNutze die Buttons unten, um deinen Kanal zu verwalten:\n\n🔒 `Sperren`: Niemand Neues kann beitreten\n🔓 `Entsperren`: Jeder kann wieder beitreten\n👁️ `Verstecken`: Kanal wird für andere unsichtbar\n👁️‍🗨️ `Sichtbar`: Kanal wird wieder sichtbar\n✏️ `Umbenennen`: Name deines Kanals ändern\n👥 `Limit`: Nutzerlimit (Größe) setzen\n👑 `Beanspruchen`: Besitzer werden (falls Owner offline)",
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        await interface.send(embed=embed, view=TempVoiceView(bot))
        
        cfg = await bot.db.aget_config(guild.id)
        cfg["temp_voice"] = {
            "enabled": True,
            "category_id": cat.id,
            "hub_channel_id": hub.id,
            "interface_channel_id": interface.id,
            "name_template": "🔊 {user}'s Kanal"
        }
        await bot.db.aset_config(guild.id, cfg)
        
        await interaction.followup.send(embed=discord.Embed(title="✅ Erfolg", description=f"Join-to-Create eingerichtet!\nInterface: {interface.mention}\nHub: {hub.mention}", color=COLOR_SUCCESS))
    except discord.Forbidden:
        await interaction.followup.send(embed=discord.Embed(title="❌ Fehler", description="Mir fehlen die Rechte (Kanäle verwalten).", color=COLOR_DANGER))
    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(title="❌ Fehler", description=f"Ein Fehler ist aufgetreten: {e}", color=COLOR_DANGER))

"""
if "class TempVoiceRenameModal" not in text:
    text = text.replace("# ── EVENT HANDLER ──────────────────────────────────────────────", tv_views + "\n# ── EVENT HANDLER ──────────────────────────────────────────────")

with open("bot/bot.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Bot UI and views added.")
