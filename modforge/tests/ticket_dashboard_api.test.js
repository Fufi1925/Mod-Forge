process.env.ADMIN_SESSION_TOKEN = 'ticket-admin-token';
process.env.SESSION_SECRET = 'ticket-dashboard-test-secret';

const { Collection, ChannelType } = require('discord.js');
const { createNodeWeb } = require('../web/server');

function mongoCollection() {
  return {
    async createIndex() {}, async findOne() { return null; }, async countDocuments() { return 0; }, async insertOne() { return { acknowledged: true }; }, async updateOne() { return { acknowledged: true }; }, async deleteOne() { return { deletedCount: 1 }; }, async deleteMany() { return { deletedCount: 0 }; },
    find() { return { sort() { return this; }, limit() { return this; }, async toArray() { return []; } }; },
  };
}

async function main() {
  const everyone = { id: '100000000000000001', name: '@everyone', position: 0, hexColor: '#000000', editable: false, permissions: { has: () => false, bitfield: 0n }, members: new Collection() };
  const teamRole = { id: '300000000000000001', name: 'Support', position: 5, hexColor: '#5865f2', editable: true, permissions: { has: () => false, bitfield: 0n }, members: new Collection() };
  const textChannel = { id: '400000000000000001', name: 'ticket-panel', type: ChannelType.GuildText, position: 1, parentId: null, isThread: () => false, isTextBased: () => true };
  const discordCategory = { id: '500000000000000001', name: 'Tickets', type: ChannelType.GuildCategory, position: 2, parentId: null, isThread: () => false, isTextBased: () => false };
  const guild = {
    id: everyone.id, name: 'Ticket API Test', ownerId: '200000000000000001', memberCount: 1, createdAt: new Date(), createdTimestamp: Date.now(), premiumSubscriptionCount: 0, premiumTier: 0, iconURL: () => null,
    roles: { cache: new Collection([[everyone.id, everyone], [teamRole.id, teamRole]]), everyone }, channels: { cache: new Collection([[textChannel.id, textChannel], [discordCategory.id, discordCategory]]) },
    members: { cache: new Collection(), me: { id: '999999999999999999', roles: { highest: teamRole }, permissions: { has: () => true } }, async fetch() { return null; } },
  };
  let settings = { enabled: true, panel_channel_id: null, panel_message_id: null, panel_title: 'Support', panel_description: 'Wähle', panel_placeholder: 'Kategorie', transcript_channel_id: null, log_channel_id: null, archive_category_id: null, global_team_roles: [], global_admin_roles: [], dashboard_admin_roles: [], max_open_global: 3, claim_enabled: true, unclaim_enabled: true, owner_can_close: true, transcript_enabled: true, transcript_format: 'html', close_mode: 'archive', close_delay_seconds: 5, permissions: { claim: 'team', close: 'team_or_owner', delete: 'admin', archive: 'admin', stats: 'admin' } };
  const categories = new Map(); const logs = [];
  const collections = new Map();
  const db = {
    ready: true, db: { collection(name) { if (!collections.has(name)) collections.set(name, mongoCollection()); return collections.get(name); } }, async connect() { return this; },
    async fetchConfig() { return {}; }, async getTicketSettingsV2() { return structuredClone(settings); }, async saveTicketSettingsV2(id, value) { settings = structuredClone(value); return structuredClone(settings); },
    async listTicketCategoriesV2(id, enabledOnly = false) { return [...categories.values()].filter(category => !enabledOnly || category.enabled).map(category => structuredClone(category)); },
    async getTicketCategoryV2(id, key) { return categories.has(key) ? structuredClone(categories.get(key)) : null; },
    async saveTicketCategoryV2(id, value) { categories.set(value.key, structuredClone(value)); return structuredClone(value); }, async deleteTicketCategoryV2(id, key) { categories.delete(key); return { deletedCount: 1 }; },
    async listTicketsV2() { return []; }, async listTicketLogsV2() { return structuredClone(logs); }, async logTicketV2(id, action, value) { logs.push({ action, ...structuredClone(value), created_at: new Date() }); },
    tickets_v2: { async countDocuments() { return 0; } },
  };
  const bot = { db, guilds: { cache: new Collection([[guild.id, guild]]) }, user: { id: '999999999999999999', displayAvatarURL: () => '' }, users: { async fetch() { return null; } }, ws: { ping: 1 }, shard: null, tracker: { lockdownActive: new Map() }, isReady: () => true };
  const app = createNodeWeb(bot); const server = app.listen(0, '127.0.0.1'); await new Promise(resolve => server.once('listening', resolve)); const base = `http://127.0.0.1:${server.address().port}`;
  const request = async (path, method = 'GET', body, csrf) => { const response = await fetch(base + path, { method, headers: { cookie: 'modforge_admin=ticket-admin-token', ...(body ? { 'content-type': 'application/json' } : {}), ...(csrf ? { 'x-csrf-token': csrf } : {}) }, body: body ? JSON.stringify(body) : undefined, redirect: 'manual' }); const text = await response.text(); let data; try { data = JSON.parse(text); } catch { data = text; } return { response, data, text }; };
  try {
    const page = await request(`/admin/server/${guild.id}/tickets`); if (page.response.status !== 200) throw new Error(`Ticket-Seite HTTP ${page.response.status}: ${page.text}`);
    const match = page.text.match(/CSRF='([a-f0-9]{64})'/); if (!match) throw new Error('CSRF-Token fehlt in Ticket-Seite'); const csrf = match[1];
    const denied = await request(`/api/guild/${guild.id}/tickets-v2/settings`, 'PUT', { panel_title: 'Denied' }, 'bad'); if (denied.response.status !== 403) throw new Error('Ungültiger CSRF-Token wurde nicht blockiert');
    const saved = await request(`/api/guild/${guild.id}/tickets-v2/settings`, 'PUT', { panel_channel_id: textChannel.id, panel_title: 'Neues Panel', panel_description: 'Beschreibung', panel_placeholder: 'Bitte wählen', global_team_roles: [teamRole.id], global_admin_roles: [], dashboard_admin_roles: [teamRole.id], max_open_global: 4, claim_enabled: true, unclaim_enabled: true, owner_can_close: true, transcript_enabled: true, transcript_format: 'html', close_mode: 'archive', close_delay_seconds: 10, permissions: { claim: 'team', close: 'team_or_owner', delete: 'admin', archive: 'admin', stats: 'team' } }, csrf);
    if (!saved.response.ok || settings.panel_title !== 'Neues Panel' || settings.global_team_roles[0] !== teamRole.id) throw new Error(`Ticket-Settings nicht gespeichert: ${saved.text}`);
    const created = await request(`/api/guild/${guild.id}/tickets-v2/categories`, 'POST', { key: 'support', name: 'Support', description: 'Hilfe', emoji: '🛠️', enabled: true, discord_category_id: discordCategory.id, team_roles: [teamRole.id], admin_roles: [], ping_role_id: teamRole.id, ping_enabled: true, ping_delete: true, ping_delay_seconds: 10, channel_prefix: 'support', name_format: '{category}-{username}-{id}', max_open_per_user: 1, allow_multiple: false, modal_enabled: true, modal_title: 'Support Anfrage', modal_questions: [{ id: 'topic', label: 'Worum geht es?', style: 'short', required: true, min_length: 3, max_length: 100 }], transcript_enabled: true, close_mode: 'archive', close_delay_seconds: 5 }, csrf);
    if (!created.response.ok || !categories.has('support') || categories.get('support').modal_questions.length !== 1) throw new Error(`Ticket-Kategorie nicht gespeichert: ${created.text}`);
    const state = await request(`/api/guild/${guild.id}/tickets-v2/state`); if (!state.response.ok || state.data.ticket_categories.length !== 1) throw new Error('Ticket-State API ist inkonsistent');
    console.log('Ticket-Dashboard-API-Test erfolgreich: Auth, CSRF, Settings, Rollen, Kategorie und Modal-Fragen');
  } finally { await new Promise(resolve => server.close(resolve)); }
}

main().catch(error => { console.error(error.stack || error.message); process.exit(1); });
