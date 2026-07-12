const {
  ActionRowBuilder,
  AttachmentBuilder,
  ButtonBuilder,
  ButtonStyle,
  ChannelType,
  ContainerBuilder,
  MessageFlags,
  ModalBuilder,
  PermissionFlagsBits,
  SeparatorBuilder,
  SeparatorSpacingSize,
  StringSelectMenuBuilder,
  StringSelectMenuOptionBuilder,
  TextDisplayBuilder,
  TextInputBuilder,
  TextInputStyle,
} = require('discord.js');

const creationLocks = new Set();
const actionLocks = new Set();

function truncate(value, length) {
  const text = String(value ?? '');
  return text.length > length ? `${text.slice(0, Math.max(0, length - 1))}…` : text;
}

function safeChannelPart(value) {
  return String(value || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'user';
}

function uniqueStrings(values) {
  return [...new Set((Array.isArray(values) ? values : []).map(String).filter(Boolean))];
}

function ephemeralComponents(text) {
  return { components: [new TextDisplayBuilder().setContent(String(text).slice(0, 4000))], flags: MessageFlags.Ephemeral | MessageFlags.IsComponentsV2 };
}

async function respondEphemeral(interaction, text) {
  const payload = ephemeralComponents(text);
  if (interaction.deferred || interaction.replied) return interaction.editReply({ components: payload.components });
  return interaction.reply(payload);
}

function memberHasAnyRole(member, roleIds) {
  const ids = new Set(uniqueStrings(roleIds));
  return ids.size > 0 && member?.roles?.cache?.some(role => ids.has(String(role.id)));
}

function ticketRoleSets(settings, category) {
  return {
    team: uniqueStrings([...(settings.global_team_roles || []), ...(category.team_roles || [])]),
    admin: uniqueStrings([...(settings.global_admin_roles || []), ...(category.admin_roles || [])]),
  };
}

function isTicketAdmin(member, settings, category) {
  return Boolean(member?.permissions?.has(PermissionFlagsBits.Administrator) || memberHasAnyRole(member, ticketRoleSets(settings, category).admin));
}

function isTicketTeam(member, settings, category) {
  const roles = ticketRoleSets(settings, category);
  return isTicketAdmin(member, settings, category) || memberHasAnyRole(member, roles.team);
}

function canClaim(member, settings, category) {
  if (settings.claim_enabled === false) return false;
  return settings.permissions?.claim === 'admin' ? isTicketAdmin(member, settings, category) : isTicketTeam(member, settings, category);
}

function canClose(member, ticket, settings, category) {
  if (isTicketAdmin(member, settings, category)) return true;
  const rule = settings.permissions?.close || 'team_or_owner';
  if (rule === 'admin') return false;
  if ((rule === 'team' || rule === 'team_or_owner') && isTicketTeam(member, settings, category)) return true;
  if (String(ticket.claimer_id || '') === String(member.id)) return true;
  return rule !== 'team' && settings.owner_can_close !== false && String(ticket.owner_id) === String(member.id);
}

function canManageTicketAction(member, settings, category, action) {
  if (isTicketAdmin(member, settings, category)) return true;
  return settings.permissions?.[action] === 'team' && isTicketTeam(member, settings, category);
}

function formatTicketName(format, category, interaction, ticketId) {
  return safeChannelPart(String(format || category.name_format || '{category}-{username}-{id}')
    .replaceAll('{category}', category.key)
    .replaceAll('{username}', interaction.user.username)
    .replaceAll('{user}', interaction.user.username)
    .replaceAll('{id}', String(ticketId))
    .replaceAll('{userid}', String(interaction.user.id))).slice(0, 100);
}

function buildTicketPanel(settings, categories) {
  const options = categories.filter(category => category.enabled !== false).slice(0, 25).map(category => {
    const option = new StringSelectMenuOptionBuilder()
      .setLabel(truncate(category.name || category.key, 100))
      .setValue(String(category.key))
      .setDescription(truncate(category.description || 'Ticket öffnen', 100));
    if (category.emoji) {
      try { option.setEmoji(category.emoji); } catch {}
    }
    return option;
  });
  if (!options.length) throw new Error('Es ist keine aktive Ticket-Kategorie vorhanden.');
  const select = new StringSelectMenuBuilder()
    .setCustomId('mf:t:create')
    .setPlaceholder(truncate(settings.panel_placeholder || 'Ticket-Kategorie auswählen', 150))
    .setMinValues(1)
    .setMaxValues(1)
    .addOptions(options);
  const container = new ContainerBuilder()
    .setAccentColor(0x5865F2)
    .addTextDisplayComponents(
      new TextDisplayBuilder().setContent(`# ${truncate(settings.panel_title || 'Support Tickets', 250)}`),
      new TextDisplayBuilder().setContent(truncate(settings.panel_description || 'Wähle unten die passende Kategorie für dein Anliegen.', 3500)),
    )
    .addSeparatorComponents(new SeparatorBuilder().setDivider(true).setSpacing(SeparatorSpacingSize.Small))
    .addActionRowComponents(new ActionRowBuilder().addComponents(select));
  return { components: [container], flags: MessageFlags.IsComponentsV2 };
}

function buildTicketControls(ticket, category, settings) {
  const statusLabels = { open: 'Offen', claimed: 'Geclaimt', closed: 'Geschlossen', archived: 'Archiviert', deleted: 'Gelöscht' };
  const answerText = (ticket.modal_answers || []).length
    ? `\n${ticket.modal_answers.map(answer => `**${answer.label}:**\n${truncate(answer.value, 800)}`).join('\n\n')}`
    : '';
  const info = [
    `# Ticket #${ticket.ticket_id} · ${category.emoji || '🎫'} ${category.name}`,
    `**Status:** ${statusLabels[ticket.status] || ticket.status}`,
    `**Ersteller:** <@${ticket.owner_id}>`,
    ticket.claimer_id ? `**Bearbeiter:** <@${ticket.claimer_id}>` : '**Bearbeiter:** Noch nicht übernommen',
    `**Erstellt:** <t:${Math.floor(new Date(ticket.created_at).getTime() / 1000)}:F>`,
    answerText,
  ].filter(Boolean).join('\n');
  const primary = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`mf:t:claim:${ticket.ticket_id}`).setLabel('Claim').setEmoji('🙋').setStyle(ButtonStyle.Success).setDisabled(ticket.status !== 'open'),
    new ButtonBuilder().setCustomId(`mf:t:unclaim:${ticket.ticket_id}`).setLabel('Unclaim').setEmoji('↩️').setStyle(ButtonStyle.Secondary).setDisabled(ticket.status !== 'claimed' || settings.unclaim_enabled === false),
    new ButtonBuilder().setCustomId(`mf:t:close:${ticket.ticket_id}`).setLabel('Schließen').setEmoji('🔒').setStyle(ButtonStyle.Danger).setDisabled(!['open', 'claimed'].includes(ticket.status)),
  );
  const admin = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`mf:t:archive:${ticket.ticket_id}`).setLabel('Archivieren').setEmoji('📦').setStyle(ButtonStyle.Secondary).setDisabled(['archived', 'deleted'].includes(ticket.status)),
    new ButtonBuilder().setCustomId(`mf:t:delete:${ticket.ticket_id}`).setLabel('Löschen').setEmoji('🗑️').setStyle(ButtonStyle.Danger).setDisabled(ticket.status === 'deleted'),
  );
  const container = new ContainerBuilder()
    .setAccentColor(ticket.status === 'claimed' ? 0xF59E0B : ticket.status === 'open' ? 0x22C55E : 0x64748B)
    .addTextDisplayComponents(new TextDisplayBuilder().setContent(info))
    .addSeparatorComponents(new SeparatorBuilder().setDivider(true).setSpacing(SeparatorSpacingSize.Small))
    .addActionRowComponents(primary, admin);
  return { components: [container], flags: MessageFlags.IsComponentsV2 };
}

