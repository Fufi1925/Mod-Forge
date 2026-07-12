const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createNodeWeb, pythonCompat } = require('../web/server');

function render(app, template, context) {
  return new Promise((resolve, reject) => {
    app.render(template, pythonCompat(context), (error, html) => error ? reject(error) : resolve(html));
  });
}

const fakeBot = {
  guilds: { cache: new Map() },
  user: null,
  ws: { ping: 0 },
  shard: null,
  tracker: { lockdownActive: new Map() },
  db: {},
  isReady: () => false,
};

const app = createNodeWeb(fakeBot);
const emptyGetObject = {};
const badge = { id: 'tester', name: 'Tester', emoji: '🧪', color: '#60a5fa', desc: 'Test-Badge', style: 'solid', rarity: 'common', level: 1 };
const role = { id: '20', name: 'Moderator', color: '#60a5fa', pos: 2, position: 2, members: 1, danger_perms: [], can_manage: true, health: 100, risk: 10 };
const channel = { id: '10', name: 'allgemein', type: 0, position: 1 };
const member = {
  id: '30', name: 'tester#0001', display_name: 'Tester', nick: '', bot: false,
  avatar: 'https://cdn.discordapp.com/embed/avatars/0.png', banner_url: null, status: 'online',
  top_role: 'Moderator', roles: [role], roles_str: 'Moderator', is_admin: true, timeout: '', voice_ch: '', voice_mute: false,
  joined: new Date().toISOString(), created: new Date().toISOString(), warns: 1, cases: 1, risk: 15,
  badges: [badge], badge_score: 1, tag: '', tag_color: '#94a3b8', all_perms: { administrator: true },
};
const caseRow = { case_id: 1, user_id: '30', user_name: 'Tester', mod_id: '40', mod_name: 'Moderator', action: 'warn', reason: 'Template-Test', ts_str: 'Gerade eben', created_at: new Date().toISOString() };
const activity = { kind: 'warn', text: 'Test-Aktivität', ts: new Date().toISOString(), data: {} };
const logModule = { key: 'moderation', label: 'Moderation', icon: '📝', desc: 'Moderations-Logs' };
const securityModule = { key: 'anti_spam', icon: '⚡', label: 'Anti-Spam', desc: 'Spam-Schutz', color: '#f59e0b', enabled: true, params: [{ key: 'punishment', label: 'Bestrafung', type: 'select', options: ['warn', 'timeout'], value: 'timeout' }, { key: 'msg_limit', label: 'Limit', type: 'number', min: 2, max: 30, value: 5, unit: 'msgs' }] };

const context = {
  guild: { id: '1', name: 'Testserver', member_count: 1, icon: null, me: { top_role: { name: 'ModForge', position: 100 }, guild_permissions: { administrator: true, manage_guild: true, manage_roles: true, manage_channels: true } } },
  cfg: emptyGetObject,
  user: { id: '2', username: 'Tester', avatar_url: 'https://cdn.discordapp.com/embed/avatars/0.png' },
  dashboard_base: '/dashboard/1', web_bot_online: true, bot_ready: true, active: 'overview',
  channels: [channel], text_channels: [channel], voice_channels: [], categories: { Moderation: [logModule] }, guild_roles: [role], roles: [role],
  members: [member], badge_catalog: [badge], definitions: [badge], users_with_badges: [{ id: '30', name: 'Tester', badges: [badge] }], history: [],
  cases: [caseRow], warns: [caseRow], activities: [activity], events: [{ event_type: 'warn', timestamp: new Date().toISOString(), data: { action: 'Warn' } }],
  backups: [{ id: 'b1', label: 'Test', guild_name: 'Testserver', roles: 1, channels: 1, categories: 0, size_label: '1 KB', size_bytes: 1024, warnings: [], health_score: 100, is_public: false, has_password: false, created_ts: Date.now() / 1000 }],
  applications: [], staff_applications: [], appeals: [], dangerous_roles: [], sections: [{ key: 'anti_spam', label: 'Anti-Spam', icon: '⚡' }],
  auto_responses: [{ trigger: 'Hallo', response: 'Hi', enabled: true }], rules: [], exempt_roles: [],
  all_public: [], my_shared: [], cats: [], tickets: [], ticket_docs: [], active_channels: [], quiz: [], role_health: [], placeholder_warnings: [],
  top_warned: [{ id: '30', name: 'Tester', count: 1 }], sorted_th: [{ count: 3, action: 'timeout' }], thresholds: [{ count: 3, action: 'timeout' }],
  top_mods: [{ id: '40', count: 1 }], action_stats: [{ typ: 'warn', count: 1 }], days_labels: ['Heute'], days_data: [1], growth_labels: ['Heute'], growth_data: [1],
  stats: { bad_words: 1, regex: 0, regex_bad: 0, regex_warn: 0, domains: 0, total: 1, warn: 1, ban: 0, kick: 0, timeout: 0 },
  am: {}, wc: {}, lv: {}, vs: {}, ve: {}, te: {}, ba: {}, decay: {}, cat_labels: {}, beta_warning: { warning: 'Test' }, themes: {}, verify_stats: { enabled: true, mode: 'one_click', add_roles: 1, remove_roles: 0, quiz_questions: 0 }, panel_status: { channel_ok: true, reason: 'OK' },
  ticket_settings: { enabled: true, panel_channel_id: '10', panel_message_id: null, panel_title: 'Support Tickets', panel_description: 'Kategorie wählen', panel_placeholder: 'Auswählen', transcript_channel_id: null, log_channel_id: null, archive_category_id: null, global_team_roles: [], global_admin_roles: [], dashboard_admin_roles: [], max_open_global: 3, claim_enabled: true, unclaim_enabled: true, owner_can_close: true, transcript_enabled: true, transcript_format: 'html', close_mode: 'archive', close_delay_seconds: 5 },
  ticket_categories: [], ticket_docs: [], ticket_logs: [], ticket_category_stats: [], ticket_team_stats: [], ticket_filters: {}, csrf_token: 'test-csrf',
  ticket_stats: { total: 0, open: 0, closed: 0, claimed: 0, archived: 0, deleted: 0, today: 0, week: 0, month: 0, frequent_category: '—', active_categories: 0 }, role_stats: { total: 1, dangerous: 0, manageable: 1, sticky: 0, auto: 0, verify: 1 }, tv: {},
  security_modules: [securityModule], modules: [securityModule], perm_checks: [], level_info: [], presets: [], suggestions: [], regex_report: [],
  log_channels: { moderation: '10' }, default_channel: '10', total_modules: 1, total_configured: 1,
  total_size_bytes: 1024, auto_interval: 24, auto_max: 5, auto_enabled: true, last_backup_ts: Date.now() / 1000,
  total_entries: 0, total_warns: 1, warns_7d: 1, cases_7d: 1, cases_30d: 1,
  humans: 1, bots: 0, online: 1, online_count: 1, boosts: 0, boost_count: 0, boost_tier: 0,
  cases_count: 1, warns_count: 1, roles_count: 1, text_ch: 1, voice_ch: 0, voice_active: 0, in_timeout: 0,
  log_channels_count: 1, active_mods: 1, active_count: 1, total_count: 1, sec_level: 1, security_level: 1, wl_count: 0,
  server_created_ts: Date.now() / 1000, growth_total: 1, owner_name: 'Owner', created: 'Heute', prefix: '!',
  score: 80, score_label: 'Sehr gut', score_color: '#4ade80', has_default_log: true,
  risk: { score: 15, cases: 1, flags: [], last_punishment: 'warn' }, account_age: 100, join_age: 10,
};

