"""
ModForge – ZENTRALE EMBED KONFIGURATION (VOLLSTÄNDIG)
======================================================

Diese Datei enthält **JEDES** Embed, das der Bot jemals senden kann.
Egal ob Welcome, Ticket, Moderation, Security, TempVoice, AutoMod, Logging, etc.

Änderst du hier etwas → ändert sich überall im Bot.

Verwendung in jedem Cog:
    from bot.embed_config import get_embed

    embed = get_embed("ban", user=user, mod=mod, reason=reason)
    await channel.send(embed=embed)
"""

import discord
from datetime import datetime
from typing import Optional, Dict, Any, List

# =========================================================
# GLOBALE FARBPALETTE
# =========================================================
COLORS = {
    "primary": 0x5865F2,
    "success": 0x22C55E,
    "warning": 0xF59E0B,
    "danger": 0xEF4444,
    "info": 0x3B82F6,
    "purple": 0x8B5CF6,
    "pink": 0xEC4899,
    "teal": 0x14B8A6,
    "dark": 0x1F2937,
    "gold": 0xFBBF24,
}

# =========================================================
# HAUPTFUNKTION
# =========================================================

def get_embed(name: str, **kwargs) -> discord.Embed:
    """Gibt ein Embed aus der zentralen Konfiguration zurück."""
    func = EMBEDS.get(name)
    if func:
        return func(**kwargs)
    
    # Fallback
    embed = discord.Embed(
        title="❌ Embed nicht gefunden",
        description=f"Das Embed `{name}` ist nicht definiert.",
        color=COLORS["danger"]
    )
    return embed


# =========================================================
# ALLE EMBEDS (VOLLSTÄNDIG)
# =========================================================

# ─────────────────────────────────────────────────────────
# WELCOME / LEAVE / ONBOARDING
# ─────────────────────────────────────────────────────────

def embed_welcome(**kwargs):
    guild = kwargs.get("guild")
    user = kwargs.get("user")
    embed = discord.Embed(title="👋 Willkommen!", description=f"Schön, dass du da bist {user.mention}!", color=COLORS["success"])
    embed.set_thumbnail(url=getattr(user.avatar, "url", None) or user.default_avatar.url)
    embed.set_footer(text=f"{guild.name}")
    embed.timestamp = datetime.utcnow()
    return embed

def embed_leave(**kwargs):
    guild = kwargs.get("guild")
    user = kwargs.get("user")
    embed = discord.Embed(title="👋 Auf Wiedersehen", description=f"{user} hat den Server verlassen.", color=COLORS["dark"])
    embed.set_footer(text=f"{guild.name}")
    return embed

def embed_onboarding(**kwargs):
    embed = discord.Embed(title="🎉 Willkommen!", description="Bitte verifiziere dich, um vollen Zugriff zu erhalten.", color=COLORS["primary"])
    embed.set_footer(text="Onboarding")
    return embed

# ─────────────────────────────────────────────────────────
# VERIFICATION
# ─────────────────────────────────────────────────────────

def embed_verification_panel(**kwargs):
    embed = discord.Embed(title="✅ Verification", description="Klicke auf den Button, um dich zu verifizieren.", color=COLORS["primary"])
    embed.set_footer(text="Verification System")
    return embed

def embed_verification_success(**kwargs):
    user = kwargs.get("user")
    embed = discord.Embed(title="✅ Verifiziert!", description=f"{user.mention} wurde erfolgreich verifiziert.", color=COLORS["success"])
    return embed

def embed_verification_failed(**kwargs):
    embed = discord.Embed(title="❌ Verification fehlgeschlagen", description="Bitte versuche es erneut.", color=COLORS["danger"])
    return embed

# ─────────────────────────────────────────────────────────
# TICKETS (alle Varianten)
# ─────────────────────────────────────────────────────────

def embed_ticket_panel(**kwargs):
    embed = discord.Embed(title="🎫 Ticket System", description="Wähle eine Kategorie aus, um ein Ticket zu öffnen.", color=COLORS["info"])
    embed.set_footer(text="Ticket System • ModForge")
    return embed