function buildConfirmation(ticketId) {
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`mf:t:close-confirm:${ticketId}`).setLabel('Ja, schließen').setStyle(ButtonStyle.Danger),
    new ButtonBuilder().setCustomId(`mf:t:close-cancel:${ticketId}`).setLabel('Abbrechen').setStyle(ButtonStyle.Secondary),
  );
  const container = new ContainerBuilder()
    .setAccentColor(0xEF4444)
    .addTextDisplayComponents(new TextDisplayBuilder().setContent('## Ticket wirklich schließen?\nJe nach Einstellung wird ein Transcript erstellt und der Kanal archiviert oder gelöscht.'))
    .addActionRowComponents(row);
  return { components: [container], flags: MessageFlags.Ephemeral | MessageFlags.IsComponentsV2 };
}

function buildModal(category) {
  const modal = new ModalBuilder().setCustomId(`mf:t:modal:${category.key}`).setTitle(truncate(category.modal_title || `${category.name} Ticket`, 45));
  const questions = (category.modal_questions || []).filter(question => question.enabled !== false).sort((a, b) => Number(a.position || 0) - Number(b.position || 0)).slice(0, 5);
  for (const [index, question] of questions.entries()) {
    const input = new TextInputBuilder()
      .setCustomId(`q${index}`)
      .setLabel(truncate(question.label || question.question || `Frage ${index + 1}`, 45))
      .setStyle(String(question.style).toLowerCase() === 'paragraph' ? TextInputStyle.Paragraph : TextInputStyle.Short)
      .setRequired(question.required !== false)
      .setMinLength(Math.max(0, Math.min(4000, Number(question.min_length || 0))))
      .setMaxLength(Math.max(1, Math.min(4000, Number(question.max_length || (String(question.style).toLowerCase() === 'paragraph' ? 2000 : 200)))));
    if (question.placeholder) input.setPlaceholder(truncate(question.placeholder, 100));
    modal.addComponents(new ActionRowBuilder().addComponents(input));
  }
  return { modal, questions };
}

