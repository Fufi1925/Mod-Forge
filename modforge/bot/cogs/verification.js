const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { createEmbed, reply, embedPayload } = require('../utils');
const { COLOR_SUCCESS, COLOR_PRIMARY, COLOR_WARNING } = require('../config');

const verifyTimers = new Map();

const commands = [
  { data: new SlashCommandBuilder().setName('setup_verify').setDescription('Richtet das Verifizierungssystem ein').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild).addChannelOption(option => option.setName('channel').setDescription('Verify-Kanal').setRequired(true)).addStringOption(option => option.setName('mode').setDescription('one_click/captcha/math/quiz').setRequired(false)), async execute(bot, interaction) { const config = await bot.db.fetchConfig(interaction.guild.id); config.verify_system = config.verify_system || {}; config.verify_system.enabled = true; config.verify_system.channel_id = interaction.options.getChannel('channel', true).id; config.verify_system.verify_channel = interaction.options.getChannel('channel', true).id; config.verify_system.mode = interaction.options.getString('mode') || 'one_click'; await bot.db.setConfig(interaction.guild.id, config); return reply(interaction, { embeds: [createEmbed('✅ Verify eingerichtet', 'Verifizierungssystem wurde dauerhaft gespeichert.', COLOR_SUCCESS)] }, true); } },
  { data: new SlashCommandBuilder().setName('verify_roles').setDescription('Verify-Rollen einstellen').setDefaultMemberPermissions(PermissionFlagsBits.ManageRoles).addRoleOption(option => option.setName('add_role').setDescription('Rolle hinzufügen').setRequired(false)).addRoleOption(option => option.setName('remove_role').setDescription('Rolle entfernen').setRequired(false)), async execute(bot, interaction) { const config = await bot.db.fetchConfig(interaction.guild.id); config.verify_system = config.verify_system || {}; const add = interaction.options.getRole('add_role'); const remove = interaction.options.getRole('remove_role'); if (add) config.verify_system.add_roles = [String(add.id)]; if (remove) config.verify_system.remove_roles = [String(remove.id)]; await bot.db.setConfig(interaction.guild.id, config); return reply(interaction, { embeds: [createEmbed('✅ Verify-Rollen', 'Verify-Rollen wurden dauerhaft gespeichert.', COLOR_SUCCESS)] }, true); } },
  { data: new SlashCommandBuilder().setName('verify_quiz_add').setDescription('Quiz-Frage hinzufügen').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild).addStringOption(option => option.setName('question').setDescription('Frage').setRequired(true)).addStringOption(option => option.setName('answer').setDescription('Antwort').setRequired(true)), async execute(bot, interaction) { const config = await bot.db.fetchConfig(interaction.guild.id); config.verify_system = config.verify_system || {}; config.verify_system.quiz = config.verify_system.quiz || []; config.verify_system.quiz.push({ question: interaction.options.getString('question', true), answer: interaction.options.getString('answer', true) }); await bot.db.setConfig(interaction.guild.id, config); return reply(interaction, { embeds: [createEmbed('✅ Quiz-Frage', 'Quiz-Frage wurde hinzugefügt.', COLOR_SUCCESS)] }, true); } },
  { data: new SlashCommandBuilder().setName('verify_timer').setDescription('Auto-Kick Timer für unverifizierte User').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild).addIntegerOption(option => option.setName('minutes').setDescription('Minuten').setRequired(false)).addStringOption(option => option.setName('action').setDescription('kick/ban/none').setRequired(false)), async execute(bot, interaction) { const config = await bot.db.fetchConfig(interaction.guild.id); config.verify_extended = config.verify_extended || {}; config.verify_extended.timer_enabled = true; config.verify_extended.timer_minutes = interaction.options.getInteger('minutes') || 10; config.verify_extended.timer_action = interaction.options.getString('action') || 'kick'; await bot.db.setConfig(interaction.guild.id, config); return reply(interaction, { embeds: [createEmbed('⏱️ Verify-Timer', 'Verify-Timer wurde dauerhaft gespeichert.', COLOR_SUCCESS)] }, true); } },
  { data: new SlashCommandBuilder().setName('verify_stats').setDescription('Verifizierungs-Statistiken'), async execute(bot, interaction) { const full = await bot.db.fetchConfig(interaction.guild.id); const config = full.verify_system || {}; return reply(interaction, { embeds: [createEmbed('✅ Verify-Stats', `Aktiv: **${Boolean(config.enabled)}**\nModus: **${config.mode || 'one_click'}**\nQuiz-Fragen: **${(config.quiz || []).length}**`, COLOR_PRIMARY)] }, true); } },
];

async function sendVerifyDm(bot, member, reason = 'Verifizierung erfolgreich!') {
  await member.send(embedPayload(createEmbed('✅ Verifizierung erfolgreich', `**Server:** ${member.guild.name}\n${reason}`, COLOR_SUCCESS, [], { author: member.client?.user, guild: member.guild }), { author: member.client?.user, guild: member.guild })).catch(() => null);
  await bot.db.data.insertOne({ type: 'verify_dm', guild_id: Number(member.guild.id), guild_id_str: String(member.guild.id), user_id: String(member.id), reason, created_at: new Date() }).catch(() => null);
}

