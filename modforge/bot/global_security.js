const { PermissionFlagsBits } = require('discord.js');

function globalBanReason(entry) {
  const detail = String(entry?.reason || 'Vom ModForge-Entwicklerteam als hochgradig gefährlich eingestuft').slice(0, 400);
  return `ModForge Global Security: ${detail}`;
}

async function notifyOwnerAboutFailedBan(bot, guild, userId, entry, error) {
  const notificationKey = `global-ban-failed:${guild.id}:${userId}`;
  const recent = await bot.db.global_security_events.findOne({ notification_key: notificationKey, created_at: { $gte: new Date(Date.now() - 86400000) } }).catch(() => null);
  if (recent) return false;
  const owner = await guild.fetchOwner().catch(() => null);
  if (!owner) return false;
  const message = [
    '🚨 **ModForge Global Security Warnung**',
    `Der Nutzer **${entry?.username || userId}** (\`${userId}\`) ist vom ModForge-Entwicklerteam als hochgradig gefährlich eingestuft.`,
    `Grund: **${entry?.reason || 'Globale Sicherheitsliste'}**`,
    '',
    `Ich konnte den Nutzer auf **${guild.name}** nicht bannen: ${error?.message || 'fehlende Berechtigung oder Rollen-Hierarchie'}.`,
    'Bitte verschiebe die ModForge-Botrolle über die Rolle des Nutzers, gib dem Bot **Mitglieder bannen** und prüfe bzw. banne den Nutzer manuell.',
  ].join('\n');
  const sent = await owner.send({ content: message }).then(() => true).catch(() => false);
  await bot.db.recordGlobalSecurityEvent({ type: 'owner_notification', notification_key: notificationKey, guild_id_str: String(guild.id), user_id: String(userId), sent, error: error?.message || null }).catch(() => null);
  return sent;
}

async function enforceBlockedUserOnGuild(bot, guild, userId, entry = null) {
  const id = String(userId);
  if (!bot.db.isGlobalDiscordBlocked(id)) return { guild_id: guild.id, skipped: true, reason: 'not_blocked' };
  if (String(guild.ownerId) === id) {
    const error = new Error('Discord erlaubt nicht, den Server-Owner zu bannen');
    await notifyOwnerAboutFailedBan(bot, guild, id, entry, error);
    return { guild_id: guild.id, ok: false, error: error.message };
  }
  const botMember = guild.members.me;
  if (!botMember?.permissions?.has(PermissionFlagsBits.BanMembers)) {
    const error = new Error('Dem Bot fehlt die Berechtigung Mitglieder bannen');
    await notifyOwnerAboutFailedBan(bot, guild, id, entry, error);
    return { guild_id: guild.id, ok: false, error: error.message };
  }
  try {
    await guild.members.ban(id, { reason: globalBanReason(entry), deleteMessageSeconds: 86400 });
    await bot.db.recordGlobalSecurityEvent({ type: 'global_ban_success', guild_id_str: String(guild.id), guild_name: guild.name, user_id: id, entry_reason: entry?.reason || null }).catch(() => null);
    return { guild_id: guild.id, ok: true };
  } catch (error) {
    await bot.db.recordGlobalSecurityEvent({ type: 'global_ban_failed', guild_id_str: String(guild.id), guild_name: guild.name, user_id: id, error: error.message }).catch(() => null);
    await notifyOwnerAboutFailedBan(bot, guild, id, entry, error);
    return { guild_id: guild.id, ok: false, error: error.message };
  }
}

async function enforceBlockedUserEverywhere(bot, userId, entry = null) {
  const results = [];
  for (const guild of bot.guilds.cache.values()) {
    results.push(await enforceBlockedUserOnGuild(bot, guild, userId, entry));
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  return results;
}

async function enforceGlobalSecurityOnGuild(bot, guild) {
  const entries = await bot.db.listGlobalSecurityEntries('discord_id');
  const results = [];
  for (const entry of entries) results.push(await enforceBlockedUserOnGuild(bot, guild, entry.value, entry));
  return results;
}

async function enforceAllGlobalSecurity(bot) {
  const entries = await bot.db.listGlobalSecurityEntries('discord_id');
  const results = [];
  for (const entry of entries) results.push(...await enforceBlockedUserEverywhere(bot, entry.value, entry));
  return results;
}

module.exports = { globalBanReason, notifyOwnerAboutFailedBan, enforceBlockedUserOnGuild, enforceBlockedUserEverywhere, enforceGlobalSecurityOnGuild, enforceAllGlobalSecurity };