async function sendTicketLog(bot, guild, settings, action, ticket, actorId, details = '') {
  await bot.db.logTicketV2(guild.id, action, { ticket_id: ticket?.ticket_id || null, channel_id: ticket?.channel_id || null, actor_id: actorId ? String(actorId) : null, owner_id: ticket?.owner_id || null, category_key: ticket?.category_key || null, details: truncate(details, 2000) });
  const channel = settings.log_channel_id ? guild.channels.cache.get(String(settings.log_channel_id)) : null;
  if (!channel?.isTextBased?.()) return;
  const text = new TextDisplayBuilder().setContent(`## 🎫 ${action}\n${ticket ? `Ticket **#${ticket.ticket_id}** · <#${ticket.channel_id || '0'}>` : ''}\n${actorId ? `Aktion von <@${actorId}>` : ''}${details ? `\n${details}` : ''}`);
  await channel.send({ components: [new ContainerBuilder().setAccentColor(0x5865F2).addTextDisplayComponents(text)], flags: MessageFlags.IsComponentsV2 }).catch(() => null);
}

async function sendOrUpdatePanel(bot, guild, actorId, forceNew = false) {
  const settings = await bot.db.getTicketSettingsV2(guild.id);
  const categories = await bot.db.listTicketCategoriesV2(guild.id, true);
  const channel = settings.panel_channel_id ? guild.channels.cache.get(String(settings.panel_channel_id)) : null;
  if (!channel?.isTextBased?.()) throw new Error('Der konfigurierte Panel-Channel existiert nicht oder ist kein Textkanal.');
  const payload = buildTicketPanel(settings, categories);
  let message = !forceNew && settings.panel_message_id ? await channel.messages.fetch(String(settings.panel_message_id)).catch(() => null) : null;
  if (message) await message.edit(payload);
  else message = await channel.send(payload);
  const updated = await bot.db.saveTicketSettingsV2(guild.id, { ...settings, panel_channel_id: String(channel.id), panel_message_id: String(message.id) });
  await sendTicketLog(bot, guild, updated, message ? 'panel_sent_or_updated' : 'panel_sent', null, actorId, `Panel-Message ${message.id}`);
  return { settings: updated, message };
}

async function collectMessages(channel, maximum = 1000) {
  const messages = [];
  let before;
  while (messages.length < maximum) {
    const batch = await channel.messages.fetch({ limit: Math.min(100, maximum - messages.length), before }).catch(() => null);
    if (!batch?.size) break;
    messages.push(...batch.values());
    before = batch.last().id;
    if (batch.size < 100) break;
  }
  return messages.sort((a, b) => a.createdTimestamp - b.createdTimestamp);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
}

async function createTranscript(bot, interaction, ticket, settings, category) {
  if (settings.transcript_enabled === false || category.transcript_enabled === false) return null;
  const messages = await collectMessages(interaction.channel);
  const plainRows = messages.map(message => ({ id: String(message.id), author_id: String(message.author.id), author: message.author.tag || message.author.username, content: message.content || '', attachments: [...message.attachments.values()].map(attachment => attachment.url), created_at: message.createdAt }));
  const format = String(settings.transcript_format || 'html').toLowerCase() === 'txt' ? 'txt' : 'html';
  const content = format === 'txt'
    ? plainRows.map(row => `[${new Date(row.created_at).toISOString()}] ${row.author}: ${row.content}${row.attachments.length ? `\n  Attachments: ${row.attachments.join(', ')}` : ''}`).join('\n')
    : `<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Ticket #${ticket.ticket_id}</title><style>body{font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:24px}.m{padding:10px 12px;border-bottom:1px solid #334155}.a{font-weight:800;color:#93c5fd}.t{font-size:12px;color:#94a3b8}.c{white-space:pre-wrap;margin-top:4px}</style></head><body><h1>Ticket #${ticket.ticket_id} · ${escapeHtml(category.name)}</h1>${plainRows.map(row => `<div class="m"><span class="a">${escapeHtml(row.author)}</span> <span class="t">${new Date(row.created_at).toLocaleString('de-DE')}</span><div class="c">${escapeHtml(row.content)}</div>${row.attachments.map(url => `<a href="${escapeHtml(url)}">Attachment</a>`).join(' ')}</div>`).join('')}</body></html>`;
  const fileName = `ticket-${ticket.ticket_id}.${format}`;
  let url = null;
  const transcriptChannel = settings.transcript_channel_id ? interaction.guild.channels.cache.get(String(settings.transcript_channel_id)) : null;
  if (transcriptChannel?.isTextBased?.()) {
    const sent = await transcriptChannel.send({ files: [new AttachmentBuilder(Buffer.from(content, 'utf8'), { name: fileName })] }).catch(() => null);
    url = sent?.attachments?.first()?.url || sent?.url || null;
  }
  await bot.db.asave_ticket_transcript(interaction.guild.id, ticket.ticket_id, { ticket_id: String(ticket.ticket_id), channel_id: String(interaction.channel.id), user_id: String(ticket.owner_id), status: ticket.status, format, file_name: fileName, transcript: content, transcript_url: url, messages: plainRows, created_at: ticket.created_at, closed_at: new Date() });
  return { format, content, fileName, url };
}

async function createTicketChannel(bot, interaction, category, answers = []) {
  const lockKey = `${interaction.guild.id}:${interaction.user.id}:${category.key}`;
  if (creationLocks.has(lockKey)) return respondEphemeral(interaction, '⏳ Für diese Kategorie wird bereits ein Ticket erstellt.');
  creationLocks.add(lockKey);
  let databaseLock = false;
  try {
    databaseLock = bot.db.acquireTicketCreationLockV2 ? await bot.db.acquireTicketCreationLockV2(interaction.guild.id, interaction.user.id, category.key) : true;
    if (!databaseLock) return respondEphemeral(interaction, '⏳ Für diese Kategorie wird bereits serverübergreifend ein Ticket erstellt.');
    if (!interaction.deferred && !interaction.replied) await interaction.deferReply({ flags: MessageFlags.Ephemeral | MessageFlags.IsComponentsV2 });
    const settings = await bot.db.getTicketSettingsV2(interaction.guild.id);
    const freshCategory = await bot.db.getTicketCategoryV2(interaction.guild.id, category.key);
    if (!settings.enabled || !freshCategory?.enabled) return respondEphemeral(interaction, '❌ Dieses Ticket-System oder diese Kategorie ist deaktiviert.');
    const parent = interaction.guild.channels.cache.get(String(freshCategory.discord_category_id || ''));
    if (!parent || parent.type !== ChannelType.GuildCategory) return respondEphemeral(interaction, '❌ Die konfigurierte Discord-Kategorie existiert nicht mehr.');
    const globalOpen = await bot.db.countOpenTicketsV2(interaction.guild.id, interaction.user.id);
    if (globalOpen >= Number(settings.max_open_global || 3)) return respondEphemeral(interaction, `❌ Du hast bereits das globale Limit von ${settings.max_open_global || 3} offenen Tickets erreicht.`);
    const categoryOpen = await bot.db.countOpenTicketsV2(interaction.guild.id, interaction.user.id, freshCategory.key);
    const categoryLimit = Number(freshCategory.max_open_per_user || 1);
    if (categoryOpen >= categoryLimit || (freshCategory.allow_multiple === false && categoryOpen > 0)) return respondEphemeral(interaction, `❌ Du hast in **${freshCategory.name}** bereits die maximal erlaubte Anzahl offener Tickets.`);
    const teamRoles = uniqueStrings([...(settings.global_team_roles || []), ...(freshCategory.team_roles || [])]).filter(roleId => interaction.guild.roles.cache.has(roleId));
    const adminRoles = uniqueStrings([...(settings.global_admin_roles || []), ...(freshCategory.admin_roles || [])]).filter(roleId => interaction.guild.roles.cache.has(roleId));
    const ticketId = await bot.db.nextTicketIdV2(interaction.guild.id);
    const channelName = formatTicketName(freshCategory.name_format || settings.ticket_name_format, freshCategory, interaction, ticketId);
    const channel = await interaction.guild.channels.create({
      name: `${safeChannelPart(freshCategory.channel_prefix || '')}${freshCategory.channel_prefix ? '-' : ''}${channelName}`.slice(0, 100),
      type: ChannelType.GuildText,
      parent: parent.id,
      topic: `ModForge Ticket #${ticketId} | Owner ${interaction.user.id} | ${freshCategory.key}`,
      reason: `Ticket #${ticketId} von ${interaction.user.tag}`,
      permissionOverwrites: [
        { id: interaction.guild.roles.everyone.id, deny: [PermissionFlagsBits.ViewChannel] },
        { id: interaction.user.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.AttachFiles, PermissionFlagsBits.EmbedLinks] },
        { id: interaction.guild.members.me.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.ManageChannels, PermissionFlagsBits.ManageMessages] },
        ...teamRoles.map(id => ({ id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.AttachFiles] })),
        ...adminRoles.filter(id => !teamRoles.includes(id)).map(id => ({ id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.ManageMessages] })),
      ],
    });
    const ticket = await bot.db.createTicketV2(interaction.guild.id, { ticket_id: ticketId, channel_id: String(channel.id), owner_id: String(interaction.user.id), owner_tag: interaction.user.tag, category_key: freshCategory.key, category_name: freshCategory.name, status: 'open', claimer_id: null, modal_answers: answers });
    const controlMessage = await channel.send(buildTicketControls(ticket, freshCategory, settings));
    await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { control_message_id: String(controlMessage.id) });
    if (freshCategory.ping_enabled && freshCategory.ping_role_id && interaction.guild.roles.cache.has(String(freshCategory.ping_role_id))) {
      const ping = await channel.send({ components: [new TextDisplayBuilder().setContent(`<@&${freshCategory.ping_role_id}> Neues **${freshCategory.name}**-Ticket #${ticket.ticket_id}`)], flags: MessageFlags.IsComponentsV2, allowedMentions: { roles: [String(freshCategory.ping_role_id)] } }).catch(() => null);
      if (ping && freshCategory.ping_delete) setTimeout(() => void ping.delete().catch(() => null), Math.max(1, Number(freshCategory.ping_delay_seconds || 10)) * 1000);
    }
    await sendTicketLog(bot, interaction.guild, settings, 'ticket_created', ticket, interaction.user.id, `Kategorie ${freshCategory.key}`);
    await respondEphemeral(interaction, `✅ Ticket erstellt: ${channel}`);
    return ticket;
  } catch (error) {
    await respondEphemeral(interaction, `❌ Ticket konnte nicht erstellt werden: ${error.message}`).catch(() => null);
    throw error;
  } finally {
    creationLocks.delete(lockKey);
    if (databaseLock && bot.db.releaseTicketCreationLockV2) await bot.db.releaseTicketCreationLockV2(interaction.guild.id, interaction.user.id, category.key).catch(() => null);
  }
}

