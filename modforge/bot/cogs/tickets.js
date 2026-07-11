const { SlashCommandBuilder, PermissionFlagsBits, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType } = require('discord.js');
const { createEmbed, reply, embedPayload } = require('../utils');
const { COLOR_SUCCESS, COLOR_PRIMARY, COLOR_WARNING } = require('../config');

function ticketButtons() {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('modforge:close_ticket').setLabel('Ticket schließen').setEmoji('🔒').setStyle(ButtonStyle.Danger),
  );
}

const commands = [{
  data: new SlashCommandBuilder().setName('ticket_panel').setDescription('Sendet das Ticket-Panel').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild).addChannelOption(option => option.setName('channel').setDescription('Kanal').setRequired(false)),
  async execute(bot, interaction) {
    const channel = interaction.options.getChannel('channel') || interaction.channel;
    const row = new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('modforge:open_ticket').setLabel('Ticket öffnen').setEmoji('🎫').setStyle(ButtonStyle.Primary));
    const message = await channel.send({ embeds: [createEmbed('🎫 Support-Ticket', 'Klicke auf den Button, um ein Ticket zu öffnen.', COLOR_PRIMARY)], components: [row] });
    const config = await bot.db.fetchConfig(interaction.guild.id);
    config.ticket_system = { ...(config.ticket_system || {}), enabled: true, panel_channel_id: String(channel.id), panel_message_id: String(message.id) };
    await bot.db.setConfig(interaction.guild.id, config);
    return reply(interaction, { embeds: [createEmbed('✅ Ticket-Panel', 'Ticket-Panel wurde gesendet und dauerhaft gespeichert.', COLOR_SUCCESS)] }, true);
  },
}];

async function createTicket(bot, interaction) {
  const fullConfig = await bot.db.fetchConfig(interaction.guild.id);
  const config = fullConfig.ticket_system || {};
  const extended = fullConfig.ticket_extended || {};
  if (config.enabled === false) return interaction.reply({ content: '❌ Das Ticket-System ist deaktiviert.', ephemeral: true });
  const openTickets = await bot.db.data.countDocuments({ type: 'ticket', guild_id_str: String(interaction.guild.id), user_id: String(interaction.user.id), status: 'open' }).catch(() => 0);
  const maximum = Math.max(1, Number(extended.max_open_per_user || 3));
  if (openTickets >= maximum) return interaction.reply({ content: `❌ Du kannst maximal ${maximum} offene Tickets haben.`, ephemeral: true });

  const category = config.category_id ? await interaction.guild.channels.fetch(String(config.category_id)).catch(() => null) : null;
  const safeName = interaction.user.username.toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 20) || interaction.user.id;
  const channel = await interaction.guild.channels.create({
    name: `ticket-${safeName}`,
    type: ChannelType.GuildText,
    parent: category?.id,
    reason: `Ticket geöffnet durch ${interaction.user.tag}`,
    permissionOverwrites: [
      { id: interaction.guild.roles.everyone.id, deny: [PermissionFlagsBits.ViewChannel] },
      { id: interaction.user.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.AttachFiles] },
      { id: interaction.guild.members.me.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ManageChannels, PermissionFlagsBits.ReadMessageHistory] },
    ],
  });
  const ticketId = channel.id;
  await bot.db.data.insertOne({ type: 'ticket', ticket_id: String(ticketId), guild_id: Number(interaction.guild.id), guild_id_str: String(interaction.guild.id), channel_id: String(channel.id), user_id: String(interaction.user.id), status: 'open', created_at: new Date() });
  await channel.send({ content: `${interaction.user}`, embeds: [createEmbed('🎫 Ticket geöffnet', 'Beschreibe dein Anliegen. Ein Teammitglied meldet sich bald.', COLOR_PRIMARY)], components: [ticketButtons()] });
  await interaction.user.send(embedPayload(createEmbed('🎫 Ticket erstellt', `**Server:** ${interaction.guild.name}\nDein Ticket wurde erstellt: ${channel}`, COLOR_SUCCESS, [], { author: interaction.user, guild: interaction.guild }), { author: interaction.user, guild: interaction.guild })).catch(() => null);
  await interaction.reply({ content: `✅ Ticket erstellt: ${channel}`, ephemeral: true });
}

async function closeTicket(bot, interaction) {
  const ticket = await bot.db.data.findOne({ type: 'ticket', guild_id_str: String(interaction.guild.id), channel_id: String(interaction.channel.id), status: 'open' }).catch(() => null);
  if (!ticket) return interaction.reply({ content: '❌ Dieser Kanal ist kein offenes ModForge-Ticket.', ephemeral: true });
  const owner = String(ticket.user_id) === String(interaction.user.id);
  const staff = interaction.member.permissions.has(PermissionFlagsBits.ManageMessages);
  if (!owner && !staff) return interaction.reply({ content: '❌ Du darfst dieses Ticket nicht schließen.', ephemeral: true });
  await interaction.deferReply({ ephemeral: true });
  const fetched = await interaction.channel.messages.fetch({ limit: 100 }).catch(() => null);
  const messages = fetched ? [...fetched.values()].sort((a, b) => a.createdTimestamp - b.createdTimestamp).map(message => ({ id: String(message.id), author_id: String(message.author.id), author: message.author.tag, content: message.content || '', attachments: [...message.attachments.values()].map(item => item.url), created_at: message.createdAt })) : [];
  const transcriptText = messages.map(message => `[${new Date(message.created_at).toISOString()}] ${message.author}: ${message.content}`).join('\n');
  await bot.db.asave_ticket_transcript(interaction.guild.id, ticket.ticket_id || ticket.channel_id, { channel_id: String(interaction.channel.id), user_id: String(ticket.user_id), closed_by: String(interaction.user.id), status: 'closed', created_at: ticket.created_at || new Date(), closed_at: new Date(), created_at_iso: new Date(ticket.created_at || Date.now()).toISOString(), transcript: transcriptText, messages });
  await bot.db.data.updateOne({ _id: ticket._id }, { $set: { status: 'closed', closed_at: new Date(), closed_by: String(interaction.user.id) } }).catch(() => null);
  await interaction.editReply({ content: '✅ Ticket wurde archiviert. Der Kanal wird in 5 Sekunden gelöscht.' });
  setTimeout(() => void interaction.channel.delete(`Ticket geschlossen von ${interaction.user.tag}`).catch(() => null), 5000);
}

const events = [{
  name: 'interactionCreate',
  async execute(bot, interaction) {
    if (!interaction.isButton()) return;
    if (interaction.customId === 'modforge:open_ticket') return createTicket(bot, interaction);
    if (interaction.customId === 'modforge:close_ticket') return closeTicket(bot, interaction);
  },
}];

module.exports = { commands, events, createTicket, closeTicket };