def embed_ticket_created(**kwargs):
    ticket_id = kwargs.get("ticket_id")
    category = kwargs.get("category", "Support")
    embed = discord.Embed(title="🎫 Ticket erstellt", description=f"Dein Ticket **#{ticket_id}** wurde erstellt.", color=COLORS["success"])
    embed.add_field(name="Kategorie", value=category)
    embed.set_footer(text="Ticket System")
    return embed

def embed_ticket_closed(**kwargs):
    ticket_id = kwargs.get("ticket_id")
    closed_by = kwargs.get("closed_by")
    embed = discord.Embed(title="🔒 Ticket geschlossen", description=f"Ticket **#{ticket_id}** wurde von {closed_by} geschlossen.", color=COLORS["dark"])
    return embed

def embed_ticket_transcript(**kwargs):
    ticket_id = kwargs.get("ticket_id")
    embed = discord.Embed(title="📜 Transcript", description=f"Transcript für Ticket #{ticket_id}", color=COLORS["purple"])
    embed.set_footer(text="Ticket System")
    return embed

def embed_ticket_claimed(**kwargs):
    ticket_id = kwargs.get("ticket_id")
    staff = kwargs.get("staff")
    embed = discord.Embed(title="🙋 Ticket übernommen", description=f"Ticket #{ticket_id} wurde von {staff} übernommen.", color=COLORS["info"])
    return embed

# ─────────────────────────────────────────────────────────
# TEMPVOICE (alle Varianten)
# ─────────────────────────────────────────────────────────

def embed_tempvoice_panel(**kwargs):
    embed = discord.Embed(title="🔊 TempVoice", description="Klicke auf den Button, um einen eigenen Voice-Kanal zu erstellen.", color=COLORS["purple"])
    embed.set_footer(text="TempVoice System")
    return embed

def embed_tempvoice_created(**kwargs):
    channel = kwargs.get("channel")
    owner = kwargs.get("owner")
    embed = discord.Embed(title="🔊 TempVoice erstellt", description=f"{owner.mention} hat den Kanal {channel.mention} erstellt.", color=COLORS["success"])
    return embed

def embed_tempvoice_deleted(**kwargs):
    channel_name = kwargs.get("channel_name")
    embed = discord.Embed(title="🗑️ TempVoice gelöscht", description=f"Der Kanal **{channel_name}** wurde gelöscht.", color=COLORS["dark"])
    return embed

def embed_tempvoice_owner_action(**kwargs):
    action = kwargs.get("action", "Aktion")
    embed = discord.Embed(title=f"🔧 {action}", description="Die Aktion wurde ausgeführt.", color=COLORS["info"])
    return embed

# ─────────────────────────────────────────────────────────
# MODERATION / CASES
# ─────────────────────────────────────────────────────────

def embed_ban(**kwargs):
    user = kwargs.get("user")
    mod = kwargs.get("mod")
    reason = kwargs.get("reason", "Kein Grund")
    embed = discord.Embed(title="🔨 Ban", description=f"{user.mention} wurde gebannt.", color=COLORS["danger"])
    embed.add_field(name="Moderator", value=str(mod), inline=True)
    embed.add_field(name="Grund", value=reason, inline=False)
    embed.set_footer(text="Moderation")
    return embed

def embed_kick(**kwargs):
    user = kwargs.get("user")
    mod = kwargs.get("mod")
    reason = kwargs.get("reason", "Kein Grund")
    embed = discord.Embed(title="👢 Kick", description=f"{user.mention} wurde gekickt.", color=COLORS["warning"])
    embed.add_field(name="Moderator", value=str(mod))
    embed.add_field(name="Grund", value=reason)
    return embed