async function resolveTicketContext(bot, interaction, ticketId) {
  const ticket = await bot.db.getTicketV2(interaction.guild.id, ticketId);
  if (!ticket) throw new Error('Ticket nicht gefunden.');
  const settings = await bot.db.getTicketSettingsV2(interaction.guild.id);
  const category = await bot.db.getTicketCategoryV2(interaction.guild.id, ticket.category_key);
  if (!category) throw new Error('Ticket-Kategorie nicht gefunden.');
  return { ticket, settings, category };
}

async function refreshControlMessage(bot, guild, ticket, category, settings) {
  const channel = ticket.channel_id ? guild.channels.cache.get(String(ticket.channel_id)) : null;
  if (!channel?.isTextBased?.() || !ticket.control_message_id) return;
  const message = await channel.messages.fetch(String(ticket.control_message_id)).catch(() => null);
  if (message) await message.edit(buildTicketControls(ticket, category, settings)).catch(() => null);
}

async function claimTicket(bot, interaction, ticketId) {
  const { ticket, settings, category } = await resolveTicketContext(bot, interaction, ticketId);
  if (!canClaim(interaction.member, settings, category)) return interaction.reply(ephemeralComponents('❌ Nur konfigurierte Team- oder Admin-Rollen dürfen Tickets claimen.'));
  if (ticket.status === 'claimed' && ticket.claimer_id && String(ticket.claimer_id) !== String(interaction.user.id) && !isTicketAdmin(interaction.member, settings, category)) return interaction.reply(ephemeralComponents(`❌ Dieses Ticket wurde bereits von <@${ticket.claimer_id}> übernommen.`));
  if (!['open', 'claimed'].includes(ticket.status)) return interaction.reply(ephemeralComponents('❌ Dieses Ticket ist nicht mehr offen.'));
  const updated = await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'claimed', claimer_id: String(interaction.user.id), claimed_at: new Date() });
  await refreshControlMessage(bot, interaction.guild, updated, category, settings);
  await sendTicketLog(bot, interaction.guild, settings, 'ticket_claimed', updated, interaction.user.id);
  return interaction.reply(ephemeralComponents(`✅ Ticket #${ticket.ticket_id} wurde von dir übernommen.`));
}

