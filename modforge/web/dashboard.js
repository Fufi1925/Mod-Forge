const crypto = require('node:crypto');
const { ObjectId } = require('mongodb');
const { PermissionFlagsBits, ChannelType, ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');
const { BADGES, LOG_MODS, ACTIVITY, DEFAULT_CONFIG } = require('../bot/config');
const { collectBackupData, restoreFromBackup } = require('../bot/cogs/backup');

const PAGE_MAP = Object.freeze({
  '': 'overview', overview: 'overview', activity: 'activity_feed', activity_feed: 'activity_feed',
  appeals: 'appeals', audit: 'audit', automod: 'automod', autonick: 'autonick',
  autoresponse: 'autoresponse', backup: 'backup', badges: 'badges', beta: 'beta', cases: 'cases',
  design: 'design', embed: 'embed', livefeed: 'livefeed', logs: 'logs', members: 'members', modules: 'modules',
  roles: 'roles', security: 'security', settings: 'settings', 'staff-applications': 'staff_applications',
  staff_applications: 'staff_applications', stats: 'stats', templates: 'templates', tempvoice: 'tempvoice',
  tickets: 'tickets', verification: 'verification', warns: 'warns', welcome: 'welcome', whitelist: 'whitelist',
});

const LOG_CATEGORIES = Object.freeze({
  Moderation: ['moderation', 'warns', 'cases'], Sicherheit: ['antispam', 'antinuke', 'antiraid', 'antiscam', 'automod'],
  Server: ['members', 'messages', 'voice', 'channels', 'roles', 'webhooks'], Systeme: ['tickets', 'verify', 'welcome', 'backup', 'tempvoice'],
});

const MODULE_SECTIONS = Object.freeze([
  { key: 'anti_spam', label: 'Anti-Spam', icon: '⚡' }, { key: 'anti_nuke', label: 'Anti-Nuke', icon: '💥' },
  { key: 'anti_raid', label: 'Anti-Raid', icon: '🚨' }, { key: 'anti_scam', label: 'Anti-Scam', icon: '🎣' },
  { key: 'automod', label: 'AutoMod', icon: '🤖' }, { key: 'verify_system', label: 'Verifizierung', icon: '✅' },
  { key: 'welcome', label: 'Welcome', icon: '👋' }, { key: 'ticket_system', label: 'Tickets', icon: '🎫' },
  { key: 'tempvoice', label: 'TempVoice', icon: '🎤' }, { key: 'backup_system', label: 'Backups', icon: '💾' },
]);

const SECURITY_MODULE_DEFINITIONS = Object.freeze([
  { key: 'anti_spam', icon: '⚡', label: 'Anti-Spam', desc: 'Erkennt Spam, CAPS-Missbrauch, Emoji-Flooding und Duplikate.', color: '#f59e0b', params: [
    { key: 'msg_limit', label: 'Nachrichten-Limit', type: 'number', min: 2, max: 30, default: 5, unit: 'msgs' },
    { key: 'msg_window', label: 'Zeitfenster', type: 'number', min: 3, max: 60, default: 5, unit: 's' },
    { key: 'caps_pct', label: 'CAPS-Schwelle', type: 'number', min: 50, max: 100, default: 70, unit: '%' },
    { key: 'emoji_max', label: 'Max Emojis', type: 'number', min: 3, max: 50, default: 10, unit: '' },
    { key: 'duplicate_max', label: 'Max Duplikate', type: 'number', min: 1, max: 10, default: 3, unit: '' },
    { key: 'timeout_duration', label: 'Timeout-Dauer', type: 'number', min: 10, max: 86400, default: 300, unit: 's' },
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['warn', 'timeout', 'kick', 'ban'], default: 'timeout' },
  ] },
  { key: 'anti_nuke', icon: '💣', label: 'Anti-Nuke', desc: 'Schützt vor Massen-Bans, Channel-Löschungen und Rollen-Änderungen.', color: '#ef4444', params: [
    { key: 'threshold', label: 'Aktions-Schwelle', type: 'number', min: 2, max: 20, default: 5, unit: '' },
    { key: 'window', label: 'Zeitfenster', type: 'number', min: 5, max: 120, default: 10, unit: 's' },
    { key: 'remove_roles', label: 'Rollen entfernen', type: 'toggle', default: true },
    { key: 'auto_lockdown', label: 'Auto-Lockdown', type: 'toggle', default: true },
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['ban', 'kick', 'timeout'], default: 'ban' },
  ] },
  { key: 'anti_raid', icon: '🚨', label: 'Anti-Raid', desc: 'Erkennt Massen-Joins, filtert neue Accounts und aktiviert Lockdown.', color: '#f97316', params: [
    { key: 'join_threshold', label: 'Join-Schwelle', type: 'number', min: 3, max: 50, default: 10, unit: '/Zeitfenster' },
    { key: 'window', label: 'Zeitfenster', type: 'number', min: 5, max: 120, default: 10, unit: 's' },
    { key: 'min_account_age', label: 'Min. Account-Alter', type: 'number', min: 0, max: 90, default: 7, unit: 'Tage' },
    { key: 'auto_kick', label: 'Neue Accounts kicken', type: 'toggle', default: true },
    { key: 'lockdown', label: 'Auto-Lockdown', type: 'toggle', default: true },
    { key: 'suspicious_name_check', label: 'Verdächtige Namen prüfen', type: 'toggle', default: true },
  ] },
  { key: 'anti_mention', icon: '🔔', label: 'Anti-Mention', desc: 'Verhindert Mass-Mentions und @everyone/@here-Missbrauch.', color: '#a78bfa', params: [
    { key: 'mention_limit', label: 'Max Mentions', type: 'number', min: 2, max: 30, default: 5, unit: '' },
    { key: 'window', label: 'Zeitfenster', type: 'number', min: 3, max: 60, default: 10, unit: 's' },
    { key: 'timeout_duration', label: 'Timeout-Dauer', type: 'number', min: 10, max: 86400, default: 600, unit: 's' },
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['warn', 'timeout', 'kick', 'ban'], default: 'timeout' },
  ] },
  { key: 'anti_scam', icon: '🎣', label: 'Anti-Scam', desc: 'Erkennt Phishing-Links, Fake-Nitro und bekannte Scam-Domains.', color: '#06b6d4', params: [
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['warn', 'timeout', 'kick', 'ban'], default: 'ban' },
    { key: 'delete_msg', label: 'Nachricht löschen', type: 'toggle', default: true },
    { key: 'notify_user', label: 'User benachrichtigen', type: 'toggle', default: true },
  ] },
  { key: 'anti_webhook', icon: '🔌', label: 'Anti-Webhook', desc: 'Erkennt verdächtige Webhook-Erstellungen und Missbrauch.', color: '#8b5cf6', params: [
    { key: 'threshold', label: 'Schwelle', type: 'number', min: 1, max: 10, default: 3, unit: '' },
    { key: 'window', label: 'Zeitfenster', type: 'number', min: 5, max: 120, default: 30, unit: 's' },
  ] },
  { key: 'anti_ghost_ping', icon: '👻', label: 'Anti-Ghost-Ping', desc: 'Erkennt gelöschte Mentions und protokolliert oder bestraft sie.', color: '#64748b', params: [
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['log', 'warn', 'timeout'], default: 'warn' },
    { key: 'notify', label: 'Im Chat anzeigen', type: 'toggle', default: true },
  ] },
  { key: 'anti_url_shortener', icon: '🔗', label: 'Anti-URL-Shortener', desc: 'Blockiert bekannte URL-Shortener aus Sicherheitsgründen.', color: '#10b981', params: [
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['warn', 'timeout', 'kick', 'ban'], default: 'warn' },
    { key: 'delete_msg', label: 'Nachricht löschen', type: 'toggle', default: true },
  ] },
  { key: 'anti_vpn', icon: '🌐', label: 'Anti-VPN', desc: 'Behandelt verdächtige VPN- oder Proxy-Verbindungen.', color: '#0ea5e9', params: [
    { key: 'action', label: 'Aktion', type: 'select', options: ['log', 'kick', 'ban'], default: 'kick' },
  ] },
  { key: 'automod', icon: '🤖', label: 'AutoMod', desc: 'Wort-, Regex-, Link- und Invite-Filter mit eigenen Regeln.', color: '#f472b6', params: [
    { key: 'punishment', label: 'Bestrafung', type: 'select', options: ['warn', 'timeout', 'kick', 'ban'], default: 'warn' },
    { key: 'block_invites', label: 'Invites blockieren', type: 'toggle', default: true },
    { key: 'block_links', label: 'Links blockieren', type: 'toggle', default: false },
    { key: 'log_only', label: 'Nur loggen', type: 'toggle', default: false },
  ] },
]);

function plain(value) {
  if (value == null) return value;
  if (typeof value === 'bigint') return value.toString();
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value)) return value.map(plain);
  if (typeof value === 'object') {
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      if (key === '_id') out._id = String(item);
      else out[key] = plain(item);
    }
    return out;
  }
  return value;
}

function deepMerge(target, patch) {
  const out = plain(target || {});
  for (const [key, value] of Object.entries(patch || {})) {
    if (value && typeof value === 'object' && !Array.isArray(value) && out[key] && typeof out[key] === 'object' && !Array.isArray(out[key])) out[key] = deepMerge(out[key], value);
    else out[key] = plain(value);
  }
  return out;
}

function safeText(value, max = 1000) {
  return String(value ?? '').trim().slice(0, max);
}

function int(value, fallback = 0, min = Number.MIN_SAFE_INTEGER, max = Number.MAX_SAFE_INTEGER) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
}

function bool(value) {
  return value === true || value === 1 || value === '1' || String(value).toLowerCase() === 'true' || String(value).toLowerCase() === 'on';
}

function channelView(channel) {
  return { id: String(channel.id), name: channel.name, type: channel.type, position: channel.position || 0, category_id: channel.parentId || null };
}

