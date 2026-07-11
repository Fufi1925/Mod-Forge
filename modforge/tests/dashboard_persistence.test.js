process.env.ADMIN_SESSION_TOKEN = 'dashboard-persistence-admin';

const { Collection, ChannelType } = require('discord.js');
const { createNodeWeb } = require('../web/server');
const { DEFAULT_CONFIG } = require('../bot/config');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function createCollection() {
  return {
    createIndex: async () => 'index',
    findOne: async () => null,
    find: () => ({ sort() { return this; }, limit() { return this; }, async toArray() { return []; } }),
    insertOne: async () => ({ acknowledged: true, insertedId: 'test' }),
    updateOne: async () => ({ acknowledged: true, matchedCount: 1, modifiedCount: 1 }),
    updateMany: async () => ({ acknowledged: true, matchedCount: 1, modifiedCount: 1 }),
    deleteOne: async () => ({ acknowledged: true, deletedCount: 1 }),
    deleteMany: async () => ({ acknowledged: true, deletedCount: 1 }),
  };
}

async function request(base, path, method = 'GET', body = undefined) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: { cookie: 'modforge_admin=dashboard-persistence-admin', ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'manual',
  });
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { text }; }
  if (!response.ok) throw new Error(`${method} ${path}: HTTP ${response.status}: ${text}`);
  return data;
}

async function main() {
  let persistedConfig = clone(DEFAULT_CONFIG);
  let persistedWhitelist = { users: [], roles: [], channels: [], bypass_antispam: [], bypass_antinuke: [] };
  const sentMessages = [];
  const textChannel = {
    id: '400000000000000001', name: 'dashboard-tests', type: ChannelType.GuildText, position: 1, parentId: null,
    isThread: () => false, isTextBased: () => true,
    async send(payload) { sentMessages.push(payload); return { id: String(900000000000000000n + BigInt(sentMessages.length)), url: 'https://discord.test/message', ...payload }; },
    messages: { fetch: async () => null },
  };
  const everyone = { id: '100000000000000001', name: '@everyone', position: 0, permissions: { has: () => false, bitfield: 0n }, members: new Collection(), editable: false, hexColor: '#000000' };
  const guild = {
    id: '100000000000000001', name: 'Persistence Test', ownerId: '200000000000000001', memberCount: 0,
    createdAt: new Date(), createdTimestamp: Date.now(), premiumSubscriptionCount: 0, premiumTier: 0,
    iconURL: () => null,
    channels: { cache: new Collection([[textChannel.id, textChannel]]), async create(options) { const channel = { ...textChannel, id: String(500000000000000000n + BigInt(this.cache.size)), name: options.name }; this.cache.set(channel.id, channel); return channel; } },
    roles: { cache: new Collection([[everyone.id, everyone]]), everyone },
    members: { cache: new Collection(), me: { id: '300000000000000001', roles: { highest: everyone }, permissions: { has: () => true } } },
  };
  const collections = new Map();
  const database = {
    ready: true,
    db: { collection(name) { if (!collections.has(name)) collections.set(name, createCollection()); return collections.get(name); } },
    async connect() { return this; },
    async fetchConfig() { return clone(persistedConfig); },
    async setConfig(guildId, config) { persistedConfig = clone(config); },
    async fetchWhitelist() { return clone(persistedWhitelist); },
    async setWhitelist(guildId, whitelist) { persistedWhitelist = clone(whitelist); },
    async asave_config_version() {},
    async log_channels_snapshot() {},
    async arecord_activity() {},
  };
  const bot = {
    db: database, user: { displayAvatarURL: () => '' }, guilds: { cache: new Collection([[guild.id, guild]]) },
    ws: { ping: 1 }, shard: null, tracker: { lockdownActive: new Map() }, isReady: () => true,
  };
  const app = createNodeWeb(bot);
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await request(base, `/api/guild/${guild.id}/config`, 'POST', { _prefix: '?', _security_level: 3, _warn_thresholds_add: { 4: 'kick' } });
    if (persistedConfig.prefix !== '?' || persistedConfig.security_level !== 3 || persistedConfig.warn_thresholds['4'] !== 'kick') throw new Error('Config-Speicherung fehlgeschlagen');

    await request(base, `/api/guild/${guild.id}/automod`, 'POST', { action: 'add_word', value: 'testbadword' });
    if (!persistedConfig.automod.bad_words.includes('testbadword')) throw new Error('AutoMod-Wort wurde nicht gespeichert');

    await request(base, `/api/guild/${guild.id}/whitelist`, 'POST', { action: 'add', category: 'users', id: '222222222222222222' });
    if (!persistedWhitelist.users.includes('222222222222222222')) throw new Error('Whitelist-Add fehlgeschlagen');
    await request(base, `/api/guild/${guild.id}/whitelist`, 'POST', { action: 'del', category: 'users', id: '222222222222222222' });
    if (persistedWhitelist.users.length) throw new Error('Whitelist-Delete fehlgeschlagen');

    await request(base, `/api/guild/${guild.id}/verification/save`, 'POST', { enabled: true, verify_channel: textChannel.id, add_roles: ['333333333333333333'], embed_title: 'Persistenter Verify-Test', timer_enabled: true });
    if (persistedConfig.verify_system.verify_channel !== textChannel.id || persistedConfig.verify_system.add_roles[0] !== '333333333333333333') throw new Error('Verify-System wurde nicht korrekt gespeichert');
    if (persistedConfig.verify_extended.embed_title !== 'Persistenter Verify-Test' || !persistedConfig.verify_extended.timer_enabled) throw new Error('Verify-Extended wurde nicht korrekt gespeichert');

    await request(base, `/api/guild/${guild.id}/embed`, 'POST', { channel_id: textChannel.id, embed: { title: 'Dashboard Embed Test', description: 'Discord-Verbindung simuliert' } });
    if (!sentMessages.length) throw new Error('Embed wurde nicht an Discord-Kanal gesendet');

    const loaded = await request(base, `/api/guild/${guild.id}/config`);
    if (loaded.config.prefix !== '?' || loaded.config.automod.bad_words[0] !== 'testbadword') throw new Error('Gespeicherte Konfiguration konnte nach erneutem Laden nicht gelesen werden');
    console.log('Dashboard-Persistenztest erfolgreich: Config, AutoMod, Whitelist, Verify und Discord-Embed');
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