async function unclaimTicket(bot, interaction, ticketId) {
  const { ticket, settings, category } = await resolveTicketContext(bot, interaction, ticketId);
  if (settings.unclaim_enabled === false) return interaction.reply(ephemeralComponents('❌ Unclaim ist deaktiviert.'));
  if (String(ticket.claimer_id || '') !== String(interaction.user.id) && !isTicketAdmin(interaction.member, settings, category)) return interaction.reply(ephemeralComponents('❌ Nur der aktuelle Claimer oder eine Override-Rolle darf unclaimen.'));
  const updated = await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'open', claimer_id: null, claimed_at: null });
  await refreshControlMessage(bot, interaction.guild, updated, category, settings);
  await sendTicketLog(bot, interaction.guild, settings, 'ticket_unclaimed', updated, interaction.user.id);
  return interaction.reply(ephemeralComponents(`✅ Claim von Ticket #${ticket.ticket_id} wurde aufgehoben.`));
}

async function archiveTicketChannel(interaction, ticket, settings, category) {
  const archiveId = category.archive_category_id || settings.archive_category_id;
  const archive = archiveId ? interaction.guild.channels.cache.get(String(archiveId)) : null;
  if (archive?.type === ChannelType.GuildCategory) await interaction.channel.setParent(archive.id, { lockPermissions: false, reason: `Ticket #${ticket.ticket_id} archiviert` }).catch(() => null);
  await interaction.channel.permissionOverwrites.edit(String(ticket.owner_id), { SendMessages: false }, { reason: 'Ticket archiviert' }).catch(() => null);
  await interaction.channel.setName(`archiv-${ticket.ticket_id}-${safeChannelPart(category.key)}`.slice(0, 100), 'Ticket archiviert').catch(() => null);
}

