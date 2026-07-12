const { Collection, ChannelType, PermissionFlagsBits } = require('discord.js');
const { createTicketChannel, claimTicket, unclaimTicket, closeTicket } = require('../bot/cogs/tickets');

async function main() {
  const guildId = '100000000000000001'; const ownerId = '200000000000000001'; const staffId = '200000000000000002'; const teamRoleId = '300000000000000001';
  const everyone = { id: guildId };
  const discordCategory = { id: '400000000000000001', name: 'Tickets', type: ChannelType.GuildCategory };
  const supportRole = { id: teamRoleId, name: 'Support' };
  const channelMessages = [];
  let ticketRecord = null; let transcriptRecord = null;
  const ticketChannel = {
    id: '500000000000000001', name: 'support-owner-1', type: ChannelType.GuildText, parentId: discordCategory.id,
    isTextBased: () => true, permissionOverwrites: { async edit() {} }, async setParent() {}, async setName(value) { this.name = value; }, async delete() {},
    messages: { async fetch(arg) { if (typeof arg === 'string') return { id: arg, async edit(payload) { channelMessages.push(payload); } }; return new Collection(); } },
    async send(payload) { channelMessages.push(payload); return { id: String(600000000000000000n + BigInt(channelMessages.length)), channelId: this.id, attachments: new Collection(), ...payload }; },
  };
  const channels = new Collection([[discordCategory.id, discordCategory]]);
  channels.create = async options => { ticketChannel.name = options.name; channels.set(ticketChannel.id, ticketChannel); return ticketChannel; };
  const guild = { id: guildId, name: 'Ticket Flow', roles: { everyone, cache: new Collection([[teamRoleId, supportRole]]) }, channels: { cache: channels, create: channels.create }, members: { me: { id: '999999999999999999' } } };
  const settings = { enabled: true, max_open_global: 3, global_team_roles: [teamRoleId], global_admin_roles: [], claim_enabled: true, unclaim_enabled: true, owner_can_close: true, transcript_enabled: true, transcript_format: 'txt', close_mode: 'keep', close_delay_seconds: 0, permissions: { claim: 'team', close: 'team_or_owner', delete: 'admin', archive: 'admin', stats: 'team' } };
  const category = { key: 'support', name: 'Support', emoji: '🛠️', enabled: true, discord_category_id: discordCategory.id, team_roles: [], admin_roles: [], ping_enabled: false, channel_prefix: 'support', name_format: '{category}-{username}-{id}', max_open_per_user: 1, allow_multiple: false, modal_enabled: true, transcript_enabled: true };
  const logs = [];
  const bot = { db: {
    async getTicketSettingsV2() { return structuredClone(settings); }, async getTicketCategoryV2() { return structuredClone(category); }, async countOpenTicketsV2() { return ticketRecord && ['open','claimed'].includes(ticketRecord.status) ? 1 : 0; }, async nextTicketIdV2() { return 1; },
    async createTicketV2(id, value) { ticketRecord = { ...structuredClone(value), guild_id: id, created_at: new Date() }; return ticketRecord; }, async getTicketV2() { return structuredClone(ticketRecord); }, async updateTicketV2(id, ticketId, patch) { Object.assign(ticketRecord, structuredClone(patch)); return structuredClone(ticketRecord); },
    async logTicketV2(id, action, data) { logs.push({ action, ...data }); }, async asave_ticket_transcript(id, ticketId, data) { transcriptRecord = data; },
  } };
  const ownerRoles = new Collection(); const staffRoles = new Collection([[teamRoleId, supportRole]]);
  const ownerMember = { id: ownerId, roles: { cache: ownerRoles }, permissions: { has: () => false } };
  const staffMember = { id: staffId, roles: { cache: staffRoles }, permissions: { has: permission => permission === PermissionFlagsBits.ManageMessages } };
  const responses = [];
  const createInteraction = { guild, user: { id: ownerId, username: 'Owner', tag: 'Owner#0001' }, member: ownerMember, deferred: false, replied: false, async deferReply() { this.deferred = true; }, async editReply(payload) { responses.push(payload); }, async reply(payload) { this.replied = true; responses.push(payload); } };
  await createTicketChannel(bot, createInteraction, category, [{ label: 'Problem', value: 'Testproblem' }]);
  if (!ticketRecord || ticketRecord.channel_id !== ticketChannel.id || !channelMessages.length || 'embeds' in channelMessages[0]) throw new Error('Ticket-Erstellung oder Components-V2 Nachricht fehlgeschlagen');
  const staffInteraction = { guild, user: { id: staffId }, member: staffMember, deferred: false, replied: false, channel: ticketChannel, async reply(payload) { this.replied = true; responses.push(payload); } };
  await claimTicket(bot, staffInteraction, 1); if (ticketRecord.status !== 'claimed' || ticketRecord.claimer_id !== staffId) throw new Error('Claim fehlgeschlagen');
  staffInteraction.replied = false; await unclaimTicket(bot, staffInteraction, 1); if (ticketRecord.status !== 'open' || ticketRecord.claimer_id) throw new Error('Unclaim fehlgeschlagen');
  const closeInteraction = { guild, user: { id: ownerId }, member: ownerMember, channel: ticketChannel, deferred: false, replied: false, async deferUpdate() { this.deferred = true; }, async editReply(payload) { responses.push(payload); } };
  await closeTicket(bot, closeInteraction, 1); if (ticketRecord.status !== 'closed' || !transcriptRecord) throw new Error('Close oder Transcript fehlgeschlagen');
  for (const action of ['ticket_created','ticket_claimed','ticket_unclaimed','ticket_closed']) if (!logs.some(log => log.action === action)) throw new Error(`Audit-Log fehlt: ${action}`);
  console.log('Ticket-Flow-Test erfolgreich: Erstellen, DB, Claim, Unclaim, Close, Transcript und Audit-Logs');
}

main().catch(error => { console.error(error.stack || error.message); process.exit(1); });
