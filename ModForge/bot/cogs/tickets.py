# -*- coding: utf-8 -*-
"""
ModForge Tickets Cog – Erweitert mit Features 111-160
Multi-Category, Priority, Assignment, SLA, Transcripts, Templates, etc.
"""
import asyncio
import datetime
import io
import time
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, COLOR_INFO, E, log
from bot.utils import create_embed
from bot.bot import TicketView


class TicketCategorySelect(discord.ui.Select):
    """Dropdown für Ticket-Kategorien (Feature 111, 118)."""
    def __init__(self, categories: list, bot_ref):
        self._bot = bot_ref
        options = []
        for cat in categories[:25]:
            options.append(discord.SelectOption(
                label=cat.get("name", "Support"), value=cat.get("id", "general"),
                emoji=cat.get("emoji", "🎫"), description=cat.get("description", "")[:100]))
        if not options:
            options = [discord.SelectOption(label="Support", value="general", emoji="🎫")]
        super().__init__(placeholder="Kategorie wählen...", options=options,
                         custom_id="modforge:ticket_category")

    async def callback(self, interaction: discord.Interaction):
        category_id = self.values[0]
        cfg = self._bot.db.get_config(interaction.guild.id)
        tc = cfg.get("ticket_system", {})
        te = cfg.get("ticket_extended", {})

        # Find Discord category
        discord_cat = interaction.guild.get_channel(tc.get("category_id")) if tc.get("category_id") else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        import re
        safe_name = re.sub(r'[^a-z0-9-]', '', interaction.user.name.lower())[:15] or str(interaction.user.id)
        try:
            channel = await interaction.guild.create_text_channel(
                f"ticket-{category_id}-{safe_name}", category=discord_cat, overwrites=overwrites,
                reason=f"Ticket ({category_id}) von {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)

        # Priority selection
        priority = "medium"
        color_map = te.get("color_coding", {"low": "#22c55e", "medium": "#f59e0b", "high": "#ef4444", "urgent": "#dc2626"})
        try:
            color = int(color_map.get(priority, "#f59e0b").lstrip("#"), 16)
        except ValueError:
            color = COLOR_INFO

        embed = discord.Embed(
            title=f"{E.TICKET} Ticket – {category_id.title()}",
            description=f"Willkommen {interaction.user.mention}!\n\n"
                        f"**Kategorie:** {category_id}\n**Priorität:** {priority}\n"
                        f"Beschreibe dein Anliegen so detailliert wie möglich.",
            color=color)
        embed.set_footer(text=f"Ticket erstellt am {datetime.datetime.utcnow().strftime('%d.%m.%Y %H:%M')}")

        # Save ticket to DB
        await self._bot.db.data.insert_one({
            "type": "ticket", "guild_id": interaction.guild.id,
            "channel_id": channel.id, "user_id": interaction.user.id,
            "category": category_id, "priority": priority,
            "status": "open", "assigned_to": None,
            "created_at": datetime.datetime.utcnow(),
            "tags": [], "messages": 0,
            "first_response_at": None,
        })

        close_view = TicketControlView(self._bot)
        await channel.send(embed=embed, view=close_view)
        await interaction.response.send_message(
            f"{E.TICKET_OK} Ticket erstellt: {channel.mention}", ephemeral=True)
        await self._bot.log_action(interaction.guild, f"{E.TICKET} Ticket erstellt",
            f"{interaction.user.mention} → {channel.mention} (Kategorie: {category_id})",
            COLOR_INFO, user=interaction.user, module="tickets")


class TicketCategoryView(discord.ui.View):
    def __init__(self, categories: list, bot_ref):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect(categories, bot_ref))