async function closeTicket(bot, interaction, ticketId) {
  const lockKey = `${interaction.guild.id}:${ticketId}:close`;
  if (actionLocks.has(lockKey)) return respondEphemeral(interaction, '⏳ Dieses Ticket wird bereits verarbeitet.');
  actionLocks.add(lockKey);
  try {
    if (!interaction.deferred && !interaction.replied) await interaction.deferUpdate();
    const { ticket, settings, category } = await resolveTicketContext(bot, interaction, ticketId);
    if (!canClose(interaction.member, ticket, settings, category)) return respondEphemeral(interaction, '❌ Du darfst dieses Ticket nicht schließen.');
    if (!['open', 'claimed'].includes(ticket.status)) return respondEphemeral(interaction, '❌ Dieses Ticket wurde bereits geschlossen.');
    const transcript = await createTranscript(bot, interaction, ticket, settings, category);
    let updated = await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'closed', closed_by_id: String(interaction.user.id), closed_at: new Date(), transcript_url: transcript?.url || null, transcript_file_name: transcript?.fileName || null });
    await sendTicketLog(bot, interaction.guild, settings, 'ticket_closed', updated, interaction.user.id);
    const mode = category.close_mode || settings.close_mode || 'archive';
    const delay = Math.max(0, Math.min(86400, Number(category.close_delay_seconds ?? settings.close_delay_seconds ?? 5)));
    if (mode === 'archive') {
      await archiveTicketChannel(interaction, updated, settings, category);
      updated = await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'archived', archived_at: new Date() });
      await sendTicketLog(bot, interaction.guild, settings, 'ticket_archived', updated, interaction.user.id);
    } else if (mode === 'delete') {
      setTimeout(async () => {
        await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'deleted', deleted_at: new Date() }).catch(() => null);
        await interaction.channel.delete(`Ticket #${ticket.ticket_id} geschlossen`).catch(() => null);
      }, delay * 1000);
    } else {
      await interaction.channel.permissionOverwrites.edit(String(ticket.owner_id), { SendMessages: false }, { reason: 'Ticket geschlossen' }).catch(() => null);
      await refreshControlMessage(bot, interaction.guild, updated, category, settings);
    }
    return respondEphemeral(interaction, `✅ Ticket #${ticket.ticket_id} wurde geschlossen.${mode === 'delete' ? ` Löschung in ${delay}s.` : ''}`);
  } finally {
    actionLocks.delete(lockKey);
  }
}