function roleView(role, guild) {
  const danger = [];
  const checks = [['Administrator', PermissionFlagsBits.Administrator], ['ManageGuild', PermissionFlagsBits.ManageGuild], ['ManageRoles', PermissionFlagsBits.ManageRoles], ['ManageChannels', PermissionFlagsBits.ManageChannels], ['BanMembers', PermissionFlagsBits.BanMembers], ['KickMembers', PermissionFlagsBits.KickMembers], ['ManageWebhooks', PermissionFlagsBits.ManageWebhooks]];
  for (const [name, bit] of checks) if (role.permissions?.has(bit)) danger.push(name);
  const me = guild.members.me;
  return {
    id: String(role.id), name: role.name, color: role.hexColor === '#000000' ? '#64748b' : role.hexColor,
    pos: role.position, position: role.position, members: role.members?.size || 0, danger_perms: danger,
    can_manage: Boolean(me && role.editable), health: danger.length ? Math.max(10, 100 - danger.length * 14) : 100,
    risk: danger.length >= 3 ? 90 : danger.length ? 50 : 10,
  };
}

function guildView(guild) {
  const iconUrl = guild.iconURL?.({ size: 256 }) || null;
  const me = guild.members.me;
  return {
    id: String(guild.id), name: guild.name, member_count: guild.memberCount || guild.members.cache.size,
    icon: iconUrl ? { url: iconUrl } : null, owner_id: guild.ownerId,
    created_at: guild.createdAt?.toISOString?.() || null,
    me: {
      top_role: me?.roles?.highest ? { name: me.roles.highest.name, position: me.roles.highest.position } : null,
      guild_permissions: {
        administrator: Boolean(me?.permissions?.has(PermissionFlagsBits.Administrator)),
        manage_guild: Boolean(me?.permissions?.has(PermissionFlagsBits.ManageGuild)),
        manage_roles: Boolean(me?.permissions?.has(PermissionFlagsBits.ManageRoles)),
        manage_channels: Boolean(me?.permissions?.has(PermissionFlagsBits.ManageChannels)),
      },
    },
  };
}

async function collection(bot, name) {
  await bot.db.connect();
  return bot.db.db.collection(name);
}

async function findMany(bot, name, query, options = {}) {
  try {
    let cursor = (await collection(bot, name)).find(query || {});
    if (options.sort) cursor = cursor.sort(options.sort);
    if (options.limit) cursor = cursor.limit(options.limit);
    return (await cursor.toArray()).map(plain);
  } catch {
    return [];
  }
}

async function findOne(bot, name, query) {
  try { return plain(await (await collection(bot, name)).findOne(query)); } catch { return null; }
}

function guildQuery(guildId) {
  return { $or: [{ guild_id: String(guildId) }, { guild_id_str: String(guildId) }, { guild_id: Number(guildId) }] };
}

function documentIdQuery(id, fallbackField) {
  const variants = [];
  if (ObjectId.isValid(String(id))) variants.push({ _id: new ObjectId(String(id)) });
  if (fallbackField) variants.push({ [fallbackField]: String(id) });
  return variants.length === 1 ? variants[0] : { $or: variants };
}

function formatAgo(date) {
  const timestamp = new Date(date || Date.now()).getTime();
  const delta = Math.max(0, Date.now() - timestamp);
  if (delta < 60_000) return 'Gerade eben';
  if (delta < 3_600_000) return `Vor ${Math.floor(delta / 60_000)} Min.`;
  if (delta < 86_400_000) return `Vor ${Math.floor(delta / 3_600_000)} Std.`;
  return new Date(timestamp).toLocaleDateString('de-DE');
}

function riskForMember(member, cases = 0, warns = 0) {
  let score = Math.min(45, cases * 6 + warns * 8);
  const age = Date.now() - member.user.createdTimestamp;
  if (age < 86_400_000) score += 35;
  else if (age < 7 * 86_400_000) score += 20;
  if (!member.user.avatar) score += 8;
  if (member.communicationDisabledUntilTimestamp > Date.now()) score += 18;
  return Math.min(100, score);
}

function badgeCatalog(custom = []) {
  const builtins = Object.entries(BADGES).map(([id, badge]) => ({ id, ...plain(badge), custom: false }));
  const byId = new Map(builtins.map(item => [item.id, item]));
  for (const item of custom) byId.set(String(item.id || item.badge_id), { ...item, id: String(item.id || item.badge_id), custom: true });
  return [...byId.values()];
}