class TicketControlView(discord.ui.View):
    """Ticket-Steuerung: Close, Claim, Priority (Features 112, 113, 119)."""
    def __init__(self, bot_ref):
        super().__init__(timeout=None)
        self.bot = bot_ref

    @discord.ui.button(label="Schließen", style=discord.ButtonStyle.red, emoji=E.LOCK, custom_id="modforge:ticket_close_ext")
    async def close_ticket(self, interaction: discord.Interaction, button):
        # Generate transcript (Feature 121, 123)
        transcript_lines = []
        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            ts = msg.created_at.strftime("%d.%m.%Y %H:%M")
            transcript_lines.append(f"[{ts}] {msg.author}: {msg.content or '[Embed/Attachment]'}")
        transcript = "\n".join(transcript_lines)

        # Save transcript to DB
        await self.bot.db.data.update_one(
            {"type": "ticket", "guild_id": interaction.guild.id, "channel_id": interaction.channel.id},
            {"$set": {"status": "closed", "closed_at": datetime.datetime.utcnow(),
                      "closed_by": interaction.user.id, "transcript": transcript[:50000],
                      "messages": len(transcript_lines)}})

        # Satisfaction Survey (Feature 126)
        cfg = self.bot.db.get_config(interaction.guild.id)
        te = cfg.get("ticket_extended", {})
        if te.get("satisfaction_survey"):
            try:
                ticket_doc = await self.bot.db.data.find_one(
                    {"type": "ticket", "channel_id": interaction.channel.id})
                if ticket_doc:
                    user = interaction.guild.get_member(ticket_doc.get("user_id"))
                    if user:
                        embed = create_embed("📊 Wie war dein Support-Erlebnis?",
                            "Bitte bewerte deinen Support:\n1️⃣ Schlecht\n2️⃣ Okay\n3️⃣ Gut\n4️⃣ Sehr gut\n5️⃣ Ausgezeichnet",
                            COLOR_PRIMARY)
                        try:
                            dm = await user.send(embed=embed)
                            for emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]:
                                await dm.add_reaction(emoji)
                        except Exception:
                            pass
            except Exception:
                pass

        await interaction.response.send_message(embed=create_embed(
            f"{E.LOCK} Ticket wird geschlossen",
            f"Transcript: {len(transcript_lines)} Nachrichten gespeichert.\nKanal wird in 5s gelöscht.",
            COLOR_WARNING))
        await self.bot.log_action(interaction.guild, f"{E.LOCK} Ticket geschlossen",
            f"{interaction.channel.mention} von {interaction.user.mention}\n{len(transcript_lines)} Nachrichten archiviert.",
            COLOR_WARNING, user=interaction.user, module="tickets")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket geschlossen")
        except Exception:
            pass

    @discord.ui.button(label="Übernehmen", style=discord.ButtonStyle.green, emoji="✋", custom_id="modforge:ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button):
        """Feature 113: Ticket-Assignment."""
        await self.bot.db.data.update_one(
            {"type": "ticket", "guild_id": interaction.guild.id, "channel_id": interaction.channel.id},
            {"$set": {"assigned_to": interaction.user.id, "first_response_at": datetime.datetime.utcnow()}})
        await interaction.response.send_message(embed=create_embed(
            f"✋ Ticket übernommen", f"{interaction.user.mention} bearbeitet dieses Ticket.", COLOR_SUCCESS))

    @discord.ui.button(label="Priorität", style=discord.ButtonStyle.secondary, emoji="🔺", custom_id="modforge:ticket_priority")
    async def set_priority(self, interaction: discord.Interaction, button):
        """Feature 112: Ticket-Priority."""
        await interaction.response.send_message(
            "Wähle eine Priorität:", view=PrioritySelectView(self.bot), ephemeral=True)


class PrioritySelectView(discord.ui.View):
    def __init__(self, bot_ref):
        super().__init__(timeout=30)
        self.bot = bot_ref

    @discord.ui.select(placeholder="Priorität wählen...", options=[
        discord.SelectOption(label="🟢 Niedrig", value="low"),
        discord.SelectOption(label="🟡 Mittel", value="medium"),
        discord.SelectOption(label="🔴 Hoch", value="high"),
        discord.SelectOption(label="🚨 Dringend", value="urgent"),
    ])
    async def select(self, interaction: discord.Interaction, select):
        priority = select.values[0]
        await self.bot.db.data.update_one(
            {"type": "ticket", "guild_id": interaction.guild.id, "channel_id": interaction.channel.id},
            {"$set": {"priority": priority}})
        emoji_map = {"low": "🟢", "medium": "🟡", "high": "🔴", "urgent": "🚨"}
        await interaction.response.send_message(embed=create_embed(
            f"{emoji_map.get(priority, '🎫')} Priorität: {priority.title()}", "", COLOR_SUCCESS))


class TicketsCog(commands.Cog):
    """Erweitertes Ticket-System."""

    def __init__(self, bot):
        self.bot = bot
        self.ticket_auto_close.start()

    def cog_unload(self):
        self.ticket_auto_close.cancel()

    @app_commands.command(name="setup_tickets", description="Richtet das Ticket-System ein")
    @app_commands.describe(channel="Kanal für Ticket-Button", category="Discord-Kategorie für Tickets")
    @app_commands.default_permissions(administrator=True)
    async def setup_tickets(self, interaction: discord.Interaction,
                            channel: discord.TextChannel,
                            category: discord.CategoryChannel = None):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["ticket_system"]["enabled"] = True
        cfg["ticket_system"]["category_id"] = category.id if category else None
        await self.bot.db.set_config(interaction.guild.id, cfg)

        te = cfg.get("ticket_extended", {})
        categories = te.get("categories", [])

        if categories:
            # Multi-Category mode (Feature 111)
            embed = create_embed(f"{E.TICKET} Support Tickets",
                "Wähle eine Kategorie aus dem Dropdown um ein Ticket zu öffnen.", COLOR_PRIMARY)
            view = TicketCategoryView(categories, self.bot)
        else:
            # Simple mode
            embed = create_embed(f"{E.TICKET} Support Tickets",
                "Klicke auf den Button um ein Ticket zu öffnen.", COLOR_PRIMARY)
            view = TicketView(self.bot)

        msg = await channel.send(embed=embed, view=view)
        cfg["ticket_system"]["ticket_message_id"] = msg.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Ticket-System eingerichtet",
            f"Button in {channel.mention}", COLOR_SUCCESS))

    @app_commands.command(name="ticket_category", description="Ticket-Kategorie hinzufügen")
    @app_commands.describe(name="Name", emoji="Emoji", description="Beschreibung")
    @app_commands.default_permissions(administrator=True)
    async def ticket_category(self, interaction: discord.Interaction, name: str,
                               emoji: str = "🎫", description: str = ""):
        cfg = self.bot.db.get_config(interaction.guild.id)
        te = cfg.get("ticket_extended", {})
        cats = te.get("categories", [])
        cat_id = name.lower().replace(" ", "-")[:20]
        cats.append({"id": cat_id, "name": name, "emoji": emoji, "description": description})
        te["categories"] = cats
        cfg["ticket_extended"] = te
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Kategorie hinzugefügt", f"{emoji} **{name}** (`{cat_id}`)", COLOR_SUCCESS))

    @app_commands.command(name="ticket_stats", description="Ticket-Statistiken")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_stats(self, interaction: discord.Interaction):
        """Feature 124, 125: Ticket-Stats-Dashboard + Response-Time-Tracking."""
        tickets = await self.bot.db.data.find(
            {"type": "ticket", "guild_id": interaction.guild.id}
        ).to_list(1000)
        total = len(tickets)
        open_t = sum(1 for t in tickets if t.get("status") == "open")
        closed_t = sum(1 for t in tickets if t.get("status") == "closed")

        # Response time tracking
        response_times = []
        for t in tickets:
            if t.get("first_response_at") and t.get("created_at"):
                delta = (t["first_response_at"] - t["created_at"]).total_seconds()
                response_times.append(delta)
        avg_response = sum(response_times) / len(response_times) if response_times else 0
        avg_minutes = int(avg_response / 60)

        # Messages per ticket
        total_msgs = sum(t.get("messages", 0) for t in tickets)

        fields = [
            ("Gesamt", str(total), True),
            ("Offen", str(open_t), True),
            ("Geschlossen", str(closed_t), True),
            ("Ø Antwortzeit", f"{avg_minutes} Min.", True),
            ("Ø Nachrichten", f"{total_msgs // max(total, 1)}", True),
        ]
        await interaction.response.send_message(embed=create_embed(
            f"📊 Ticket-Statistiken", "", COLOR_PRIMARY, fields))

    @app_commands.command(name="ticket_canned", description="Vordefinierte Antwort hinzufügen")
    @app_commands.describe(name="Name/Trigger", response="Antwort-Text")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_canned(self, interaction: discord.Interaction, name: str, response: str):
        """Feature 156, 157: Canned/Macro Responses."""
        cfg = self.bot.db.get_config(interaction.guild.id)
        te = cfg.get("ticket_extended", {})
        canned = te.get("canned_responses", [])
        canned.append({"name": name.lower(), "response": response})
        te["canned_responses"] = canned
        cfg["ticket_extended"] = te
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Antwort gespeichert", f"**{name}** – Nutze `/canned {name}` in Tickets.", COLOR_SUCCESS))

    @app_commands.command(name="canned", description="Vordefinierte Antwort senden")
    @app_commands.describe(name="Name der Antwort")
    @app_commands.default_permissions(manage_messages=True)
    async def use_canned(self, interaction: discord.Interaction, name: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        te = cfg.get("ticket_extended", {})
        canned = te.get("canned_responses", [])
        found = next((c for c in canned if c["name"] == name.lower()), None)
        if not found:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", f"Antwort `{name}` nicht gefunden.", COLOR_DANGER), ephemeral=True)
        await interaction.response.send_message(found["response"])

    @app_commands.command(name="ticket_transcript", description="Exportiert Ticket-Transcript")
    @app_commands.describe(channel="Ticket-Kanal")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_transcript(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Feature 121, 123: Ticket-Transcript-Export."""
        target = channel or interaction.channel
        await interaction.response.defer(ephemeral=True)
        lines = []
        async for msg in target.history(limit=500, oldest_first=True):
            ts = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
            content = msg.content or "[Embed/Attachment]"
            lines.append(f"[{ts}] {msg.author.display_name}: {content}")
        transcript = "\n".join(lines)
        # HTML format (Feature 123)
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Transcript – {target.name}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:auto;padding:20px;background:#1a1a2e;color:#e0e0e0}}
.msg{{padding:8px;margin:4px 0;background:#16213e;border-radius:6px}}.ts{{color:#888;font-size:0.8em}}
.author{{color:#7c3aed;font-weight:bold}}</style></head><body>
<h1>📋 Transcript – #{target.name}</h1><p>{len(lines)} Nachrichten</p><hr>"""
        for msg_line in lines:
            parts = msg_line.split("] ", 1)
            if len(parts) == 2:
                ts = parts[0].lstrip("[")
                rest = parts[1].split(": ", 1)
                author = rest[0] if len(rest) > 1 else "?"
                content = rest[1] if len(rest) > 1 else rest[0]
                html += f'<div class="msg"><span class="ts">{ts}</span> <span class="author">{author}</span>: {content}</div>\n'
        html += "</body></html>"
        buf = io.BytesIO(html.encode("utf-8"))
        file = discord.File(buf, filename=f"transcript-{target.name}.html")
        await interaction.followup.send(f"📋 Transcript: {len(lines)} Nachrichten", file=file)

    @tasks.loop(hours=1)
    async def ticket_auto_close(self):
        """Feature 127: Ticket-Auto-Close-Timer."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                cfg = self.bot.db.get_config(guild.id)
                te = cfg.get("ticket_extended", {})
                auto_close_hours = te.get("auto_close_hours", 48)
                if auto_close_hours <= 0:
                    continue
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=auto_close_hours)
                old_tickets = await self.bot.db.data.find({
                    "type": "ticket", "guild_id": guild.id, "status": "open",
                    "created_at": {"$lt": cutoff}
                }).to_list(50)
                for ticket in old_tickets:
                    ch = guild.get_channel(ticket.get("channel_id"))
                    if ch:
                        # Check last message
                        try:
                            last_msg = None
                            async for msg in ch.history(limit=1):
                                last_msg = msg
                            if last_msg and (datetime.datetime.utcnow() - last_msg.created_at.replace(tzinfo=None)).total_seconds() > auto_close_hours * 3600:
                                await ch.send(embed=create_embed(
                                    f"{E.LOCK} Ticket auto-geschlossen",
                                    f"Keine Aktivität seit {auto_close_hours}h.", COLOR_WARNING))
                                await self.bot.db.data.update_one(
                                    {"_id": ticket["_id"]},
                                    {"$set": {"status": "closed", "closed_at": datetime.datetime.utcnow()}})
                                await asyncio.sleep(5)
                                await ch.delete(reason="Auto-Close")
                        except Exception:
                            pass
            except Exception as e:
                log.debug(f"Ticket auto-close error {guild.id}: {e}")


async def setup(bot):
    await bot.add_cog(TicketsCog(bot))