async function archiveTicket(bot, interaction, ticketId) {
  const { ticket, settings, category } = await resolveTicketContext(bot, interaction, ticketId);
  if (!canManageTicketAction(interaction.member, settings, category, 'archive')) return interaction.reply(ephemeralComponents('❌ Du besitzt nicht die konfigurierte Archiv-Berechtigung.'));
  await archiveTicketChannel(interaction, ticket, settings, category);
  const updated = await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'archived', archived_at: new Date(), archived_by_id: String(interaction.user.id) });
  await sendTicketLog(bot, interaction.guild, settings, 'ticket_archived', updated, interaction.user.id);
  return interaction.reply(ephemeralComponents(`✅ Ticket #${ticket.ticket_id} wurde archiviert.`));
}

async function deleteTicket(bot, interaction, ticketId) {
  const { ticket, settings, category } = await resolveTicketContext(bot, interaction, ticketId);
  if (!canManageTicketAction(interaction.member, settings, category, 'delete')) return interaction.reply(ephemeralComponents('❌ Du besitzt nicht die konfigurierte Lösch-Berechtigung.'));
  await bot.db.updateTicketV2(interaction.guild.id, ticket.ticket_id, { status: 'deleted', deleted_at: new Date(), deleted_by_id: String(interaction.user.id) });
  await sendTicketLog(bot, interaction.guild, settings, 'ticket_deleted', ticket, interaction.user.id);
  await interaction.reply(ephemeralComponents(`✅ Ticket #${ticket.ticket_id} wird gelöscht.`));
  setTimeout(() => void interaction.channel.delete(`Ticket #${ticket.ticket_id} gelöscht`).catch(() => null), 1500);
}