def embed_mute(**kwargs):
    user = kwargs.get("user")
    mod = kwargs.get("mod")
    duration = kwargs.get("duration", "Unbekannt")
    reason = kwargs.get("reason", "Kein Grund")
    embed = discord.Embed(title="🔇 Mute", description=f"{user.mention} wurde stummgeschaltet.", color=COLORS["purple"])
    embed.add_field(name="Dauer", value=duration)
    embed.add_field(name="Grund", value=reason)
    return embed

def embed_warn(**kwargs):
    user = kwargs.get("user")
    mod = kwargs.get("mod")
    reason = kwargs.get("reason", "Kein Grund")
    embed = discord.Embed(title="⚠️ Warn", description=f"{user.mention} wurde verwarnt.", color=COLORS["warning"])
    embed.add_field(name="Grund", value=reason)
    return embed

def embed_case(**kwargs):
    case_id = kwargs.get("case_id")
    action = kwargs.get("action", "unknown").upper()
    user = kwargs.get("user")
    reason = kwargs.get("reason", "Kein Grund")
    embed = discord.Embed(title=f"📋 Case #{case_id}", description=f"**{action}** gegen {user.mention}", color=COLORS["danger"] if action in ["BAN", "KICK"] else COLORS["warning"])
    embed.add_field(name="Grund", value=reason)
    embed.set_footer(text="Moderation System")
    return embed

def embed_case_updated(**kwargs):
    case_id = kwargs.get("case_id")
    embed = discord.Embed(title=f"✏️ Case #{case_id} aktualisiert", description="Der Grund wurde geändert.", color=COLORS["info"])
    return embed

# ─────────────────────────────────────────────────────────
# AUTOMOD
# ─────────────────────────────────────────────────────────

def embed_automod_hit(**kwargs):
    user = kwargs.get("user")
    rule = kwargs.get("rule", "Unbekannt")
    embed = discord.Embed(title="🛡️ AutoMod", description=f"{user.mention} hat gegen eine Regel verstoßen.", color=COLORS["warning"])
    embed.add_field(name="Regel", value=rule)
    embed.set_footer(text="AutoMod")
    return embed

def embed_automod_blocked(**kwargs):
    embed = discord.Embed(title="🚫 Nachricht blockiert", description="Deine Nachricht wurde von AutoMod blockiert.", color=COLORS["danger"])
    return embed

def embed_anti_spam(**kwargs):
    user = kwargs.get("user")
    embed = discord.Embed(title="🚫 Anti-Spam", description=f"{user.mention} wurde wegen Spam eingeschränkt.", color=COLORS["danger"])
    return embed

def embed_anti_raid(**kwargs):
    embed = discord.Embed(title="🚨 Anti-Raid erkannt", description="Mögliche Raid-Aktivität wurde erkannt.", color=COLORS["danger"])
    return embed

# ─────────────────────────────────────────────────────────
# SECURITY / ANTINUKE
# ─────────────────────────────────────────────────────────

def embed_security_alert(**kwargs):
    embed = discord.Embed(title="🚨 Security Alert", description="Potentiell gefährliche Aktivität erkannt!", color=COLORS["danger"])
    embed.set_footer(text="Security System")
    return embed

def embed_anti_nuke(**kwargs):
    user = kwargs.get("user")
    action = kwargs.get("action", "unbekannt")
    embed = discord.Embed(title="🛡️ Anti-Nuke", description=f"{user.mention} hat versucht, den Server zu attackieren ({action}).", color=COLORS["danger"])
    return embed

def embed_whitelist_bypass(**kwargs):
    user = kwargs.get("user")
    embed = discord.Embed(title="⚠️ Whitelist Bypass", description=f"{user.mention} hat versucht, eine geschützte Aktion auszuführen.", color=COLORS["warning"])
    return embed

# ─────────────────────────────────────────────────────────
# BACKUP
# ─────────────────────────────────────────────────────────

def embed_backup_created(**kwargs):
    embed = discord.Embed(title="💾 Backup erstellt", description="Deine Server-Einstellungen wurden erfolgreich gesichert.", color=COLORS["success"])
    embed.set_footer(text="Backup System")
    return embed

