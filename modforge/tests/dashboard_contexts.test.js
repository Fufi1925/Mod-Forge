const { Collection, ChannelType, PermissionFlagsBits } = require('discord.js');
const { createNodeWeb, pythonCompat } = require('../web/server');
const { pageContext, compareMemberViews, PAGE_MAP } = require('../web/dashboard');
const { DEFAULT_CONFIG } = require('../bot/config');

function render(app, template, context) {
  return new Promise((resolve, reject) => app.render(template, pythonCompat(context), (error, html) => error ? reject(error) : resolve(html)));
}

class EmptyCursor {
  sort() { return this; }
  limit() { return this; }
  async toArray() { return []; }
}

class EmptyMongoCollection {
  find() { return new EmptyCursor(); }
  async findOne() { return null; }
  async insertOne(document) { return { acknowledged: true, insertedId: document._id || 'test' }; }
  async updateOne() { return { acknowledged: true, matchedCount: 1, modifiedCount: 1 }; }
  async updateMany() { return { acknowledged: true, matchedCount: 1, modifiedCount: 1 }; }
  async deleteOne() { return { acknowledged: true, deletedCount: 1 }; }
  async createIndex() { return 'test-index'; }
}

function makeGuild() {
  const guild = {
    id: '100000000000000001', name: 'Context-Testserver', memberCount: 1, ownerId: '200000000000000001',
    createdAt: new Date('2024-01-01T00:00:00Z'), createdTimestamp: Date.parse('2024-01-01T00:00:00Z'),
    premiumSubscriptionCount: 0, premiumTier: 0,
    iconURL: () => null,
    roles: { cache: new Collection() }, channels: { cache: new Collection() }, members: { cache: new Collection() },
    async fetchOwner() { return this.members.cache.first(); },
  };
  const everyone = {
    id: guild.id, name: '@everyone', position: 0, hexColor: '#000000', editable: false,
    permissions: { has: () => false, bitfield: 0n }, members: new Collection(),
  };
  const moderator = {
    id: '300000000000000001', name: 'Moderator', position: 10, hexColor: '#60a5fa', editable: true,
    permissions: { has: bit => bit === PermissionFlagsBits.ManageMessages, bitfield: PermissionFlagsBits.ManageMessages }, members: new Collection(),
  };
  guild.roles.everyone = everyone;
  guild.roles.cache.set(everyone.id, everyone).set(moderator.id, moderator);
  const textChannel = {
    id: '400000000000000001', name: 'allgemein', type: ChannelType.GuildText, position: 1, parentId: null,
    isThread: () => false, isTextBased: () => true,
  };
  const voiceChannel = {
    id: '400000000000000002', name: 'Voice', type: ChannelType.GuildVoice, position: 2, parentId: null,
    isThread: () => false, isTextBased: () => false,
  };
  guild.channels.cache.set(textChannel.id, textChannel).set(voiceChannel.id, voiceChannel);
  const user = {
    id: '200000000000000001', tag: 'Tester#0001', username: 'Tester', bot: false, avatar: null,
    createdAt: new Date('2023-01-01T00:00:00Z'), createdTimestamp: Date.parse('2023-01-01T00:00:00Z'),
  };
  const roleCache = new Collection([[everyone.id, everyone], [moderator.id, moderator]]);
  roleCache.highest = moderator;
  const member = {
    id: user.id, user, displayName: 'Tester', nickname: null, joinedAt: new Date('2024-01-02T00:00:00Z'), joinedTimestamp: Date.parse('2024-01-02T00:00:00Z'),
    communicationDisabledUntilTimestamp: null, communicationDisabledUntil: null, presence: { status: 'online' },
    permissions: { has: bit => bit === PermissionFlagsBits.Administrator || bit === PermissionFlagsBits.ManageGuild },
    roles: { cache: roleCache, highest: moderator }, voice: { channelId: null, channel: null, mute: false },
    displayAvatarURL: () => 'https://cdn.discordapp.com/embed/avatars/0.png',
  };
  moderator.members.set(member.id, member);
  guild.members.cache.set(member.id, member);
  guild.members.me = member;
  guild.members.fetch = async id => id ? guild.members.cache.get(String(id)) || null : guild.members.cache;
  return guild;
}

async function main() {
  const orderedMembers = [
    { id: 'member-low', display_name: 'Low', bot: false, top_role_position: 1 },
    { id: 'normal-bot', display_name: 'Bot', bot: true, top_role_position: 0 },
    { id: 'member-high', display_name: 'High', bot: false, top_role_position: 99 },
    { id: 'modforge-bot', display_name: 'ModForge', bot: true, is_modforge_bot: true, top_role_position: 100 },
    { id: '1303627964734246944', display_name: 'Owner', bot: false, is_modforge_owner: true, top_role_position: 0 },
  ].sort(compareMemberViews).map(member => member.id);
  const expectedOrder = ['1303627964734246944', 'modforge-bot', 'normal-bot', 'member-high', 'member-low'];
  if (JSON.stringify(orderedMembers) !== JSON.stringify(expectedOrder)) throw new Error(`Member-Reihenfolge falsch: ${orderedMembers.join(', ')}`);
  const guild = makeGuild();
  const mongoCollections = new Map();
  const database = {
    db: { collection(name) { if (!mongoCollections.has(name)) mongoCollections.set(name, new EmptyMongoCollection()); return mongoCollections.get(name); } },
    async connect() { return this; },
    async fetchWhitelist() { return { users: [], roles: [], channels: [], bypass_antispam: [], bypass_antinuke: [] }; },
  };
  const bot = {
    db: database, guilds: { cache: new Collection([[guild.id, guild]]) }, user: null, ws: { ping: 1 }, shard: null,
    tracker: { lockdownActive: new Map() }, isReady: () => true,
  };
  const app = createNodeWeb(bot);
  const cfg = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  const dashboardUser = { id: '200000000000000001', username: 'Tester', avatar_url: 'https://cdn.discordapp.com/embed/avatars/0.png' };
  const pages = [...new Set(Object.values(PAGE_MAP))].filter(page => page !== 'user_risk').sort();
  const failures = [];
  for (const page of pages) {
    try {
      const context = await pageContext(bot, guild, cfg, dashboardUser, page);
      const html = await render(app, `dashboard/${page}.html`, context);
      if (!html.toLowerCase().includes('<!doctype html>')) throw new Error('Kein vollständiges HTML-Dokument');
      if (html.includes('{%') || html.includes('{{')) throw new Error('Nicht gerenderte Template-Syntax gefunden');
      console.log(`OK context dashboard/${page}.html (${html.length} Zeichen)`);
    } catch (error) {
      failures.push({ page, error });
      console.error(`FEHLER context dashboard/${page}.html: ${error.stack || error.message}`);
    }
  }
  if (failures.length) throw new Error(`${failures.length} von ${pages.length} Dashboard-Kontexten sind fehlgeschlagen`);
  console.log(`Dashboard-Kontext-Test erfolgreich: ${pages.length}/${pages.length}`);
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
