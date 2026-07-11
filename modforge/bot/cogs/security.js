const { SlashCommandBuilder, PermissionFlagsBits, AuditLogEvent, ChannelType } = require('discord.js');
const { createEmbed, reply } = require('../utils');
const { COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING } = require('../config');

async function lockdownGuild(guild, reason) {
  let changed = 0;
  for (const channel of guild.channels.cache.values()) {
    if (![ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(channel.type)) continue;
    try { await channel.permissionOverwrites.edit(guild.roles.everyone, { SendMessages: false }, { reason }); changed += 1; } catch {}
  }
  return changed;
}

async function latestExecutor(guild, type, targetId) {
  try {
    const logs = await guild.fetchAuditLogs({ type, limit: 6 });
    const now = Date.now();
    return logs.entries.find(entry => (!targetId || String(entry.target?.id) === String(targetId)) && now - entry.createdTimestamp < 20_000)?.executor || null;
  } catch { return null; }
}

async function trackNukeAction(bot, guild, executor, kind, config) {
  if (!executor || executor.bot || String(executor.id) === String(bot.user.id)) return;
  const member = await guild.members.fetch(executor.id).catch(() => null);
  if (!member || bot.isWhitelisted(member, 'bypass_antinuke')) return;
  const key = `${guild.id}:${executor.id}:${kind}`;
  const entries = bot.tracker.nukeTracker.get(key) || [];
  const now = Date.now();
  const windowSeconds = Number(config.window || 10);
  entries.push(now);
  while (entries.length && now - entries[0] > windowSeconds * 1000) entries.shift();
  bot.tracker.nukeTracker.set(key, entries);
  const threshold = Number(config.threshold || 5);
  if (entries.length < threshold) return;
  bot.tracker.nukeTracker.set(key, []);
  if (config.remove_roles) {
    for (const role of member.roles.cache.values()) if (role.id !== guild.id && role.editable) await member.roles.remove(role, 'Anti-Nuke ausgelöst').catch(() => null);
  }
  const punishment = config.punishment || 'ban';
  await bot.punish(member, punishment, `Anti-Nuke: ${entries.length}× ${kind} in ${windowSeconds}s`, config.timeout_duration || 86400).catch(() => null);
  const locked = config.auto_lockdown ? await lockdownGuild(guild, `Anti-Nuke durch ${executor.tag}`) : 0;
  await bot.logAction(guild, '💥 Anti-Nuke ausgelöst', `**Ausführer:** ${executor}\n**Aktion:** ${kind}\n**Anzahl:** ${entries.length}\n**Strafe:** ${punishment}\n**Gesperrte Kanäle:** ${locked}`, COLOR_DANGER, { module: 'antinuke', executor });
}

const events = [
  { name: 'guildMemberAdd', async execute(bot, member) {
    const cfg = await bot.db.fetchConfig(member.guild.id);
    if (member.user.bot && cfg.server_protection?.bot_approval_required && !(cfg.approved_bots || cfg.server_protection.approved_bots || []).map(String).includes(String(member.id))) {
      await member.kick('Bot ist nicht durch ModForge genehmigt').catch(() => null);
      await bot.logAction(member.guild, '🤖 Nicht genehmigter Bot', `${member.user.tag} wurde automatisch entfernt.`, COLOR_DANGER, { module: 'antinuke', user: member.user });
      return;
    }
    if (!cfg.anti_raid?.enabled || member.user.bot) return;
    const accountAgeDays = (Date.now() - member.user.createdTimestamp) / 86400000;
    if (cfg.anti_raid.auto_kick && accountAgeDays < Number(cfg.anti_raid.min_account_age || 0)) {
      await member.kick(`Anti-Raid: Account jünger als ${cfg.anti_raid.min_account_age} Tage`).catch(() => null);
      await bot.logAction(member.guild, '🚨 Anti-Raid · Neuer Account', `${member.user.tag} wurde automatisch entfernt (${accountAgeDays.toFixed(1)} Tage alt).`, COLOR_WARNING, { module: 'antiraid', user: member.user });
      return;
    }
    const entries = bot.tracker.raidTracker.get(member.guild.id) || [];
    const now = Date.now();
    const windowSeconds = Number(cfg.anti_raid.window || 20);
    const threshold = Number(cfg.anti_raid.join_threshold || cfg.anti_raid.joins || 10);
    entries.push(now);
    while (entries.length && now - entries[0] > windowSeconds * 1000) entries.shift();
    bot.tracker.raidTracker.set(member.guild.id, entries);
    if (entries.length >= threshold) {
      bot.tracker.lockdownActive.set(member.guild.id, true);
      const locked = cfg.anti_raid.lockdown ? await lockdownGuild(member.guild, `Anti-Raid: ${entries.length} Joins`) : 0;
      await bot.logAction(member.guild, '🚨 Anti-Raid', `Raid erkannt: **${entries.length}** Joins in ${windowSeconds}s. **${locked}** Kanäle gesperrt.`, COLOR_DANGER, { module: 'antiraid' });
    }
  } },
  { name: 'channelDelete', async execute(bot, channel) { if (!channel.guild) return; const cfg = await bot.db.fetchConfig(channel.guild.id); if (!cfg.anti_nuke?.enabled) return; const executor = await latestExecutor(channel.guild, AuditLogEvent.ChannelDelete, channel.id); await trackNukeAction(bot, channel.guild, executor, 'Channel-Löschungen', cfg.anti_nuke); } },
  { name: 'roleDelete', async execute(bot, role) { const cfg = await bot.db.fetchConfig(role.guild.id); if (!cfg.anti_nuke?.enabled) return; const executor = await latestExecutor(role.guild, AuditLogEvent.RoleDelete, role.id); await trackNukeAction(bot, role.guild, executor, 'Rollen-Löschungen', cfg.anti_nuke); } },
  { name: 'webhookUpdate', async execute(bot, channel) { await bot.logAction(channel.guild, '🔌 Webhook-Update', `Webhooks in ${channel} wurden geändert.`, COLOR_WARNING, { module: 'webhooks' }); } },
  { name: 'guildUpdate', async execute(bot, before, after) { await bot.logAction(after, '💥 Server-Update', `Server **${before.name}** wurde geändert.`, COLOR_WARNING, { module: 'antinuke' }); } },
];

const commands = [
  { data: new SlashCommandBuilder().setName('snapshot').setDescription('Vergleicht Server mit letztem Snapshot').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild), async execute(bot, interaction) { return reply(interaction, { embeds: [createEmbed('📸 Snapshot', `Rollen: **${interaction.guild.roles.cache.size}**\nChannels: **${interaction.guild.channels.cache.size}**\nMember: **${interaction.guild.memberCount}**`, COLOR_PRIMARY)] }, true); } },
  { data: new SlashCommandBuilder().setName('panic').setDescription('Panic-Button: Sofortiger Lockdown').setDefaultMemberPermissions(PermissionFlagsBits.Administrator), async execute(bot, interaction) { bot.tracker.lockdownActive.set(interaction.guild.id, true); const locked = await lockdownGuild(interaction.guild, `Panic Button von ${interaction.user.tag}`); await bot.logAction(interaction.guild, '🚨 Panic Button', `${interaction.user} hat den Panic-Button ausgelöst. ${locked} Kanäle gesperrt.`, COLOR_DANGER, { module: 'antinuke' }); return reply(interaction, { embeds: [createEmbed('🚨 Panic aktiviert', `${locked} Kanäle wurden gesperrt.`, COLOR_DANGER)] }, true); } },
  { data: new SlashCommandBuilder().setName('nuke_whitelist').setDescription('Nuke-Whitelist verwalten').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addStringOption(option => option.setName('action').setDescription('add/remove/list').setRequired(true)).addUserOption(option => option.setName('user').setDescription('User').setRequired(false)).addRoleOption(option => option.setName('role').setDescription('Rolle').setRequired(false)), async execute(bot, interaction) { const whitelist = await bot.db.fetchWhitelist(interaction.guild.id); const action = interaction.options.getString('action', true); const user = interaction.options.getUser('user'); const role = interaction.options.getRole('role'); if (action === 'add' && user && !whitelist.users.includes(user.id)) whitelist.users.push(user.id); if (action === 'add' && role && !whitelist.roles.includes(role.id)) whitelist.roles.push(role.id); if (action === 'remove' && user) whitelist.users = whitelist.users.filter(id => id !== user.id); if (action === 'remove' && role) whitelist.roles = whitelist.roles.filter(id => id !== role.id); await bot.db.setWhitelist(interaction.guild.id, whitelist); return reply(interaction, { embeds: [createEmbed('🛡️ Nuke-Whitelist', `Users: ${whitelist.users.length}\nRoles: ${whitelist.roles.length}`, COLOR_SUCCESS)] }, true); } },
  { data: new SlashCommandBuilder().setName('emergency_contact').setDescription('Emergency-Contact hinzufügen').setDefaultMemberPermissions(PermissionFlagsBits.Administrator).addStringOption(option => option.setName('action').setDescription('add/remove/list').setRequired(true)).addUserOption(option => option.setName('user').setDescription('User').setRequired(false)), async execute(bot, interaction) { const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.emergency_contacts = cfg.emergency_contacts || []; const action = interaction.options.getString('action', true); const user = interaction.options.getUser('user'); if (action === 'add' && user && !cfg.emergency_contacts.includes(user.id)) cfg.emergency_contacts.push(user.id); if (action === 'remove' && user) cfg.emergency_contacts = cfg.emergency_contacts.filter(id => id !== user.id); await bot.db.setConfig(interaction.guild.id, cfg); return reply(interaction, { embeds: [createEmbed('🚨 Emergency Contacts', `${cfg.emergency_contacts.length} Kontakte gespeichert.`, COLOR_SUCCESS)] }, true); } },
  { data: new SlashCommandBuilder().setName('bot_approve').setDescription('Genehmigt einen Bot').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild).addStringOption(option => option.setName('bot_id').setDescription('Bot ID').setRequired(true)), async execute(bot, interaction) { const cfg = await bot.db.fetchConfig(interaction.guild.id); cfg.approved_bots = cfg.approved_bots || []; const id = interaction.options.getString('bot_id', true); if (!cfg.approved_bots.includes(id)) cfg.approved_bots.push(id); await bot.db.setConfig(interaction.guild.id, cfg); return reply(interaction, { embeds: [createEmbed('✅ Bot approved', `Bot **${id}** wurde genehmigt.`, COLOR_SUCCESS)] }, true); } },
];

module.exports = { commands, events, lockdownGuild, trackNukeAction };