def embed_backup_restored(**kwargs):
    backup_id = kwargs.get("backup_id")
    embed = discord.Embed(title="♻️ Backup wiederhergestellt", description=f"Backup **{backup_id}** wurde erfolgreich wiederhergestellt.", color=COLORS["info"])
    return embed

# ─────────────────────────────────────────────────────────
# LOGGING (verschiedene Log-Embeds)
# ─────────────────────────────────────────────────────────

def embed_log_message_delete(**kwargs):
    user = kwargs.get("user")
    channel = kwargs.get("channel")
    content = kwargs.get("content", "")
    embed = discord.Embed(title="🗑️ Nachricht gelöscht", description=f"Von {user.mention} in {channel.mention}", color=COLORS["dark"])
    embed.add_field(name="Inhalt", value=content[:1024] or "Kein Inhalt")
    return embed

def embed_log_message_edit(**kwargs):
    user = kwargs.get("user")
    embed = discord.Embed(title="✏️ Nachricht bearbeitet", description=f"Von {user.mention}", color=COLORS["info"])
    return embed

def embed_log_role_create(**kwargs):
    role = kwargs.get("role")
    embed = discord.Embed(title="➕ Rolle erstellt", description=f"Rolle **{role.name}** wurde erstellt.", color=COLORS["success"])
    return embed

def embed_log_role_delete(**kwargs):
    role_name = kwargs.get("role_name")
    embed = discord.Embed(title="➖ Rolle gelöscht", description=f"Rolle **{role_name}** wurde gelöscht.", color=COLORS["danger"])
    return embed

def embed_log_channel_create(**kwargs):
    channel = kwargs.get("channel")
    embed = discord.Embed(title="➕ Kanal erstellt", description=f"Kanal **{channel.name}** wurde erstellt.", color=COLORS["success"])
    return embed

def embed_log_member_join(**kwargs):
    user = kwargs.get("user")
    embed = discord.Embed(title="➕ Member beigetreten", description=f"{user.mention} ist dem Server beigetreten.", color=COLORS["success"])
    return embed

def embed_log_member_leave(**kwargs):
    user = kwargs.get("user")
    embed = discord.Embed(title="➖ Member verlassen", description=f"{user} hat den Server verlassen.", color=COLORS["dark"])
    return embed

# ─────────────────────────────────────────────────────────
# BADGES
# ─────────────────────────────────────────────────────────

def embed_badge_added(**kwargs):
    user = kwargs.get("user")
    badge = kwargs.get("badge")
    embed = discord.Embed(title="🏅 Badge erhalten", description=f"{user.mention} hat das Badge **{badge}** erhalten.", color=COLORS["gold"])
    return embed

def embed_badge_removed(**kwargs):
    user = kwargs.get("user")
    badge = kwargs.get("badge")
    embed = discord.Embed(title="🏅 Badge entfernt", description=f"Das Badge **{badge}** wurde von {user.mention} entfernt.", color=COLORS["dark"])
    return embed

# ─────────────────────────────────────────────────────────
# STATS / LEADERBOARD
# ─────────────────────────────────────────────────────────

def embed_leaderboard(**kwargs):
    title = kwargs.get("title", "Leaderboard")
    embed = discord.Embed(title=f"🏆 {title}", description="Hier sind die besten Mitglieder:", color=COLORS["gold"])
    return embed

def embed_stats(**kwargs):
    embed = discord.Embed(title="📊 Server Statistiken", color=COLORS["info"])
    embed.set_footer(text="Stats System")
    return embed

# ─────────────────────────────────────────────────────────
# UTILITY / GENERAL
# ─────────────────────────────────────────────────────────

def embed_success(**kwargs):
    msg = kwargs.get("message", "Erfolgreich!")
    embed = discord.Embed(title="✅ Erfolg", description=msg, color=COLORS["success"])
    return embed