async function verificationExpired(bot, guildId, userId) {
  const key = `${guildId}:${userId}`;
  verifyTimers.delete(key);
  const guild = bot.guilds.cache.get(String(guildId));
  const member = guild ? await guild.members.fetch(String(userId)).catch(() => null) : null;
  if (!member) return;
  const full = await bot.db.fetchConfig(guild.id);
  const system = full.verify_system || {};
  const extended = full.verify_extended || {};
  const verified = (system.add_roles || []).map(String).some(roleId => member.roles.cache.has(roleId));
  if (verified) {
    await bot.db.tempactions.deleteMany({ type: 'verify_expiry', guild_id_str: String(guildId), user_id: String(userId) }).catch(() => null);
    return;
  }
  const action = extended.timer_action || system.timer_action || 'kick';
  if (action === 'ban') await member.ban({ reason: 'Verifizierung nicht rechtzeitig abgeschlossen' }).catch(() => null);
  else if (action === 'kick') await member.kick('Verifizierung nicht rechtzeitig abgeschlossen').catch(() => null);
  await bot.logAction(guild, '⏱️ Verify-Timer', `${member.user.tag} wurde wegen nicht abgeschlossener Verifizierung **${action}** ausgeführt.`, COLOR_WARNING, { module: 'verify', user: member.user }).catch(() => null);
  await bot.db.tempactions.deleteMany({ type: 'verify_expiry', guild_id_str: String(guildId), user_id: String(userId) }).catch(() => null);
}

async function scheduleVerification(bot, member, expiresAt = null) {
  const full = await bot.db.fetchConfig(member.guild.id);
  const system = full.verify_system || {};
  const extended = full.verify_extended || {};
  if (!system.enabled || !extended.timer_enabled) return;
  const minutes = Math.max(1, Number(extended.timer_minutes || 10));
  const expiry = expiresAt ? new Date(expiresAt) : new Date(Date.now() + minutes * 60000);
  const key = `${member.guild.id}:${member.id}`;
  if (verifyTimers.has(key)) clearTimeout(verifyTimers.get(key));
  await bot.db.tempactions.updateOne(
    { type: 'verify_expiry', guild_id_str: String(member.guild.id), user_id: String(member.id) },
    { $set: { type: 'verify_expiry', guild_id_str: String(member.guild.id), user_id: String(member.id), expires_at: expiry, action: extended.timer_action || 'kick', updated_at: new Date() } },
    { upsert: true },
  );
  const delay = Math.max(0, Math.min(expiry.getTime() - Date.now(), 2_147_000_000));
  verifyTimers.set(key, setTimeout(() => void verificationExpired(bot, member.guild.id, member.id), delay));
}

const events = [
  { name: 'interactionCreate', async execute(bot, interaction) {
    if (!interaction.isButton() || interaction.customId !== 'modforge:verify') return;
    const full = await bot.db.fetchConfig(interaction.guild.id);
    const config = full.verify_system || {};
    if (!config.enabled) return interaction.reply({ content: '❌ Verifizierung ist deaktiviert.', ephemeral: true });
    for (const id of (config.add_roles || []).map(String)) await interaction.member.roles.add(id, 'Verifizierung erfolgreich').catch(() => null);
    for (const id of (config.remove_roles || []).map(String)) await interaction.member.roles.remove(id, 'Verifizierung erfolgreich').catch(() => null);
    const key = `${interaction.guild.id}:${interaction.user.id}`;
    if (verifyTimers.has(key)) { clearTimeout(verifyTimers.get(key)); verifyTimers.delete(key); }
    await bot.db.tempactions.deleteMany({ type: 'verify_expiry', guild_id_str: String(interaction.guild.id), user_id: String(interaction.user.id) }).catch(() => null);
    await sendVerifyDm(bot, interaction.member, 'Du wurdest über den Verify-Button verifiziert.');
    await interaction.reply({ embeds: [createEmbed('✅ Erfolg', 'Verifizierung erfolgreich!', COLOR_SUCCESS)], ephemeral: true });
  } },
  { name: 'guildMemberAdd', async execute(bot, member) { if (!member.user.bot) await scheduleVerification(bot, member); } },
  { name: 'guildMemberUpdate', async execute(bot, before, after) { if (after.user.bot) return; const full = await bot.db.fetchConfig(after.guild.id); const config = full.verify_system || {}; const add = (config.add_roles || []).map(String); if (!add.length) return; const gained = add.some(id => !before.roles.cache.has(id) && after.roles.cache.has(id)); if (gained) await sendVerifyDm(bot, after, 'Dir wurde eine Verify-Rolle gegeben.'); } },
  { name: 'clientReady', async execute(bot) {
    const pending = await bot.db.tempactions.find({ type: 'verify_expiry' }).limit(5000).toArray().catch(() => []);
    for (const item of pending) {
      const guild = bot.guilds.cache.get(String(item.guild_id_str || item.guild_id));
      const member = guild ? await guild.members.fetch(String(item.user_id)).catch(() => null) : null;
      if (member) await scheduleVerification(bot, member, item.expires_at);
    }
  } },
];

module.exports = { commands, events, sendVerifyDm, scheduleVerification, verificationExpired };