async function main() {
  const frozenContext = Object.freeze({ nested: Object.freeze({ value: 1 }) });
  pythonCompat(frozenContext);
  const templatesDirectory = path.join(__dirname, '..', 'web', 'templates', 'dashboard');
  const templates = fs.readdirSync(templatesDirectory).filter(name => name.endsWith('.html') && !name.startsWith('_')).sort();
  const failures = [];
  for (const name of templates) {
    try {
      const html = await render(app, `dashboard/${name}`, { ...context, active: name.replace('.html', '') });
      if (!html.toLowerCase().includes('<!doctype html>')) throw new Error('Template lieferte kein vollständiges HTML-Dokument');
      if (html.includes('{%') || html.includes('{{')) throw new Error('Nicht gerenderte Template-Syntax im HTML gefunden');
      const scripts = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)]
        .filter(match => !/\bsrc\s*=|type\s*=\s*["']application\/json/i.test(match[1]))
        .map(match => match[2].trim())
        .filter(Boolean);
      for (let index = 0; index < scripts.length; index += 1) {
        try { new vm.Script(scripts[index], { filename: `dashboard/${name}#script-${index + 1}` }); }
        catch (error) { throw new Error(`JavaScript in Script ${index + 1} ist ungültig: ${error.message}`); }
      }
      console.log(`OK dashboard/${name} (${html.length} Zeichen, ${scripts.length} Scripts)`);
    } catch (error) {
      failures.push({ name, error });
      console.error(`FEHLER dashboard/${name}: ${error.stack || error.message}`);
    }
  }
  try {
    const systemHtml = await render(app, 'admin/system.html', { active: 'system', discord_entries: [{ value: '222222222222222222', username: 'Blocked User', avatar_url: '', reason: 'Test', added_by: 'admin', added_by_name: 'Admin', created_at_fmt: 'Heute' }], ip_entries: [{ value: 'a'.repeat(64), label: 'IP-FP-AAAAAAAAAAAA', reason: 'Test', linked_users: [{ id: '333333333333333333', username: 'Alt Test' }], created_at_fmt: 'Heute' }], guild_count: 1, event_count: 2, message: '' });
    if (!systemHtml.includes('Global Security System') || systemHtml.includes('{%') || systemHtml.includes('{{')) throw new Error('Admin-System-Template wurde nicht vollständig gerendert');
    console.log(`OK admin/system.html (${systemHtml.length} Zeichen)`);
  } catch (error) {
    failures.push({ name: 'admin/system.html', error });
    console.error(`FEHLER admin/system.html: ${error.stack || error.message}`);
  }
  if (failures.length) throw new Error(`${failures.length} Template-Tests sind fehlgeschlagen`);
  console.log(`Dashboard-Template-Test erfolgreich: ${templates.length}/${templates.length} + Admin System`);
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