def embed_error(**kwargs):
    msg = kwargs.get("message", "Ein Fehler ist aufgetreten.")
    embed = discord.Embed(title="❌ Fehler", description=msg, color=COLORS["danger"])
    return embed

def embed_info(**kwargs):
    title = kwargs.get("title", "Information")
    desc = kwargs.get("description", "")
    embed = discord.Embed(title=title, description=desc, color=COLORS["info"])
    return embed

def embed_help(**kwargs):
    cmd = kwargs.get("command", "Befehl")
    embed = discord.Embed(title=f"❓ Hilfe: {cmd}", color=COLORS["primary"])
    return embed

def embed_pagination(**kwargs):
    embed = discord.Embed(title="Seite", color=COLORS["dark"])
    return embed

# ─────────────────────────────────────────────────────────
# VOICE / VOICE EVENTS
# ─────────────────────────────────────────────────────────

def embed_voice_join(**kwargs):
    user = kwargs.get("user")
    channel = kwargs.get("channel")
    embed = discord.Embed(title="🔊 Voice beigetreten", description=f"{user.mention} ist {channel.mention} beigetreten.", color=COLORS["teal"])
    return embed

def embed_voice_leave(**kwargs):
    user = kwargs.get("user")
    channel = kwargs.get("channel")
    embed = discord.Embed(title="🔇 Voice verlassen", description=f"{user.mention} hat {channel.mention} verlassen.", color=COLORS["dark"])
    return embed

# =========================================================
# REGISTER ALL EMBEDS
# =========================================================

EMBEDS: Dict[str, Any] = {
    # Welcome / Leave
    "welcome": embed_welcome,
    "leave": embed_leave,
    "onboarding": embed_onboarding,
    
    # Verification
    "verification_panel": embed_verification_panel,
    "verification_success": embed_verification_success,
    "verification_failed": embed_verification_failed,
    
    # Tickets
    "ticket_panel": embed_ticket_panel,
    "ticket_created": embed_ticket_created,
    "ticket_closed": embed_ticket_closed,
    "ticket_transcript": embed_ticket_transcript,
    "ticket_claimed": embed_ticket_claimed,
    
    # TempVoice
    "tempvoice_panel": embed_tempvoice_panel,
    "tempvoice_created": embed_tempvoice_created,
    "tempvoice_deleted": embed_tempvoice_deleted,
    "tempvoice_owner_action": embed_tempvoice_owner_action,
    
    # Moderation
    "ban": embed_ban,
    "kick": embed_kick,
    "mute": embed_mute,
    "warn": embed_warn,
    "case": embed_case,
    "case_updated": embed_case_updated,
    
    # AutoMod
    "automod_hit": embed_automod_hit,
    "automod_blocked": embed_automod_blocked,
    "anti_spam": embed_anti_spam,
    "anti_raid": embed_anti_raid,
    
    # Security
    "security_alert": embed_security_alert,
    "anti_nuke": embed_anti_nuke,
    "whitelist_bypass": embed_whitelist_bypass,
    
    # Backup
    "backup_created": embed_backup_created,
    "backup_restored": embed_backup_restored,
    
    # Logging
    "log_message_delete": embed_log_message_delete,
    "log_message_edit": embed_log_message_edit,
    "log_role_create": embed_log_role_create,
    "log_role_delete": embed_log_role_delete,
    "log_channel_create": embed_log_channel_create,
    "log_member_join": embed_log_member_join,
    "log_member_leave": embed_log_member_leave,
    
    # Badges
    "badge_added": embed_badge_added,
    "badge_removed": embed_badge_removed,
    
    # Stats
    "leaderboard": embed_leaderboard,
    "stats": embed_stats,
    
    # Utility
    "success": embed_success,
    "error": embed_error,
    "info": embed_info,
    "help": embed_help,
    "pagination": embed_pagination,
    
    # Voice
    "voice_join": embed_voice_join,
    "voice_leave": embed_voice_leave,
}

print("✅ embed_config.py geladen – Alle Embeds sind zentral definiert.")