async function commonContext(bot, guild, cfg, user) {
  const channels = [...guild.channels.cache.values()].filter(ch => !ch.isThread?.()).map(channelView).sort((a, b) => a.position - b.position);
  const roles = [...guild.roles.cache.values()].filter(role => role.id !== guild.id).map(role => roleView(role, guild)).sort((a, b) => b.pos - a.pos);
  return {
    guild: guildView(guild), raw_guild: guild, cfg: plain(cfg), user: plain(user || { id: '0', username: 'Admin', avatar_url: '' }),
    dashboard_base: `/dashboard/${guild.id}`, web_bot_online: bot.isReady(), channels,
    text_channels: channels.filter(ch => [ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(ch.type)),
    voice_channels: channels.filter(ch => [ChannelType.GuildVoice, ChannelType.GuildStageVoice].includes(ch.type)),
    categories: channels.filter(ch => ch.type === ChannelType.GuildCategory), guild_roles: roles, roles,
  };
}

async function overviewContext(bot, guild, cfg) {
  const members = guild.members.cache;
  const humans = members.filter(m => !m.user.bot).size;
  const bots = members.filter(m => m.user.bot).size;
  const online = members.filter(m => m.presence?.status && m.presence.status !== 'offline').size;
  const activeMods = MODULE_SECTIONS.filter(item => cfg[item.key]?.enabled).map(item => item.label);
  const logCount = Object.values(cfg.log_channels || {}).filter(Boolean).length;
  let score = 20 + Math.min(20, logCount * 2) + activeMods.length * 6;
  if (cfg.security_level) score += int(cfg.security_level, 0, 0, 5) * 4;
  score = Math.min(100, score);
  const owner = await guild.fetchOwner().catch(() => null);
  return {
    humans, bots, online_count: online, in_timeout: members.filter(m => m.communicationDisabledUntilTimestamp > Date.now()).size,
    voice_active: members.filter(m => m.voice?.channelId).size, text_ch: guild.channels.cache.filter(c => c.type === ChannelType.GuildText).size,
    voice_ch: guild.channels.cache.filter(c => c.type === ChannelType.GuildVoice).size, roles_count: guild.roles.cache.size,
    boost_count: guild.premiumSubscriptionCount || 0, boost_tier: guild.premiumTier || 0, owner_name: owner?.user?.tag || owner?.displayName || 'Unbekannt',
    created: guild.createdAt?.toLocaleDateString('de-DE') || '—', prefix: cfg.prefix || '!', score,
    score_label: score >= 80 ? 'Sehr gut' : score >= 60 ? 'Gut' : score >= 40 ? 'Ausbaufähig' : 'Kritisch',
    score_color: score >= 80 ? '#4ade80' : score >= 60 ? '#60a5fa' : score >= 40 ? '#fbbf24' : '#f87171',
    sec_level: cfg.security_level || 0, active_mods: activeMods, active_count: activeMods.length,
    has_default_log: Boolean(cfg.log_channel || cfg.log_channels?.default), log_channels_count: logCount,
    activities: ACTIVITY.snapshot(12), recent_activities: ACTIVITY.snapshot(12),
  };
}

async function membersContext(bot, guild) {
  await guild.members.fetch().catch(() => null);
  const cases = await findMany(bot, 'cases', guildQuery(guild.id), { limit: 5000 });
  const badgeRows = await findMany(bot, 'badges', guildQuery(guild.id), { limit: 5000 });
  const customDefs = await findMany(bot, 'badge_defs', guildQuery(guild.id), { limit: 500 });
  const catalog = badgeCatalog(customDefs);
  const catalogById = new Map(catalog.map(b => [String(b.id), b]));
  const casesByUser = new Map();
  for (const item of cases) {
    const id = String(item.user_id || '');
    if (!casesByUser.has(id)) casesByUser.set(id, []);
    casesByUser.get(id).push(item);
  }
  const badgesByUser = new Map();
  for (const row of badgeRows) {
    const ids = row.badge_ids || row.badges || (row.badge_id ? [row.badge_id] : []);
    badgesByUser.set(String(row.user_id), ids.map(id => catalogById.get(String(id))).filter(Boolean));
  }
  const members = [...guild.members.cache.values()].map(member => {
    const ownCases = casesByUser.get(String(member.id)) || [];
    const warns = ownCases.filter(item => String(item.action).toLowerCase() === 'warn').length;
    const roles = [...member.roles.cache.values()].filter(role => role.id !== guild.id).sort((a, b) => b.position - a.position).map(role => ({ id: role.id, name: role.name, color: role.hexColor === '#000000' ? null : role.hexColor }));
    return {
      id: String(member.id), name: member.user.tag, display_name: member.displayName, nick: member.nickname || '', bot: member.user.bot,
      avatar: member.displayAvatarURL({ size: 256 }), banner_url: null, status: member.presence?.status || 'offline',
      top_role: roles[0]?.name || '', roles, roles_str: roles.map(role => role.name).join(' '),
      is_admin: member.permissions.has(PermissionFlagsBits.Administrator), timeout: member.communicationDisabledUntil?.toISOString?.() || '',
      voice_ch: member.voice?.channel?.name || '', voice_mute: Boolean(member.voice?.mute), joined: member.joinedAt?.toISOString?.(),
      created: member.user.createdAt?.toISOString?.(), warns, cases: ownCases.length, risk: riskForMember(member, ownCases.length, warns),
      badges: badgesByUser.get(String(member.id)) || [], badge_score: (badgesByUser.get(String(member.id)) || []).reduce((sum, badge) => sum + int(badge.level, 1), 0),
      tag: member.user.bot ? 'BOT' : '', tag_color: member.user.bot ? '#60a5fa' : '#94a3b8',
      all_perms: { administrator: member.permissions.has(PermissionFlagsBits.Administrator), manage_guild: member.permissions.has(PermissionFlagsBits.ManageGuild), manage_roles: member.permissions.has(PermissionFlagsBits.ManageRoles), moderate_members: member.permissions.has(PermissionFlagsBits.ModerateMembers) },
    };
  }).sort((a, b) => Number(a.bot) - Number(b.bot) || a.display_name.localeCompare(b.display_name, 'de'));
  return { members, badge_catalog: catalog };
}

async function casesContext(bot, guild) {
  const rows = await findMany(bot, 'cases', guildQuery(guild.id), { sort: { case_id: -1 }, limit: 500 });
  const cases = rows.map(item => ({ ...item, user_name: item.user_name || item.user_tag || String(item.user_id || 'Unbekannt'), mod_name: item.mod_name || item.moderator_tag || 'System / ModForge', ts_str: formatAgo(item.created_at || item.timestamp) }));
  const now = Date.now();
  const stats = { total: cases.length, warn: 0, ban: 0, kick: 0, timeout: 0 };
  for (const item of cases) { const action = String(item.action || '').toLowerCase(); if (stats[action] != null) stats[action] += 1; if (['mute', 'timeout'].includes(action)) stats.timeout += action === 'mute' ? 1 : 0; }
  return { cases, stats, cases_7d: cases.filter(c => now - new Date(c.created_at || 0).getTime() <= 7 * 864e5).length, cases_30d: cases.filter(c => now - new Date(c.created_at || 0).getTime() <= 30 * 864e5).length };
}

async function warnsContext(bot, guild, cfg) {
  const rows = (await casesContext(bot, guild)).cases.filter(item => String(item.action).toLowerCase() === 'warn');
  const counts = new Map();
  for (const row of rows) counts.set(String(row.user_id), (counts.get(String(row.user_id)) || 0) + 1);
  return {
    warns: rows, total_warns: rows.length, warns_7d: rows.filter(row => Date.now() - new Date(row.created_at || 0).getTime() <= 7 * 864e5).length,
    top_warned: [...counts.entries()].map(([id, count]) => ({ id, name: guild.members.cache.get(id)?.displayName || id, count })).sort((a, b) => b.count - a.count).slice(0, 10),
    decay: cfg.warn_decay || {}, thresholds: cfg.warn_thresholds || [{ count: 3, action: 'timeout' }, { count: 5, action: 'kick' }, { count: 7, action: 'ban' }],
    sorted_th: cfg.warn_thresholds || [{ count: 3, action: 'timeout' }, { count: 5, action: 'kick' }, { count: 7, action: 'ban' }],
  };
}

function automodEvaluate(cfg, text) {
  const am = cfg.automod || {};
  const hits = [];
  const lower = String(text || '').toLowerCase();
  for (const word of am.bad_words || []) if (lower.includes(String(word).toLowerCase())) hits.push({ label: `BadWord: ${word}`, action: am.punishment || 'delete', severity: 'high' });
  for (const domain of am.blocked_domains || []) if (lower.includes(String(domain).toLowerCase())) hits.push({ label: `Domain: ${domain}`, action: am.punishment || 'delete', severity: 'high' });
  if (am.invite_filter && /discord(?:app)?\.(?:gg|com\/invite)\//i.test(text)) hits.push({ label: 'Discord-Einladung', action: am.punishment || 'delete', severity: 'medium' });
  if (am.link_filter && /https?:\/\//i.test(text)) hits.push({ label: 'Link', action: am.punishment || 'delete', severity: 'medium' });
  for (const pattern of am.regex_patterns || []) {
    try { if (new RegExp(pattern, 'iu').test(text)) hits.push({ label: `Regex: ${pattern}`, action: am.punishment || 'delete', severity: 'high' }); } catch {}
  }
  return { hits, count: hits.length, would_delete: hits.length > 0, warnings: [] };
}

function automodContext(cfg) {
  const am = cfg.automod || {};
  const regexReport = (am.regex_patterns || []).map((pattern, index) => {
    try { new RegExp(pattern, 'iu'); return { index, pattern, level: 'ok', message: 'Gültig', danger: false }; }
    catch (error) { return { index, pattern, level: 'danger', message: error.message, danger: true }; }
  });
  return { am, regex_report: regexReport, stats: { bad_words: (am.bad_words || []).length, regex: regexReport.length, regex_bad: regexReport.filter(x => x.danger).length, regex_warn: 0, domains: (am.blocked_domains || []).length }, suggestions: [] };
}

async function backupRows(bot, guildId) {
  const rows = await findMany(bot, 'backups', guildQuery(guildId), { sort: { created_at: -1 }, limit: 100 });
  return rows.map(row => {
    const data = row.data || {};
    const size = Buffer.byteLength(JSON.stringify(data));
    const warnings = [];
    if (!(data.roles || []).length) warnings.push('Keine Rollen gespeichert');
    if (!(data.channels || []).length) warnings.push('Keine Kanäle gespeichert');
    return { ...row, id: String(row.backup_id || row.id || row._id), label: row.label || 'Backup', guild_name: row.guild_name || data.guild_name || '', roles: (data.roles || []).length, channels: (data.channels || []).length, categories: (data.channels || []).filter(ch => ch.type === ChannelType.GuildCategory).length, created_ts: new Date(row.created_at || Date.now()).getTime() / 1000, size_bytes: size, size_label: size < 1024 ? `${size} B` : `${(size / 1024).toFixed(1)} KB`, warnings, health_score: Math.max(20, 100 - warnings.length * 25), is_public: Boolean(row.is_public), has_password: Boolean(row.password_hash) };
  });
}

async function logsContext(guild, cfg) {
  const channels = [...guild.channels.cache.values()].filter(ch => [ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(ch.type)).map(channelView);
  const configured = cfg.log_channels || {};
  const categories = Object.entries(LOG_CATEGORIES).map(([name, keys]) => ({ name, mods: keys.map(key => ({ key, label: key.replace(/_/g, ' '), icon: '📝', desc: `Log-Kanal für ${key}` })) }));
  const categoryMap = Object.fromEntries(categories.map(category => [category.name, category.mods]));
  return { log_categories: categories, categories: categoryMap, default_channel: cfg.log_channel || configured.default || null, log_channels: configured, total_modules: LOG_MODS.length, total_configured: Object.values(configured).filter(Boolean).length, channels };
}

async function rolesContext(guild, cfg) {
  const roles = [...guild.roles.cache.values()].filter(r => r.id !== guild.id).map(r => roleView(r, guild)).sort((a, b) => b.pos - a.pos);
  const sticky = cfg.sticky_roles || [];
  const auto = cfg.auto_roles || [];
  const verify = [...(cfg.verify_system?.add_roles || []), ...(cfg.verify_system?.remove_roles || [])];
  return { roles, dangerous_roles: roles.filter(r => r.danger_perms.length), sticky_roles: sticky, auto_roles: auto, role_stats: { total: roles.length, dangerous: roles.filter(r => r.danger_perms.length).length, manageable: roles.filter(r => r.can_manage).length, sticky: sticky.length, auto: auto.length, verify: verify.length }, role_health: [], role_history: [] };
}

function securityContext(cfg, roles) {
  const modules = SECURITY_MODULE_DEFINITIONS.map(definition => {
    const moduleConfig = cfg[definition.key] || {};
    const params = definition.params.map(parameter => {
      const raw = moduleConfig[parameter.key] == null ? parameter.default : moduleConfig[parameter.key];
      const value = parameter.type === 'toggle' ? Boolean(raw) : parameter.type === 'number' ? Number(raw) : String(raw ?? '');
      return { ...parameter, value };
    });
    return { ...definition, enabled: Boolean(moduleConfig.enabled), params };
  });
  const active = modules.filter(item => item.enabled).length;
  const dangerousRoles = roles.filter(role => role.danger_perms?.length);
  const permissionChecks = [
    { label: 'Bot hat Administrator', ok: true, fix: 'Bot-Rechte prüfen' },
    { label: 'Gefährliche Rollen', ok: dangerousRoles.length === 0, fix: `${dangerousRoles.length} prüfen` },
    { label: 'Log-Kanal gesetzt', ok: Boolean(cfg.log_channel || Object.values(cfg.log_channels || {}).some(Boolean)), fix: 'Logs konfigurieren' },
  ];
  return { security_modules: modules, modules, active_count: active, total_count: modules.length, security_level: cfg.security_level || Math.min(3, Math.ceil(active / 3)), dangerous_roles: dangerousRoles, wl_count: 0, checks: permissionChecks, perm_checks: permissionChecks, presets: [] };
}

async function badgeContext(bot, guild, cfg) {
  const definitions = badgeCatalog(await findMany(bot, 'badge_defs', guildQuery(guild.id), { limit: 500 }));
  const grants = await findMany(bot, 'badges', guildQuery(guild.id), { limit: 5000 });
  const byId = new Map(definitions.map(item => [item.id, item]));
  const users = grants.map(row => ({ id: String(row.user_id), name: guild.members.cache.get(String(row.user_id))?.displayName || String(row.user_id), badges: (row.badge_ids || row.badges || []).map(id => byId.get(String(id))).filter(Boolean) })).filter(row => row.badges.length);
  return { definitions, users_with_badges: users, history: await findMany(bot, 'badge_history', guildQuery(guild.id), { sort: { created_at: -1 }, limit: 100 }), ba: cfg.badge_automation || {} };
}

async function ticketContext(bot, guild, cfg) {
  const transcripts = await findMany(bot, 'ticket_transcripts', guildQuery(guild.id), { sort: { updated_at: -1 }, limit: 100 });
  const cats = cfg.ticket_extended?.categories || [];
  return { tickets: transcripts, ticket_docs: transcripts.map(item => ({ created_at_iso: item.created_at_iso || item.created_at || item.updated_at || new Date().toISOString(), status: item.status || 'closed', transcript: item.transcript || '', ...item })), cats, ticket_categories: cats, te: cfg.ticket_extended || {}, ticket_stats: { total: transcripts.length, open: transcripts.filter(x => x.status === 'open').length, closed: transcripts.filter(x => x.status === 'closed').length, claimed: transcripts.filter(x => x.claimed_by).length } };
}

async function templateContext(bot, guild) {
  const all = await findMany(bot, 'community_templates', {}, { sort: { downloads: -1 }, limit: 200 });
  const normalized = all.map(t => {
    const data = t.data || {};
    const ratings = Array.isArray(t.ratings) ? t.ratings : [];
    const likes = Array.isArray(t.likes) ? t.likes.length : Number(t.likes || 0);
    return {
      rating_avg: ratings.length ? (ratings.reduce((sum, row) => sum + Number(row.stars || 0), 0) / ratings.length).toFixed(1) : '0.0',
      rating_count: ratings.length, likes, downloads: Number(t.downloads || 0), score: Number(t.score || 100), risk: t.risk || 'low',
      recommended: Array.isArray(t.recommended) ? t.recommended : [], ...t,
      id: String(t.template_id || t.id || t._id), roles: (data.roles || []).length, channels: (data.channels || []).length,
      categories: (data.channels || []).filter(channel => channel.type === ChannelType.GuildCategory).length,
      emojis: (data.emojis || []).length, is_mine: String(t.guild_id) === String(guild.id), guild_name: t.guild_name || 'Unbekannter Server',
    };
  });
  const categories = {};
  for (const item of normalized) {
    const key = item.category || 'general';
    if (!categories[key]) categories[key] = [];
    categories[key].push(item);
  }
  return { all_public: normalized, my_shared: normalized.filter(t => t.is_mine), categories, bot_ready: bot.isReady(), cat_labels: { general: 'Allgemein', gaming: 'Gaming', community: 'Community', support: 'Support', security: 'Security' } };
}

async function pageContext(bot, guild, cfg, user, page) {
  const common = await commonContext(bot, guild, cfg, user);
  let extra = {};
  if (page === 'overview') extra = await overviewContext(bot, guild, cfg);
  else if (page === 'members') extra = await membersContext(bot, guild);
  else if (page === 'cases') extra = await casesContext(bot, guild);
  else if (page === 'warns') extra = await warnsContext(bot, guild, cfg);
  else if (page === 'automod') extra = automodContext(cfg);
  else if (page === 'backup') { const backups = await backupRows(bot, guild.id); extra = { backups, auto_enabled: Boolean(cfg.backup_system?.auto_enabled), auto_interval: cfg.backup_system?.auto_interval_hours || 24, auto_max: cfg.backup_system?.auto_max_backups || 5, total_size_bytes: backups.reduce((sum, row) => sum + row.size_bytes, 0), last_backup_ts: backups[0]?.created_ts || null }; }
  else if (page === 'logs') extra = await logsContext(guild, cfg);
  else if (page === 'roles') extra = await rolesContext(guild, cfg);
  else if (page === 'security') { const rc = await rolesContext(guild, cfg); extra = { ...rc, ...securityContext(cfg, rc.roles) }; }
  else if (page === 'badges') extra = await badgeContext(bot, guild, cfg);
  else if (page === 'tickets') extra = await ticketContext(bot, guild, cfg);
  else if (page === 'templates') extra = await templateContext(bot, guild);
  else if (page === 'whitelist') {
    const whitelist = await bot.db.fetchWhitelist(guild.id);
    const definitions = [
      ['users', '👤', 'User', 'Vertrauenswürdige Mitglieder', '96,165,250'],
      ['roles', '🏷️', 'Rollen', 'Alle Mitglieder mit diesen Rollen', '167,139,250'],
      ['channels', '💬', 'Kanäle', 'Kanäle von Filtern ausnehmen', '34,211,238'],
      ['bypass_antispam', '⚡', 'Anti-Spam Bypass', 'User ohne Spam-Prüfung', '74,222,128'],
      ['bypass_antinuke', '💥', 'Anti-Nuke Bypass', 'User ohne Nuke-Prüfung', '251,146,60'],
    ];
    const cats = definitions.map(([key, icon, label, desc, color]) => ({
      key, icon, label, desc, color, placeholder: 'Discord-ID eingeben',
      entries: (whitelist[key] || []).map(id => ({ id: String(id), name: guild.members.cache.get(String(id))?.displayName || guild.roles.cache.get(String(id))?.name || guild.channels.cache.get(String(id))?.name || String(id) })),
    }));
    extra = { whitelist, cats, total_entries: cats.reduce((sum, category) => sum + category.entries.length, 0) };
  }
  else if (page === 'stats') {
    const cc = await casesContext(bot, guild);
    const members = [...guild.members.cache.values()];
    const humans = members.filter(member => !member.user.bot).length;
    const bots = members.filter(member => member.user.bot).length;
    const joins = members.filter(member => member.joinedTimestamp).sort((a, b) => a.joinedTimestamp - b.joinedTimestamp);
    const growthLabels = []; const growthData = [];
    for (const member of joins) { growthLabels.push(new Date(member.joinedTimestamp).toLocaleDateString('de-DE')); growthData.push(growthData.length + 1); }
    const modCounts = new Map();
    for (const item of cc.cases) { const id = String(item.mod_id || item.moderator_id || 'System'); modCounts.set(id, (modCounts.get(id) || 0) + 1); }
    extra = {
      ...cc, total_cases: cc.cases.length, cases_count: cc.cases.length, warns_count: cc.stats.warn,
      active_mods: MODULE_SECTIONS.filter(x => cfg[x.key]?.enabled).length, sec_level: cfg.security_level || 0,
      humans, bots, online: members.filter(member => member.presence?.status && member.presence.status !== 'offline').length,
      boosts: guild.premiumSubscriptionCount || 0, roles_count: guild.roles.cache.size,
      text_ch: guild.channels.cache.filter(channel => channel.type === ChannelType.GuildText).size,
      voice_ch: guild.channels.cache.filter(channel => channel.type === ChannelType.GuildVoice).size,
      log_channels_count: Object.values(cfg.log_channels || {}).filter(Boolean).length,
      server_created_ts: Math.floor((guild.createdTimestamp || 0) / 1000), growth_total: humans + bots,
      days_labels: [], days_data: [], growth_labels: growthLabels, growth_data: growthData,
      top_mods: [...modCounts.entries()].map(([id, count]) => ({ id, count })).sort((a, b) => b.count - a.count).slice(0, 10),
      action_stats: Object.entries(cc.stats).filter(([key]) => key !== 'total').map(([typ, count]) => ({ typ, count })),
    };
  }
  else if (page === 'livefeed' || page === 'activity_feed' || page === 'audit') {
    const stored = await findMany(bot, 'guild_events', guildQuery(guild.id), { sort: { created_at: -1 }, limit: 100 });
    const events = stored.map(item => ({ ...item, event_type: item.event_type || item.type || 'event', timestamp: item.timestamp || item.created_at || new Date().toISOString(), data: item.data || {} }));
    extra = { activities: ACTIVITY.snapshot(100), events, dangerous_roles: (await rolesContext(guild, cfg)).dangerous_roles };
  }
  else if (page === 'tempvoice') extra = { active_channels: await findMany(bot, 'tempvoice_channels', guildQuery(guild.id), { limit: 100 }), tv: cfg.tempvoice || cfg.temp_voice || {} };
  else if (page === 'verification') { const vs = cfg.verify_system || {}; extra = { vs, ve: cfg.verify_extended || {}, quiz: vs.quiz || [], panel_status: { channel_ok: Boolean(vs.channel_id || vs.verify_channel), reason: (vs.channel_id || vs.verify_channel) ? 'Kanal gesetzt' : 'Kein Kanal gesetzt' }, role_health: [], verify_stats: { enabled: Boolean(vs.enabled), add_roles: (vs.add_roles || []).length, remove_roles: (vs.remove_roles || []).length, quiz_questions: (vs.quiz || []).length, mode: vs.mode || 'one_click' } }; }
  else if (page === 'welcome') extra = { wc: cfg.welcome || {}, lv: cfg.leave || {}, wc_col: cfg.welcome?.embed_color || '#22c55e', lv_col: cfg.leave?.embed_color || '#ef4444', placeholder_warnings: [], role_health: [] };
  else if (page === 'autonick') { const settings = cfg.auto_nickname || {}; extra = { enabled: Boolean(settings.enabled), rules: (settings.rules || []).map(rule => ({ ...rule, role_name: rule.role_name || guild.roles.cache.get(String(rule.role_id))?.name || String(rule.role_id) })), exempt_roles: (settings.exempt_roles || []).map(item => typeof item === 'object' ? { id: String(item.id), name: item.name || guild.roles.cache.get(String(item.id))?.name || String(item.id) } : { id: String(item), name: guild.roles.cache.get(String(item))?.name || String(item) }) }; }
  else if (page === 'autoresponse') extra = { auto_responses: cfg.auto_responses || [] };
  else if (page === 'modules') extra = { sections: MODULE_SECTIONS };
  else if (page === 'embed') extra = {};
  else if (page === 'settings') extra = { setting_fields: [] };
  else if (page === 'beta' || page === 'appeals') { const appeals = await findMany(bot, 'appeals', guildQuery(guild.id), { sort: { created_at: -1 }, limit: 100 }); const applications = await findMany(bot, 'staff_applications', guildQuery(guild.id), { sort: { created_at: -1 }, limit: 100 }); extra = { appeals, applications, staff_applications: applications, appeals_count: appeals.length, appeals_pending: appeals.filter(x => x.status === 'pending').length, staff_count: applications.length, staff_pending: applications.filter(x => x.status === 'pending').length, beta_warning: { warning: 'Beta-Funktionen können sich ändern.' }, themes: { dark: '#111827', midnight: '#0f172a', forest: '#14532d', ocean: '#164e63' }, current_theme: cfg.dashboard_theme || 'dark', auto_dm: false, smart_timeout: false, risk_alerts: false }; }
  else if (page === 'staff_applications') extra = { applications: await findMany(bot, 'staff_applications', guildQuery(guild.id), { sort: { created_at: -1 }, limit: 100 }) };
  return { ...common, ...extra, active: page };
}

async function backupDocument(bot, guildId, id) {
  return findOne(bot, 'backups', { backup_id: String(id), ...guildQuery(guildId) });
}

function registerDashboard({ app, bot, render, getSession, canManage, forbidden, invite, isAdmin }) {
  async function dashboardAuth(req, res, next) {
    let session = await getSession(req, bot);
    const admin = Boolean(isAdmin?.(req));
    if (!session && admin) session = { user: { id: '0', username: 'Admin', avatar_url: bot.user?.displayAvatarURL?.({ size: 128 }) || '' }, guilds: [] };
    if (!session) return res.redirect('/login');
    const guildInfo = (session.guilds || []).find(g => String(g.id) === String(req.params.guildId));
    if (!admin && (!guildInfo || !canManage(guildInfo))) return forbidden(res, session.user);
    const guild = bot.guilds.cache.get(String(req.params.guildId));
    if (!guild) return admin ? res.status(404).send('Server nicht gefunden') : res.redirect(invite(req.params.guildId));
    req.dashboard = { session, guild, admin };
    return next();
  }

  app.get('/dashboard/:guildId/risk/:userId', dashboardAuth, async (req, res) => {
    const member = await req.dashboard.guild.members.fetch(req.params.userId).catch(() => null);
    if (!member) return res.status(404).send('Mitglied nicht gefunden');
    const cfg = await bot.db.fetchConfig(req.dashboard.guild.id);
    const cases = await findMany(bot, 'cases', { ...guildQuery(req.params.guildId), user_id: String(member.id) }, { sort: { case_id: -1 }, limit: 100 });
    const warns = cases.filter(item => String(item.action).toLowerCase() === 'warn').length;
    const base = await commonContext(bot, req.dashboard.guild, cfg, req.dashboard.session.user);
    const risk = { score: riskForMember(member, cases.length, warns), cases: cases.length, flags: [], last_punishment: cases[0]?.action || null };
    const avatarUrl = member.displayAvatarURL({ size: 256 });
    const context = { ...base, active: 'members', profile_user: { id: member.id, name: member.user.tag, username: member.user.tag, avatar_url: avatarUrl, avatar: { url: avatarUrl }, toString() { return this.name; } }, risk, account_age: Math.floor((Date.now() - member.user.createdTimestamp) / 864e5), join_age: member.joinedTimestamp ? Math.floor((Date.now() - member.joinedTimestamp) / 864e5) : 0 };
    context.user_profile = context.profile_user;
    context.risk_user = context.profile_user;
    return render(res, 'dashboard/user_risk.html', { ...context, user: context.profile_user, dashboard_user: req.dashboard.session.user }, true);
  });

  async function renderDashboardPage(req, res) {
    const page = PAGE_MAP[req.params.subpage || ''];
    if (!page) return res.status(404).send('Seite nicht gefunden');
    const cfg = await bot.db.fetchConfig(req.dashboard.guild.id);
    const context = await pageContext(bot, req.dashboard.guild, cfg, req.dashboard.session.user, page);
    context.dashboard_base = req.dashboard.admin ? `/admin/server/${req.dashboard.guild.id}` : `/dashboard/${req.dashboard.guild.id}`;
    return render(res, `dashboard/${page}.html`, context, true);
  }

  app.get(['/dashboard/:guildId', '/dashboard/:guildId/:subpage'], dashboardAuth, renderDashboardPage);
  app.get(['/admin/server/:guildId', '/admin/server/:guildId/:subpage'], dashboardAuth, renderDashboardPage);

  app.use('/api/guild/:guildId', dashboardAuth);

  app.get('/api/guild/:guildId/config', async (req, res) => res.json({ ok: true, config: await bot.db.fetchConfig(req.params.guildId) }));
  app.post('/api/guild/:guildId/config', async (req, res) => {
    const oldCfg = await bot.db.fetchConfig(req.params.guildId);
    await bot.db.asave_config_version(req.params.guildId, oldCfg, `dashboard:${req.dashboard.session.user.id}`).catch(() => null);
    const incoming = { ...(req.body || {}) };
    if (incoming._reset === true) {
      const resetConfig = plain(DEFAULT_CONFIG);
      await bot.db.setConfig(req.params.guildId, resetConfig);
      return res.json({ ok: true, reset: true, config: resetConfig });
    }
    delete incoming._reset;
    const patch = {};
    for (const [rawKey, value] of Object.entries(incoming)) {
      const key = rawKey.startsWith('_') ? rawKey.slice(1) : rawKey;
      if (!key || key === 'id') continue;
      patch[key] = value;
    }
    if (patch.temp_voice) {
      patch.tempvoice = deepMerge(patch.tempvoice || oldCfg.tempvoice || {}, patch.temp_voice);
      delete patch.temp_voice;
    }
    const cfg = deepMerge(oldCfg, patch);
    await bot.db.setConfig(req.params.guildId, cfg);
    res.json({ ok: true, config: cfg });
  });

  app.get('/api/guild/:guildId/activity', async (req, res) => {
    const stored = await findMany(bot, 'guild_events', guildQuery(req.params.guildId), { sort: { created_at: -1 }, limit: 100 });
    res.json({ ok: true, activities: [...ACTIVITY.snapshot(100), ...stored].slice(0, 100) });
  });

  app.post('/api/guild/:guildId/onboarding/wizard_seen', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.dashboard_onboarding = { ...(cfg.dashboard_onboarding || {}), wizard_popup_seen: true, wizard_popup_seen_at: new Date().toISOString() }; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/quick_setup', async (req, res) => {
    const profile = safeText(req.body.profile || 'balanced', 20);
    const cfg = await bot.db.fetchConfig(req.params.guildId);
    const presets = { relaxed: { limit: 8, timeout: 10 }, balanced: { limit: 5, timeout: 30 }, strict: { limit: 3, timeout: 60 } };
    const preset = presets[profile] || presets.balanced;
    cfg.security_level = profile === 'strict' ? 4 : profile === 'relaxed' ? 2 : 3;
    cfg.anti_spam = { ...(cfg.anti_spam || {}), enabled: true, msg_limit: preset.limit, timeout_minutes: preset.timeout };
    cfg.anti_scam = { ...(cfg.anti_scam || {}), enabled: true };
    cfg.anti_raid = { ...(cfg.anti_raid || {}), enabled: true };
    cfg.automod = { ...(cfg.automod || {}), enabled: true, invite_filter: profile !== 'relaxed', phishing_check: true };
    await bot.db.setConfig(req.params.guildId, cfg);
    res.json({ ok: true, score: 70 + cfg.security_level * 5, profile });
  });
  app.post('/api/guild/:guildId/emergency', async (req, res) => {
    const guild = req.dashboard.guild;
    let locked = 0; const errors = [];
    for (const channel of guild.channels.cache.values()) {
      if (![ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(channel.type)) continue;
      try { await channel.permissionOverwrites.edit(guild.roles.everyone, { SendMessages: false }, { reason: `Emergency Mode von ${req.dashboard.session.user.id}` }); locked += 1; }
      catch (error) { errors.push(`${channel.name}: ${error.message}`); }
    }
    bot.tracker.lockdownActive.set(guild.id, true);
    res.json({ ok: true, locked, errors });
  });

  app.post('/api/guild/:guildId/automod', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.automod = deepMerge(cfg.automod || {}, req.body || {}); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, automod: cfg.automod }); });
  app.post('/api/guild/:guildId/automod/test', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); res.json({ ok: true, result: automodEvaluate(cfg, safeText(req.body.text, 4000)) }); });
  app.get('/api/guild/:guildId/automod/export', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); res.attachment(`modforge-automod-${req.params.guildId}.json`).json({ automod: cfg.automod || {} }); });
  app.post('/api/guild/:guildId/automod/import', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.automod = req.body.mode === 'replace' ? plain(req.body.automod || {}) : deepMerge(cfg.automod || {}, req.body.automod || {}); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true }); });

  app.post('/api/guild/:guildId/autonick', async (req, res) => {
    const cfg = await bot.db.fetchConfig(req.params.guildId);
    const settings = deepMerge({ enabled: false, rules: [], exempt_roles: [] }, cfg.auto_nickname || {});
    const action = safeText(req.body.action, 30);
    if (action === 'toggle') settings.enabled = bool(req.body.enabled);
    else if (action === 'add') {
      const rule = { role_id: safeText(req.body.role_id, 30), role_name: safeText(req.body.role_name, 100), prefix: safeText(req.body.prefix, 16), suffix: safeText(req.body.suffix, 16) };
      if (!rule.role_id || (!rule.prefix && !rule.suffix)) return res.status(400).json({ ok: false, error: 'Rolle und Prefix oder Suffix werden benötigt' });
      settings.rules.push(rule);
      const role = req.dashboard.guild.roles.cache.get(rule.role_id);
      const exemptIds = new Set((settings.exempt_roles || []).map(item => String(item.id || item)));
      let applied = 0; let skipped = 0; let failed = 0;
      for (const member of role?.members?.values?.() || []) {
        if (member.user.bot || exemptIds.has(member.id) || member.manageable === false) { skipped += 1; continue; }
        const baseName = member.user.globalName || member.user.username || member.displayName;
        const nickname = `${rule.prefix}${baseName}${rule.suffix}`.slice(0, 32);
        try { await member.setNickname(nickname, `Auto-Nick Regel von ${req.dashboard.session.user.id}`); applied += 1; } catch { failed += 1; }
      }
      cfg.auto_nickname = settings; await bot.db.setConfig(req.params.guildId, cfg);
      return res.json({ ok: true, total: applied + skipped + failed, applied, skipped, failed, auto_nickname: settings });
    } else if (action === 'delete') settings.rules.splice(int(req.body.index, -1), 1);
    else if (action === 'reorder') {
      const order = Array.isArray(req.body.order) ? req.body.order.map(index => int(index, -1)) : [];
      if (order.length !== settings.rules.length || new Set(order).size !== settings.rules.length || order.some(index => index < 0 || index >= settings.rules.length)) return res.status(400).json({ ok: false, error: 'Ungültige Reihenfolge' });
      settings.rules = order.map(index => settings.rules[index]);
    } else if (action === 'add_exempt') {
      const id = safeText(req.body.role_id, 30); if (id && !(settings.exempt_roles || []).some(item => String(item.id || item) === id)) settings.exempt_roles.push({ id, name: safeText(req.body.role_name, 100) });
    } else if (action === 'remove_exempt') {
      const id = safeText(req.body.role_id, 30); settings.exempt_roles = (settings.exempt_roles || []).filter(item => String(item.id || item) !== id);
    } else return res.status(400).json({ ok: false, error: 'Unbekannte Auto-Nick-Aktion' });
    cfg.auto_nickname = settings; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, auto_nickname: settings });
  });
  app.post('/api/guild/:guildId/autoresponse', async (req, res) => {
    const cfg = await bot.db.fetchConfig(req.params.guildId); const action = req.body.action || 'save'; const list = [...(cfg.auto_responses || [])];
    if (action === 'delete' || action === 'del') list.splice(int(req.body.index, -1), 1);
    else if (action === 'toggle' && list[int(req.body.index, -1)]) list[int(req.body.index, -1)].enabled = !list[int(req.body.index, -1)].enabled;
    else { const item = { trigger: safeText(req.body.trigger, 200), response: safeText(req.body.response, 1800), enabled: req.body.enabled !== false }; const index = int(req.body.index, -1); if (index >= 0 && list[index]) list[index] = item; else list.push(item); }
    cfg.auto_responses = list; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, auto_responses: list });
  });

  app.get('/api/guild/:guildId/backup/list', async (req, res) => { const backups = await backupRows(bot, req.params.guildId); res.json({ ok: true, count: backups.length, backups }); });
  app.post('/api/guild/:guildId/backup/create', async (req, res) => { const data = await collectBackupData(req.dashboard.guild); const id = crypto.randomUUID().slice(0, 8); await (await collection(bot, 'backups')).insertOne({ backup_id: id, guild_id: String(req.params.guildId), guild_id_str: String(req.params.guildId), guild_name: req.dashboard.guild.name, data, label: safeText(req.body.label || 'Manuelles Backup', 100), created_by: String(req.dashboard.session.user.id), created_at: new Date() }); res.json({ ok: true, backup_id: id }); });
  app.get('/api/guild/:guildId/backup/:id/preview', async (req, res) => { const row = await backupDocument(bot, req.params.guildId, req.params.id); if (!row) return res.status(404).json({ ok: false, error: 'Backup nicht gefunden' }); const data = row.data || {}; const size = Buffer.byteLength(JSON.stringify(data)); res.json({ ok: true, preview: { id: req.params.id, risk: 'low', warnings: [], summary: { roles_new: (data.roles || []).length, channels_new: (data.channels || []).length, categories_total: (data.channels || []).filter(c => c.type === ChannelType.GuildCategory).length, emojis_total: (data.emojis || []).length }, meta: { label: row.label || 'Backup', health_score: 100, size_label: `${(size / 1024).toFixed(1)} KB` } } }); });
  app.get('/api/guild/:guildId/backup/:id/download', async (req, res) => { const row = await backupDocument(bot, req.params.guildId, req.params.id); if (!row) return res.status(404).json({ ok: false, error: 'Backup nicht gefunden' }); res.attachment(`modforge-backup-${req.params.id}.json`).json(row); });
  app.post('/api/guild/:guildId/backup/:id/restore', async (req, res) => { const row = await backupDocument(bot, req.params.guildId, req.params.id); if (!row) return res.status(404).json({ ok: false, error: 'Backup nicht gefunden' }); const report = await restoreFromBackup(req.dashboard.guild, row.data || {}); res.json({ ok: true, report }); });
  app.post('/api/guild/:guildId/backup/:id/delete', async (req, res) => { const result = await (await collection(bot, 'backups')).deleteOne({ backup_id: String(req.params.id), ...guildQuery(req.params.guildId) }); res.json({ ok: result.deletedCount > 0 }); });

  app.get('/api/guild/:guildId/badges/definitions', async (req, res) => res.json({ ok: true, definitions: badgeCatalog(await findMany(bot, 'badge_defs', guildQuery(req.params.guildId), { limit: 500 })) }));
  app.post('/api/guild/:guildId/badges/definitions', async (req, res) => { const id = safeText(req.body.id || req.body.badge_id, 48).replace(/[^a-zA-Z0-9_-]/g, ''); if (!id) return res.status(400).json({ ok: false, error: 'Ungültige Badge-ID' }); const doc = { guild_id: String(req.params.guildId), id, name: safeText(req.body.name, 64), emoji: safeText(req.body.emoji || '🏷️', 16), color: safeText(req.body.color || '#94a3b8', 16), desc: safeText(req.body.desc, 256), style: safeText(req.body.style || 'solid', 24), rarity: safeText(req.body.rarity || 'common', 24), category: safeText(req.body.category || 'custom', 32), level: int(req.body.level, 1, 1, 100) }; await (await collection(bot, 'badge_defs')).updateOne({ guild_id: String(req.params.guildId), id }, { $set: doc }, { upsert: true }); res.json({ ok: true, badge: doc }); });
  app.delete('/api/guild/:guildId/badges/definitions/:id', async (req, res) => { await (await collection(bot, 'badge_defs')).deleteOne({ guild_id: String(req.params.guildId), id: req.params.id }); await (await collection(bot, 'badges')).updateMany(guildQuery(req.params.guildId), { $pull: { badge_ids: req.params.id, badges: req.params.id } }); res.json({ ok: true }); });
  app.get('/api/guild/:guildId/member/:memberId/badges', async (req, res) => { const row = await findOne(bot, 'badges', { guild_id: String(req.params.guildId), user_id: String(req.params.memberId) }) || {}; const all = badgeCatalog(await findMany(bot, 'badge_defs', guildQuery(req.params.guildId), { limit: 500 })); const map = new Map(all.map(b => [b.id, b])); res.json({ ok: true, badges: (row.badge_ids || row.badges || []).map(id => map.get(String(id))).filter(Boolean), all_badges: all }); });
  app.post('/api/guild/:guildId/member/:memberId/badges', async (req, res) => { const badgeId = safeText(req.body.badge_id, 48); const query = { guild_id: String(req.params.guildId), user_id: String(req.params.memberId) }; const row = await findOne(bot, 'badges', query) || {}; if ((row.badge_ids || []).includes(badgeId)) return res.json({ ok: false, duplicate: true }); await (await collection(bot, 'badges')).updateOne(query, { $setOnInsert: query, $push: { badge_ids: badgeId }, $set: { updated_at: new Date() } }, { upsert: true }); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/member/:memberId/badges/order', async (req, res) => { const ids = Array.isArray(req.body.badge_ids) ? req.body.badge_ids.map(x => safeText(x, 48)).slice(0, 100) : []; await (await collection(bot, 'badges')).updateOne({ guild_id: String(req.params.guildId), user_id: String(req.params.memberId) }, { $set: { badge_ids: ids, updated_at: new Date() } }, { upsert: true }); res.json({ ok: true }); });
  app.delete('/api/guild/:guildId/member/:memberId/badges/:badgeId', async (req, res) => { await (await collection(bot, 'badges')).updateOne({ guild_id: String(req.params.guildId), user_id: String(req.params.memberId) }, { $pull: { badge_ids: req.params.badgeId, badges: req.params.badgeId } }); res.json({ ok: true }); });

  app.get('/api/guild/:guildId/member/:memberId/details', async (req, res) => { const notes = await findMany(bot, 'notes', { ...guildQuery(req.params.guildId), user_id: String(req.params.memberId) }, { sort: { created_at: -1 }, limit: 100 }); const cases = await findMany(bot, 'cases', { ...guildQuery(req.params.guildId), user_id: String(req.params.memberId) }, { sort: { case_id: -1 }, limit: 100 }); res.json({ ok: true, notes, cases }); });
  app.post('/api/guild/:guildId/member/:memberId/note', async (req, res) => { const text = safeText(req.body.text, 1000); if (!text) return res.status(400).json({ ok: false, error: 'Notiz ist leer' }); await (await collection(bot, 'notes')).insertOne({ guild_id: String(req.params.guildId), user_id: String(req.params.memberId), mod_id: String(req.dashboard.session.user.id), text, priority: safeText(req.body.priority || 'medium', 20), pinned: bool(req.body.pinned), created_at: new Date() }); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/member/:memberId/action', async (req, res) => { const guild = req.dashboard.guild; const member = await guild.members.fetch(req.params.memberId).catch(() => null); const action = safeText(req.body.action, 20); const reason = safeText(req.body.reason || `Dashboard-Aktion von ${req.dashboard.session.user.id}`, 400); try { if (action === 'ban') await guild.members.ban(req.params.memberId, { reason }); else if (action === 'kick') { if (!member) throw new Error('Mitglied nicht gefunden'); await member.kick(reason); } else if (action === 'timeout') { if (!member) throw new Error('Mitglied nicht gefunden'); await member.timeout(int(req.body.duration, 3600, 1, 2419200) * 1000, reason); } else if (action === 'untimeout') { if (!member) throw new Error('Mitglied nicht gefunden'); await member.timeout(null, reason); } else if (action === 'nick') { if (!member) throw new Error('Mitglied nicht gefunden'); await member.setNickname(safeText(req.body.nick, 32) || null, reason); } else if (action === 'add_role' || action === 'remove_role') { if (!member) throw new Error('Mitglied nicht gefunden'); const role = guild.roles.cache.get(String(req.body.role_id)); if (!role) throw new Error('Rolle nicht gefunden'); if (!role.editable) throw new Error('Der Bot kann diese Rolle wegen der Rollen-Hierarchie nicht verwalten'); if (action === 'add_role') await member.roles.add(role, reason); else await member.roles.remove(role, reason); } else throw new Error('Unbekannte Aktion'); await bot.createCase(guild, action, member || { id: req.params.memberId, tag: req.params.memberId }, { id: req.dashboard.session.user.id, tag: req.dashboard.session.user.username }, reason); res.json({ ok: true, action }); } catch (error) { res.status(400).json({ ok: false, error: error.message }); } });

  app.get('/api/guild/:guildId/cases/export', async (req, res) => { const cases = (await casesContext(bot, req.dashboard.guild)).cases; if (req.query.format === 'html') { res.attachment(`cases-${req.params.guildId}.html`).type('html').send(`<!doctype html><meta charset="utf-8"><title>Cases</title><table><tr><th>ID</th><th>User</th><th>Aktion</th><th>Grund</th></tr>${cases.map(c => `<tr><td>${c.case_id}</td><td>${safeText(c.user_id)}</td><td>${safeText(c.action)}</td><td>${safeText(c.reason)}</td></tr>`).join('')}</table>`); } else res.attachment(`cases-${req.params.guildId}.json`).json(cases); });
  app.post('/api/guild/:guildId/case/:caseId/reason', async (req, res) => { await bot.db.updateCase(req.params.guildId, req.params.caseId, { reason: safeText(req.body.reason, 1000), updated_at: new Date() }); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/case/:caseId/evidence', async (req, res) => { await bot.db.aadd_case_evidence(req.params.guildId, req.params.caseId, { text: safeText(req.body.evidence || req.body.text, 2000), added_by: String(req.dashboard.session.user.id), created_at: new Date() }); res.json({ ok: true }); });
  app.delete('/api/guild/:guildId/case/:caseId', async (req, res) => { await (await collection(bot, 'cases')).deleteOne({ guild_id: Number(req.params.guildId), case_id: Number(req.params.caseId) }); res.json({ ok: true }); });

  app.post('/api/guild/:guildId/whitelist', async (req, res) => { const whitelist = await bot.db.fetchWhitelist(req.params.guildId); const category = safeText(req.body.category || req.body.type || 'users', 40); if (!Object.prototype.hasOwnProperty.call(whitelist, category) || !Array.isArray(whitelist[category])) return res.status(400).json({ ok: false, error: 'Unbekannte Kategorie' }); const id = safeText(req.body.id, 30); if (req.body.action === 'remove') whitelist[category] = whitelist[category].filter(item => String(item) !== id); else if (id && !whitelist[category].includes(id)) whitelist[category].push(id); await bot.db.setWhitelist(req.params.guildId, whitelist); res.json({ ok: true, whitelist }); });

  app.post('/api/guild/:guildId/roles', async (req, res) => {
    const guild = req.dashboard.guild; const action = safeText(req.body.action, 30); const roleId = safeText(req.body.role_id, 30); const role = guild.roles.cache.get(roleId);
    try {
      if (['add_auto', 'del_auto', 'add_sticky', 'del_sticky', 'add_verify', 'del_verify', 'add_unverify', 'del_unverify'].includes(action)) {
        if (!role) throw new Error('Rolle nicht gefunden');
        const cfg = await bot.db.fetchConfig(req.params.guildId);
        const addOrRemove = (items, add) => add ? [...new Set([...(items || []).map(String), roleId])] : (items || []).map(String).filter(id => id !== roleId);
        if (action.endsWith('_auto')) cfg.auto_roles = addOrRemove(cfg.auto_roles, action.startsWith('add_'));
        else if (action.endsWith('_sticky')) cfg.sticky_roles = addOrRemove(cfg.sticky_roles, action.startsWith('add_'));
        else {
          cfg.verify_system = cfg.verify_system || {};
          const field = action.endsWith('_unverify') ? 'remove_roles' : 'add_roles';
          cfg.verify_system[field] = addOrRemove(cfg.verify_system[field], action.startsWith('add_'));
        }
        await bot.db.setConfig(req.params.guildId, cfg);
        return res.json({ ok: true, action, role_id: roleId });
      }
      if (action === 'create') { const created = await guild.roles.create({ name: safeText(req.body.name || 'Neue Rolle', 100), color: safeText(req.body.color || '#64748b', 16), reason: `Dashboard von ${req.dashboard.session.user.id}` }); return res.json({ ok: true, role_id: created.id }); }
      if (!role) throw new Error('Rolle nicht gefunden');
      if (action === 'delete') await role.delete(`Dashboard von ${req.dashboard.session.user.id}`);
      else if (action === 'edit') await role.edit({ name: safeText(req.body.name || role.name, 100), color: safeText(req.body.color || role.hexColor, 16) }, `Dashboard von ${req.dashboard.session.user.id}`);
      else throw new Error('Unbekannte Aktion');
      res.json({ ok: true });
    } catch (error) { res.status(400).json({ ok: false, error: error.message }); }
  });
  app.get('/api/guild/:guildId/roles/preview/:id', async (req, res) => { const role = req.dashboard.guild.roles.cache.get(String(req.params.id)); if (!role) return res.status(404).json({ ok: false, error: 'Rolle nicht gefunden' }); res.json({ ok: true, role: roleView(role, req.dashboard.guild), members: [...role.members.values()].slice(0, 100).map(m => ({ id: m.id, name: m.displayName, avatar: m.displayAvatarURL({ size: 64 }) })) }); });

  app.get('/api/guild/:guildId/logs/health', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const channels = cfg.log_channels || {}; const health = Object.entries(channels).map(([module, id]) => { const channel = req.dashboard.guild.channels.cache.get(String(id)); return { module, channel_id: id, ok: Boolean(channel?.isTextBased?.()), reason: channel ? 'OK' : 'Kanal nicht gefunden' }; }); res.json({ ok: true, health }); });
  app.post('/api/guild/:guildId/logs/test', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const module = safeText(req.body.module || 'default', 40); const id = req.body.channel_id || cfg.log_channels?.[module] || cfg.log_channel; const channel = req.dashboard.guild.channels.cache.get(String(id)); if (!channel?.isTextBased?.()) return res.status(400).json({ ok: false, error: 'Log-Kanal nicht gefunden' }); const message = await channel.send({ content: `✅ ModForge Test-Log · Modul **${module}** · ausgelöst von <@${req.dashboard.session.user.id}>` }); res.json({ ok: true, message_id: message.id }); });
  app.post('/api/guild/:guildId/logs/preset', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const channelId = safeText(req.body.channel_id, 30); const preset = safeText(req.body.preset || 'all', 20); const keys = preset === 'security' ? LOG_CATEGORIES.Sicherheit : preset === 'moderation' ? LOG_CATEGORIES.Moderation : LOG_MODS; cfg.log_channels = { ...(cfg.log_channels || {}) }; for (const key of keys) cfg.log_channels[key] = channelId; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, configured: keys.length }); });
  app.post('/api/guild/:guildId/logs/repair', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const valid = {}; for (const [key, id] of Object.entries(cfg.log_channels || {})) if (req.dashboard.guild.channels.cache.has(String(id))) valid[key] = id; cfg.log_channels = valid; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, removed: Object.keys(cfg.log_channels || {}).length - Object.keys(valid).length }); });

  app.post('/api/guild/:guildId/verification/save', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.verify_system = deepMerge(cfg.verify_system || {}, req.body || {}); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/verification/quiz', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.verify_system = cfg.verify_system || {}; cfg.verify_system.quiz = cfg.verify_system.quiz || []; cfg.verify_system.quiz.push({ question: safeText(req.body.question, 300), answer: safeText(req.body.answer, 300) }); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true }); });
  app.delete('/api/guild/:guildId/verification/quiz', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.verify_system = cfg.verify_system || {}; cfg.verify_system.quiz = cfg.verify_system.quiz || []; cfg.verify_system.quiz.splice(int(req.body.index, -1), 1); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/verification/panel', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const vs = cfg.verify_system || {}; const channel = req.dashboard.guild.channels.cache.get(String(req.body.channel_id || vs.channel_id || vs.verify_channel)); if (!channel?.isTextBased?.()) return res.status(400).json({ ok: false, error: 'Verify-Kanal nicht gefunden' }); const row = new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('modforge:verify').setLabel(vs.button_label || 'Verifizieren').setEmoji(vs.button_emoji || '✅').setStyle(ButtonStyle.Success)); let message = req.body.update && vs.message_id ? await channel.messages.fetch(vs.message_id).catch(() => null) : null; const payload = { content: `## ${vs.embed_title || '✅ Verifizierung'}\n${vs.embed_description || 'Klicke den Button, um dich zu verifizieren.'}`, components: [row] }; if (message) await message.edit(payload); else message = await channel.send(payload); cfg.verify_system = { ...vs, channel_id: channel.id, verify_channel: channel.id, message_id: message.id, enabled: true }; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, message_id: message.id }); });
  app.post('/api/guild/:guildId/verification/test', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const vs = cfg.verify_system || {}; const channel = req.dashboard.guild.channels.cache.get(String(vs.channel_id || vs.verify_channel)); const roleIds = [...(vs.add_roles || []).map(id => ({ id, kind: 'add' })), ...(vs.remove_roles || []).map(id => ({ id, kind: 'remove' }))]; res.json({ ok: true, panel_status: { channel_ok: Boolean(channel), reason: channel ? `#${channel.name}` : 'Kanal fehlt' }, role_health: roleIds.map(item => { const role = req.dashboard.guild.roles.cache.get(String(item.id)); return { ...item, name: role?.name || item.id, ok: Boolean(role?.editable), reason: role ? (role.editable ? 'OK' : 'Nicht verwaltbar') : 'Nicht gefunden' }; }) }); });

  app.post('/api/guild/:guildId/welcome/test', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const mode = req.body.mode === 'leave' ? cfg.leave || {} : cfg.welcome || {}; const description = safeText(mode.embed_description || mode.message || `Test für ${req.dashboard.guild.name}`, 1800).replaceAll('{server}', req.dashboard.guild.name).replaceAll('{user}', `<@${req.dashboard.session.user.id}>`); try { if (req.body.target === 'dm') { const user = await bot.users.fetch(req.dashboard.session.user.id); await user.send(description); } else { const channel = req.dashboard.guild.channels.cache.get(String(req.body.channel_id || mode.channel_id)); if (!channel?.isTextBased?.()) throw new Error('Kanal nicht gefunden'); await channel.send(description); } res.json({ ok: true }); } catch (error) { res.status(400).json({ ok: false, error: error.message }); } });

  app.post('/api/guild/:guildId/tempvoice/panel', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const tv = cfg.tempvoice || cfg.temp_voice || {}; const channel = req.dashboard.guild.channels.cache.get(String(req.body.channel_id || req.body.panel_channel_id || tv.panel_channel_id)); if (!channel?.isTextBased?.()) return res.status(400).json({ ok: false, error: 'Panel-Kanal nicht gefunden' }); const message = await channel.send({ content: '## 🎤 TempVoice\nBetritt den Join-Channel, um einen temporären Voice-Kanal zu erstellen.' }); cfg.tempvoice = { ...tv, panel_channel_id: channel.id, panel_message_id: message.id, enabled: true }; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, message_id: message.id }); });
  app.get('/api/guild/:guildId/tempvoice/health', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const tv = cfg.tempvoice || cfg.temp_voice || {}; const join = req.dashboard.guild.channels.cache.get(String(tv.join_channel_id || tv.hub_channel_id || tv.create_channel_id)); const category = req.dashboard.guild.channels.cache.get(String(tv.category_id)); const panel = req.dashboard.guild.channels.cache.get(String(tv.panel_channel_id)); const active = (await findMany(bot, 'tempvoice_channels', guildQuery(req.params.guildId), { limit: 1000 })).length; const checks = [{ label: 'Join-/Hub-Kanal', ok: Boolean(join), reason: join ? `#${join.name}` : 'Nicht gesetzt oder nicht gefunden' }, { label: 'Kategorie', ok: Boolean(category), reason: category ? category.name : 'Nicht gesetzt oder nicht gefunden' }, { label: 'Panel-Kanal', ok: Boolean(panel), reason: panel ? `#${panel.name}` : 'Nicht gesetzt oder nicht gefunden' }, { label: 'Aktive Temp-Channels', ok: true, reason: String(active) }]; res.json({ ok: true, checks, join_channel: checks[0], category: checks[1], active }); });

  app.post('/api/guild/:guildId/tickets/panel', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const ts = cfg.ticket_system || {}; const channel = req.dashboard.guild.channels.cache.get(String(req.body.channel_id || ts.panel_channel_id)); if (!channel?.isTextBased?.()) return res.status(400).json({ ok: false, error: 'Panel-Kanal nicht gefunden' }); const row = new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('modforge:open_ticket').setLabel('Ticket öffnen').setEmoji('🎫').setStyle(ButtonStyle.Primary)); const title = safeText(req.body.title || '🎫 Support', 100); const description = safeText(req.body.description || 'Klicke auf den Button, um ein Ticket zu öffnen.', 1800); const message = await channel.send({ content: `## ${title}\n${description}`, components: [row] }); cfg.ticket_system = { ...ts, panel_channel_id: channel.id, panel_message_id: message.id, enabled: true }; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, message_id: message.id }); });
  app.get('/api/guild/:guildId/tickets/health', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); const ts = cfg.ticket_system || {}; const panel = req.dashboard.guild.channels.cache.get(String(ts.panel_channel_id)); const category = req.dashboard.guild.channels.cache.get(String(ts.category_id)); const log = req.dashboard.guild.channels.cache.get(String(ts.log_channel_id)); const checks = [{ label: 'Panel-Kanal', ok: Boolean(panel), reason: panel ? `#${panel.name}` : 'Nicht gesetzt oder nicht gefunden' }, { label: 'Ticket-Kategorie', ok: Boolean(category), reason: category ? category.name : 'Nicht gesetzt oder nicht gefunden' }, { label: 'Log-Kanal', ok: Boolean(log), reason: log ? `#${log.name}` : 'Optional / nicht gesetzt' }]; res.json({ ok: true, checks, panel: checks[0], category: checks[1] }); });

  app.get('/api/guild/:guildId/config/versions', async (req, res) => { const versions = await bot.db.aget_config_versions(req.params.guildId, 50); res.json({ ok: true, versions: versions.map(version => ({ ...plain(version), id: String(version._id || version.version_id || '') })) }); });
  app.post('/api/guild/:guildId/config/rollback', async (req, res) => { let version = req.body.version_id ? await bot.db.aget_config_version(req.body.version_id) : (await bot.db.aget_config_versions(req.params.guildId, 2))[1]; if (!version?.config) return res.status(404).json({ ok: false, error: 'Version nicht gefunden' }); await bot.db.asave_config_version(req.params.guildId, await bot.db.fetchConfig(req.params.guildId), `rollback:${req.dashboard.session.user.id}`); await bot.db.setConfig(req.params.guildId, version.config); res.json({ ok: true }); });

  app.post('/api/guild/:guildId/beta/theme', async (req, res) => { const theme = safeText(req.body.theme, 30); await bot.db.setServerTheme(req.params.guildId, theme); const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.dashboard_theme = theme; await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, theme }); });
  app.post('/api/guild/:guildId/beta/settings', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId); cfg.beta_settings = deepMerge(cfg.beta_settings || {}, req.body || {}); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/beta/appeals/:id', async (req, res) => { await (await collection(bot, 'appeals')).updateOne(documentIdQuery(req.params.id, 'appeal_id'), { $set: { status: safeText(req.body.status || req.body.vote, 20), reviewer_id: String(req.dashboard.session.user.id), reviewed_at: new Date() } }); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/beta/staff/:id', async (req, res) => { await (await collection(bot, 'staff_applications')).updateOne(documentIdQuery(req.params.id, 'app_id'), { $set: { status: safeText(req.body.status, 20), reviewer_id: String(req.dashboard.session.user.id), reviewed_at: new Date() } }); res.json({ ok: true }); });
  app.post('/api/guild/:guildId/appeal/:id/vote', async (req, res) => { const status = ['yes', 'approve', 'accepted'].includes(String(req.body.vote || req.body.status)) ? 'accepted' : 'rejected'; await (await collection(bot, 'appeals')).updateOne(documentIdQuery(req.params.id, 'appeal_id'), { $set: { status, reviewer_id: String(req.dashboard.session.user.id), reviewed_at: new Date() } }); res.json({ ok: true, status }); });

  app.post('/api/guild/:guildId/templates/share', async (req, res) => { const backup = await backupDocument(bot, req.params.guildId, req.body.backup_id); if (!backup) return res.status(404).json({ ok: false, error: 'Backup nicht gefunden' }); const id = crypto.randomUUID().slice(0, 12); await (await collection(bot, 'community_templates')).insertOne({ template_id: id, guild_id: String(req.params.guildId), guild_name: req.dashboard.guild.name, name: safeText(req.body.name || backup.label, 100), description: safeText(req.body.description, 1000), category: safeText(req.body.category || 'general', 30), data: backup.data, likes: [], ratings: [], downloads: 0, created_at: new Date() }); res.json({ ok: true, template_id: id }); });
  app.get('/api/guild/:guildId/templates/preview/:id', async (req, res) => { const t = await findOne(bot, 'community_templates', { template_id: String(req.params.id) }); if (!t) return res.status(404).json({ ok: false, error: 'Template nicht gefunden' }); const data = t.data || {}; res.json({ ok: true, template: { ...t, id: req.params.id, roles: data.roles || [], channels: data.channels || [], score: 100, risk: { level: 'low' }, rating_avg: 0, rating_count: (t.ratings || []).length, likes: (t.likes || []).length } }); });
  app.get('/api/guild/:guildId/templates/check/:id', async (req, res) => { const t = await findOne(bot, 'community_templates', { template_id: String(req.params.id) }); if (!t) return res.status(404).json({ ok: false, error: 'Template nicht gefunden' }); const data = t.data || {}; const roleNames = new Set(req.dashboard.guild.roles.cache.map(r => r.name)); const channelNames = new Set(req.dashboard.guild.channels.cache.map(c => c.name)); res.json({ ok: true, risk: 'low', warnings: [], summary: { roles_new: (data.roles || []).filter(r => !roleNames.has(r.name)).length, roles_existing: (data.roles || []).filter(r => roleNames.has(r.name)).length, channels_new: (data.channels || []).filter(c => !channelNames.has(c.name)).length, channels_existing: (data.channels || []).filter(c => channelNames.has(c.name)).length, categories_total: (data.channels || []).filter(c => c.type === ChannelType.GuildCategory).length } }); });
  app.post('/api/guild/:guildId/templates/import/:id', async (req, res) => { const t = await findOne(bot, 'community_templates', { template_id: String(req.params.id) }); if (!t) return res.status(404).json({ ok: false, error: 'Template nicht gefunden' }); const report = await restoreFromBackup(req.dashboard.guild, t.data || {}); await (await collection(bot, 'community_templates')).updateOne({ template_id: String(req.params.id) }, { $inc: { downloads: 1 } }); res.json({ ok: true, report }); });
  app.post('/api/guild/:guildId/templates/like/:id', async (req, res) => { const col = await collection(bot, 'community_templates'); const t = await col.findOne({ template_id: String(req.params.id) }); if (!t) return res.status(404).json({ ok: false, error: 'Template nicht gefunden' }); const uid = String(req.dashboard.session.user.id); const liked = !(t.likes || []).includes(uid); await col.updateOne({ template_id: String(req.params.id) }, liked ? { $addToSet: { likes: uid } } : { $pull: { likes: uid } }); res.json({ ok: true, liked, likes: (t.likes || []).length + (liked ? 1 : -1) }); });
  app.post('/api/guild/:guildId/templates/rate/:id', async (req, res) => { const stars = int(req.body.stars, 5, 1, 5); const col = await collection(bot, 'community_templates'); const t = await col.findOne({ template_id: String(req.params.id) }); if (!t) return res.status(404).json({ ok: false, error: 'Template nicht gefunden' }); const uid = String(req.dashboard.session.user.id); const ratings = (t.ratings || []).filter(r => String(r.user_id) !== uid); ratings.push({ user_id: uid, stars }); await col.updateOne({ template_id: String(req.params.id) }, { $set: { ratings } }); res.json({ ok: true, rating_avg: (ratings.reduce((n, r) => n + Number(r.stars), 0) / ratings.length).toFixed(1) }); });
  app.post('/api/guild/:guildId/templates/unshare/:id', async (req, res) => { await (await collection(bot, 'community_templates')).deleteOne({ template_id: String(req.params.id), guild_id: String(req.params.guildId) }); res.json({ ok: true }); });
}

module.exports = { registerDashboard, pageContext, guildView, plain, deepMerge, PAGE_MAP };
