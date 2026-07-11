const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getEmbed } = require('../embed_config');

function replaceVars(text, member) {
  return String(text || '')
    .replaceAll('{mention}', `${member}`)
    .replaceAll('{user}', String(member.user?.tag || member))
    .replaceAll('{username}', String(member.user?.username || member.displayName || member))
    .replaceAll('{server}', member.guild?.name || '')
    .replaceAll('{count}', String(member.guild?.memberCount || 0));
}

function styleWelcomeEmbed(embed, config, member) {
  if (config.embed_title) embed.setTitle(replaceVars(config.embed_title, member));
  if (config.embed_description) embed.setDescription(replaceVars(config.embed_description, member));
  if (config.embed_color) embed.setColor(config.embed_color);
  if (config.embed_image) embed.setImage(config.embed_image);
  if (config.embed_thumbnail && member.user?.displayAvatarURL) embed.setThumbnail(member.user.displayAvatarURL({ size: 256 }));
  return embed;
}

async function sendWelcome(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const welcome = cfg.welcome || {};
  for (const roleId of welcome.add_roles || []) await member.roles.add(String(roleId), 'Auto-Role bei Join').catch(() => null);
  if (welcome.dm_enabled && welcome.dm_description) {
    const dmEmbed = styleWelcomeEmbed(getEmbed('welcome', { guild: member.guild, user: member, bot }), { ...welcome, embed_description: welcome.dm_description }, member);
    await member.send({ embeds: [dmEmbed] }).catch(() => null);
  }
  if (!welcome.enabled || !welcome.channel_id) return;
  const channel = await member.guild.channels.fetch(String(welcome.channel_id)).catch(() => null);
  if (!channel?.isTextBased?.()) return;
  const embed = styleWelcomeEmbed(getEmbed('welcome', { guild: member.guild, user: member, bot }), welcome, member);
  await channel.send({ content: welcome.mention ? `${member}` : null, embeds: [embed] }).catch(() => null);
}

async function sendLeave(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const leave = cfg.leave || {};
  if (!leave.enabled || !leave.channel_id) return;
  const channel = await member.guild.channels.fetch(leave.channel_id).catch(() => null);
  if (!channel?.isTextBased?.()) return;
  const embed = styleWelcomeEmbed(getEmbed('leave', { guild: member.guild, user: member, bot }), leave, member);
  await channel.send({ embeds: [embed] }).catch(() => null);
}

async function restoreStickyRoles(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const sticky = (cfg.sticky_roles || []).map(String);
  if (!sticky.length) return;
  const doc = await bot.db.data.findOne({ guild_id_str: String(member.guild.id), user_id: String(member.id), type: 'sticky_roles' }).catch(() => null)
    || await bot.db.data.findOne({ guild_id: Number(member.guild.id), user_id: String(member.id), type: 'sticky_roles' }).catch(() => null);
  if (doc?.roles) for (const roleId of doc.roles.map(String)) if (sticky.includes(roleId)) await member.roles.add(roleId, 'Sticky-Role wiederhergestellt').catch(() => null);
}

async function saveStickyRoles(bot, member) {
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const sticky = new Set((cfg.sticky_roles || []).map(String));
  if (!sticky.size) return;
  const roles = member.roles.cache.map(role => String(role.id)).filter(id => sticky.has(id));
  await bot.db.data.updateOne(
    { type: 'sticky_roles', guild_id_str: String(member.guild.id), user_id: String(member.id) },
    { $set: { type: 'sticky_roles', guild_id_str: String(member.guild.id), user_id: String(member.id), roles, updated_at: new Date() } },
    { upsert: true },
  ).catch(() => null);
}

async function applyAutoNickname(bot, member) {
  if (member.user.bot || member.manageable === false) return;
  const cfg = await bot.db.fetchConfig(member.guild.id);
  const settings = cfg.auto_nickname || {};
  if (!settings.enabled) return;
  const exempt = new Set((settings.exempt_roles || []).map(item => String(item?.id || item)));
  if (member.roles.cache.some(role => exempt.has(String(role.id)))) return;
  const rule = (settings.rules || []).find(item => member.roles.cache.has(String(item.role_id)));
  if (!rule) return;
  const base = member.user.globalName || member.user.username || member.displayName;
  const nickname = `${rule.prefix || ''}${base}${rule.suffix || ''}`.slice(0, 32);
  await member.setNickname(nickname || null, 'ModForge Auto-Nickname').catch(() => null);
}

const commands = [{
  data: new SlashCommandBuilder().setName('welcome_channel').setDescription('Setzt den Welcome-Kanal')
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addChannelOption(o => o.setName('channel').setDescription('Der Kanal').setRequired(true)),
  async execute(bot, interaction) {
    const channel = interaction.options.getChannel('channel', true);
    const cfg = await bot.db.fetchConfig(interaction.guild.id);
    cfg.welcome = cfg.welcome || {};
    cfg.welcome.channel_id = channel.id;
    cfg.welcome.enabled = true;
    await bot.db.setConfig(interaction.guild.id, cfg);
    await interaction.reply({ content: `✅ Welcome-Kanal auf ${channel} gesetzt.`, ephemeral: true });
  }
}];

const events = [
  { name: 'guildMemberAdd', async execute(bot, member) { await restoreStickyRoles(bot, member); await sendWelcome(bot, member); await applyAutoNickname(bot, member); } },
  { name: 'guildMemberRemove', async execute(bot, member) { await saveStickyRoles(bot, member); await sendLeave(bot, member); } },
];

module.exports = { commands, events, sendWelcome, sendLeave, restoreStickyRoles, saveStickyRoles, applyAutoNickname };