const events = [{
  name: 'interactionCreate',
  async execute(bot, interaction) {
    if (!interaction.inGuild()) return;
    if (interaction.isStringSelectMenu() && interaction.customId === 'mf:t:create') {
      const category = await bot.db.getTicketCategoryV2(interaction.guild.id, interaction.values[0]);
      if (!category?.enabled) return interaction.reply(ephemeralComponents('❌ Diese Ticket-Kategorie ist nicht verfügbar.'));
      if (category.modal_enabled && (category.modal_questions || []).length) {
        const { modal } = buildModal(category);
        return interaction.showModal(modal);
      }
      return createTicketChannel(bot, interaction, category, []);
    }
    if (interaction.isModalSubmit() && interaction.customId.startsWith('mf:t:modal:')) {
      const key = interaction.customId.slice('mf:t:modal:'.length);
      const category = await bot.db.getTicketCategoryV2(interaction.guild.id, key);
      if (!category?.enabled) return interaction.reply(ephemeralComponents('❌ Diese Ticket-Kategorie ist nicht mehr aktiv.'));
      const questions = (category.modal_questions || []).filter(question => question.enabled !== false).sort((a, b) => Number(a.position || 0) - Number(b.position || 0)).slice(0, 5);
      const answers = questions.map((question, index) => ({ id: question.id || `q${index}`, label: question.label || question.question || `Frage ${index + 1}`, value: interaction.fields.getTextInputValue(`q${index}`) }));
      return createTicketChannel(bot, interaction, category, answers);
    }
    if (!interaction.isButton() || !interaction.customId.startsWith('mf:t:')) return;
    const parts = interaction.customId.split(':');
    const action = parts[2];
    const ticketId = Number(parts[3]);
    if (!Number.isFinite(ticketId)) return interaction.reply(ephemeralComponents('❌ Ungültige Ticket-ID.'));
    if (action === 'claim') return claimTicket(bot, interaction, ticketId);
    if (action === 'unclaim') return unclaimTicket(bot, interaction, ticketId);
    if (action === 'close') return interaction.reply(buildConfirmation(ticketId));
    if (action === 'close-cancel') return interaction.update(ephemeralComponents('Schließen abgebrochen.'));
    if (action === 'close-confirm') return closeTicket(bot, interaction, ticketId);
    if (action === 'archive') return archiveTicket(bot, interaction, ticketId);
    if (action === 'delete') return deleteTicket(bot, interaction, ticketId);
  },
}];

module.exports = {
  commands: [],
  events,
  buildTicketPanel,
  buildTicketControls,
  buildModal,
  sendOrUpdatePanel,
  createTicketChannel,
  createTranscript,
  claimTicket,
  unclaimTicket,
  closeTicket,
  archiveTicket,
  deleteTicket,
  isTicketAdmin,
  isTicketTeam,
};
