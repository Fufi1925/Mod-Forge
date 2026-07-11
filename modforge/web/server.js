// ModForge Node Web Dashboard – Bot + Web zusammen deploybar
const express = require('express');
const nunjucks = require('nunjucks');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { URLSearchParams } = require('node:url');
const { registerDashboard } = require('./dashboard');
const { SUPERUSER_IDS } = require('../bot/config');

const SESSION_COOKIE = 'modforge_session';
const ADMIN_COOKIE = 'modforge_admin';
const SESSION_TTL = Number(process.env.DASHBOARD_SESSION_TTL || 30 * 24 * 3600);
const DISCORD_API = 'https://discord.com/api/v10';
// Discord OAuth2 Scopes: space-separated in URL, shown here as requested: identify,guilds,guilds.join
const OAUTH_SCOPES = 'identify guilds guilds.join';
const sessionCollectionPromises = new WeakMap();
const adminEventCollectionPromises = new WeakMap();

function withTimeout(promise, milliseconds, label = 'Operation') {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} hat nach ${milliseconds} ms das Zeitlimit überschritten.`)), milliseconds);
  });
  return Promise.race([Promise.resolve(promise), timeout]).finally(() => clearTimeout(timer));
}

function esc(value = '') {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}

function pythonCompat(value, seen = new WeakSet()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return value;
  seen.add(value);
  if (Array.isArray(value)) {
    if (Object.isExtensible(value) && !Object.prototype.hasOwnProperty.call(value, 'append')) {
      Object.defineProperty(value, 'append', { enumerable: false, configurable: true, value(item) { this.push(item); return null; } });
    }
    for (const item of value) pythonCompat(item, seen);
    return value;
  }
  if (!Object.isExtensible(value)) {
    for (const item of Object.values(value)) pythonCompat(item, seen);
    return value;
  }
  if (!Object.prototype.hasOwnProperty.call(value, 'get')) {
    Object.defineProperty(value, 'get', { enumerable: false, configurable: true, value(key, fallback = null) { return pythonCompat(this[key] == null ? fallback : this[key]); } });
  }
  if (!Object.prototype.hasOwnProperty.call(value, 'items')) {
    Object.defineProperty(value, 'items', { enumerable: false, configurable: true, value() { return Object.entries(this); } });
  }
  for (const item of Object.values(value)) pythonCompat(item, seen);
  return value;
}

function parseCookies(req) {
  const out = {};
  for (const part of String(req.headers.cookie || '').split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    out[part.slice(0, idx).trim()] = decodeURIComponent(part.slice(idx + 1).trim());
  }
  return out;
}

function getClientIp(req) {
  const raw = req.headers['cf-connecting-ip'] || req.headers['x-real-ip'] || req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '';
  return String(Array.isArray(raw) ? raw[0] : raw).split(',')[0].trim().replace(/^::ffff:/, '') || 'unknown';
}

async function lookupGeo(ip) {
  if (!ip || ip === 'unknown' || ip === '127.0.0.1' || ip === '::1' || ip.startsWith('10.') || ip.startsWith('192.168.')) return { ip, city: 'Lokal', country: '', region: '' };
  try {
    const res = await fetch(`https://ipapi.co/${encodeURIComponent(ip)}/json/`, { headers: { 'User-Agent': 'ModForge-Dashboard/3.0' } });
    const j = await res.json();
    return { ip, city: j.city || 'Unbekannt', region: j.region || '', country: j.country_name || j.country || '' };
  } catch {
    return { ip, city: 'Unbekannt', country: '', region: '' };
  }
}

function setCookie(res, name, value, maxAge = SESSION_TTL) {
  const secure = String(process.env.DASHBOARD_BASE_URL || '').startsWith('https://') || process.env.NODE_ENV === 'production';
  const parts = [`${name}=${encodeURIComponent(value)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax', `Max-Age=${maxAge}`];
  if (secure) parts.push('Secure');
  res.append('Set-Cookie', parts.join('; '));
}

function clearCookie(res, name) {
  res.append('Set-Cookie', `${name}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`);
}

function publicBaseUrl(req) {
  const configured = process.env.DASHBOARD_BASE_URL || process.env.PUBLIC_BASE_URL;
  if (configured) return String(configured).replace(/\/$/, '');
  if (process.env.RAILWAY_PUBLIC_DOMAIN) return `https://${String(process.env.RAILWAY_PUBLIC_DOMAIN).replace(/^https?:\/\//, '').replace(/\/$/, '')}`;
  return `${req.protocol}://${req.get('host')}`.replace(/\/$/, '');
}

function iconUrl(id, icon, fallback = 0) {
  return icon ? `https://cdn.discordapp.com/icons/${id}/${icon}.png?size=128` : `https://cdn.discordapp.com/embed/avatars/${fallback}.png`;
}

function userAvatar(user) {
  const id = user?.id || '0';
  return user?.avatar ? `https://cdn.discordapp.com/avatars/${id}/${user.avatar}.png?size=128` : `https://cdn.discordapp.com/embed/avatars/${Number(BigInt(id || 0) % 5n)}.png`;
}

function inviteUrl(clientId, guildId = null) {
  const params = new URLSearchParams({ client_id: String(clientId || ''), scope: 'bot applications.commands', permissions: '8' });
  if (guildId) {
    params.set('guild_id', String(guildId));
    params.set('disable_guild_select', 'true');
  }
  return `https://discord.com/oauth2/authorize?${params.toString()}`;
}

async function discordApi(path, token, options = {}) {
  const headers = { 'User-Agent': 'ModForge-Node-Dashboard/3.0', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${DISCORD_API}${path}`, { ...options, headers });
  const text = await res.text();
  let json = {};
  try { json = text ? JSON.parse(text) : {}; } catch { json = { raw: text }; }
  if (!res.ok) throw new Error(`Discord API ${res.status}: ${text.slice(0, 250)}`);
  return json;
}

async function pullUserToGuild(guildId, userId, accessToken) {
  const res = await fetch(`${DISCORD_API}/guilds/${guildId}/members/${userId}`, {
    method: 'PUT',
    headers: {
      'Authorization': `Bot ${process.env.DISCORD_TOKEN || ''}`,
      'Content-Type': 'application/json',
      'User-Agent': 'ModForge-Node-Dashboard/3.0',
    },
    body: JSON.stringify({ access_token: accessToken }),
  });
  const text = await res.text();
  if (![201, 204].includes(res.status)) throw new Error(`HTTP ${res.status}: ${text.slice(0, 250)}`);
  return { status: res.status, created: res.status === 201 };
}

function layout(title, body, user = null) {
  return `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)} – ModForge</title><style>
:root{color-scheme:dark;--bg:#070712;--card:rgba(255,255,255,.055);--line:rgba(255,255,255,.11);--fg:#f8fafc;--muted:#94a3b8;--blue:#60a5fa;--green:#4ade80;--red:#fb7185;--yellow:#fbbf24;--violet:#8b5cf6}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#1e1b4b,#070712 55%);color:var(--fg);font-family:Inter,system-ui,Segoe UI,sans-serif;min-height:100vh}a{color:inherit;text-decoration:none}.top{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:rgba(5,5,16,.85);border-bottom:1px solid var(--line);position:sticky;top:0;backdrop-filter:blur(18px);z-index:10}.brand{display:flex;align-items:center;gap:10px;font-weight:900}.logo{width:36px;height:36px;border-radius:12px;background:linear-gradient(135deg,var(--blue),var(--violet));display:grid;place-items:center}.user{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:.9rem}.user img{width:32px;height:32px;border-radius:50%}.wrap{max-width:1180px;margin:0 auto;padding:28px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.25)}.row{display:flex;align-items:center;gap:12px}.grow{flex:1;min-width:0}.muted{color:var(--muted)}.btn{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:rgba(255,255,255,.07);padding:9px 13px;border-radius:12px;font-weight:700;font-size:.85rem}.btn:hover{border-color:rgba(96,165,250,.45)}.primary{background:linear-gradient(135deg,#2563eb,#7c3aed);border:0}.danger{background:rgba(239,68,68,.14);border-color:rgba(239,68,68,.25);color:#fecaca}.ok{color:var(--green)}.warn{color:var(--yellow)}.badge{font-size:.68rem;padding:4px 9px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.05);font-weight:800}.servericon{width:48px;height:48px;border-radius:15px;object-fit:cover;background:rgba(255,255,255,.08);display:grid;place-items:center;font-weight:900}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.input{width:100%;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:12px;color:var(--fg);padding:10px 12px;margin:6px 0 12px}.table{width:100%;border-collapse:collapse}.table td,.table th{padding:12px;border-bottom:1px solid var(--line);text-align:left}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem;color:var(--muted)}h1{margin:0 0 8px}h2{margin:0 0 12px;font-size:1.1rem}</style></head><body><header class="top"><a class="brand" href="/"><span class="logo">🛡️</span><span>ModForge</span></a><nav class="actions"><a class="btn" href="/dashboard">Dashboard</a><a class="btn" href="/admin">Admin</a><a class="btn" href="/admin/pull">Pull</a><a class="btn primary" href="/invite">Bot einladen</a>${user ? `<span class="user"><img src="${esc(user.avatar_url)}"><span>${esc(user.username)}</span></span>` : `<a class="btn" href="/login">Login</a>`}</nav></header><main class="wrap">${body}</main></body></html>`;
}

async function sessionsCol(bot) {
  if (!sessionCollectionPromises.has(bot)) {
    sessionCollectionPromises.set(bot, (async () => {
      await withTimeout(bot.db.connect(), 8_000, 'MongoDB-Verbindung für Dashboard-Sessions');
      const col = bot.db.db.collection('dashboard_sessions');
      await Promise.allSettled([
        col.createIndex({ sid: 1 }, { unique: true }),
        col.createIndex({ 'user.id': 1 }),
        col.createIndex({ expires_at: 1 }),
      ]);
      return col;
    })());
  }
  try {
    return await sessionCollectionPromises.get(bot);
  } catch (error) {
    sessionCollectionPromises.delete(bot);
    throw error;
  }
}

async function adminEventsCol(bot) {
  if (!adminEventCollectionPromises.has(bot)) {
    adminEventCollectionPromises.set(bot, (async () => {
      await withTimeout(bot.db.connect(), 8_000, 'MongoDB-Verbindung für Admin-Events');
      const col = bot.db.db.collection('admin_events');
      await Promise.allSettled([
        col.createIndex({ created_at: -1 }),
        col.createIndex({ type: 1 }),
        col.createIndex({ ip: 1 }),
      ]);
      return col;
    })());
  }
  try {
    return await adminEventCollectionPromises.get(bot);
  } catch (error) {
    adminEventCollectionPromises.delete(bot);
    throw error;
  }
}

async function recordAdminEvent(bot, req, type, data = {}) {
  try {
    const ip = getClientIp(req);
    const geo = data.geo || await lookupGeo(ip).catch(() => ({ ip, city: 'Unbekannt', country: '' }));
    await (await adminEventsCol(bot)).insertOne({
      type,
      ip,
      geo,
      path: req.originalUrl || req.url,
      method: req.method,
      user_agent: String(req.headers['user-agent'] || '').slice(0, 300),
      data,
      created_at: new Date(),
      ts: Date.now() / 1000,
    });
  } catch (error) {
    console.warn('admin event log failed:', error.message);
  }
}

async function recentAdminEvents(bot, limit = 12) {
  try {
    return await (await adminEventsCol(bot)).find({}).sort({ created_at: -1 }).limit(limit).toArray();
  } catch {
    return [];
  }
}

async function getSession(req, bot) {
  const sid = parseCookies(req)[SESSION_COOKIE];
  if (!sid) return null;
  try {
    const col = await withTimeout(sessionsCol(bot), 8_000, 'Dashboard-Session-Collection');
    const doc = await withTimeout(col.findOne({ sid }, { maxTimeMS: 5_000 }), 6_000, 'Dashboard-Session-Abfrage');
    if (!doc || (doc.expires_at && doc.expires_at < Date.now() / 1000)) return null;
    col.updateOne({ sid }, { $set: { last_seen: Date.now() / 1000 } }, { maxTimeMS: 5_000 }).catch(() => null);
    return doc;
  } catch (error) {
    console.error('Dashboard-Session-Fehler:', error.message);
    return null;
  }
}

function requireAdmin(req, res, next) {
  const cookies = parseCookies(req);
  if (process.env.ADMIN_SESSION_TOKEN && cookies[ADMIN_COOKIE] === process.env.ADMIN_SESSION_TOKEN) return next();
  return res.redirect('/admin/login');
}

function canManage(guild) {
  if (!guild) return false;
  if (guild.owner === true || guild.owner === 'true') return true;
  try {
    const p = BigInt(guild.permissions || '0');
    return Boolean((p & 0x8n) || (p & 0x20n)); // Administrator oder Manage Guild/Server verwalten
  } catch {
    const p = Number(guild.permissions || 0);
    return Boolean((p & 0x8) || (p & 0x20));
  }
}


function adminLoginHtml(error = '') {
  return layout('Admin Login', `<div class="card" style="max-width:440px;margin:60px auto">
    <h1>🔐 Admin Login</h1>
    <p class="muted">Melde dich mit ADMIN_USERNAME und ADMIN_PASSWORD an.</p>
    ${error ? `<div class="card" style="border-color:rgba(239,68,68,.35);background:rgba(239,68,68,.08);margin:14px 0;padding:12px;color:#fecaca">${esc(error)}</div>` : ''}
    <form method="post" action="/admin/login">
      <label class="muted">Username</label>
      <input class="input" name="username" placeholder="admin" autocomplete="username" required>
      <label class="muted">Passwort</label>
      <input class="input" name="password" type="password" placeholder="Passwort" autocomplete="current-password" required>
      <button class="btn primary" type="submit">Login</button>
    </form>
  </div>`);
}

function createNodeWeb(bot) {
  const app = express();
  app.set('trust proxy', 1);
  app.disable('x-powered-by');
  const templatesDir = path.join(__dirname, 'templates');
  const env = nunjucks.configure(templatesDir, { autoescape: true, express: app, noCache: process.env.NODE_ENV !== 'production', throwOnUndefined: false });
  env.addGlobal('url_for', (name) => name === 'static' ? '/static' : `/${name}`);
  env.addGlobal('True', true);
  env.addGlobal('False', false);
  env.addGlobal('None', null);
  env.addFilter('tojson', (value) => JSON.stringify(value ?? null));
  env.addFilter('sum', (arr, attr) => Array.isArray(arr) ? arr.reduce((n, x) => n + Number(attr ? x?.[attr] : x || 0), 0) : 0);
  env.addFilter('int', (value, fallback = 0) => Number.isFinite(Number(value)) ? Math.trunc(Number(value)) : fallback);
  env.addFilter('float', (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback);
  env.addFilter('string', (value) => String(value ?? ''));
  env.addFilter('list', (value) => Array.isArray(value) ? value : value == null ? [] : [...value]);
  env.addFilter('limit', (value, count) => typeof value === 'string' || Array.isArray(value) ? value.slice(0, Math.max(0, Number(count) || 0)) : value);
  env.addFilter('configuredCount', (modules, configured) => Array.isArray(modules) ? modules.filter(module => Boolean(configured?.[module?.key])).length : 0);
  env.addFilter('selectattr', (arr, attr, test = null, expected = undefined) => {
    if (!Array.isArray(arr)) return [];
    if (test === 'equalto' || test === 'eq') return arr.filter(item => item?.[attr] === expected);
    if (test === 'ne') return arr.filter(item => item?.[attr] !== expected);
    return arr.filter(item => Boolean(item?.[attr]));
  });
  env.addFilter('rejectattr', (arr, attr, test = null, expected = undefined) => {
    if (!Array.isArray(arr)) return [];
    if (test === 'equalto' || test === 'eq') return arr.filter(item => item?.[attr] !== expected);
    if (test === 'ne') return arr.filter(item => item?.[attr] === expected);
    return arr.filter(item => !item?.[attr]);
  });
  env.addFilter('map', (arr, options) => {
    if (!Array.isArray(arr)) return [];
    if (options === 'string') return arr.map(item => String(item ?? ''));
    if (options === 'int') return arr.map(item => Number.parseInt(item, 10) || 0);
    const attr = typeof options === 'string' ? options : options?.attribute;
    return attr ? arr.map(item => item?.[attr]) : arr;
  });

  app.use('/static', express.static(path.join(__dirname, 'static')));
  app.use(express.urlencoded({ extended: true }));
  app.use(express.json({ limit: '1mb' }));

  app.use((req, res, next) => {
    res.locals.bot = bot;
    next();
  });

  function publicContext(extra = {}) {
    const guilds = [...bot.guilds.cache.values()].sort((a, b) => (b.memberCount || 0) - (a.memberCount || 0));
    const gc = bot.guilds.cache.size;
    const mc = guilds.reduce((a, g) => a + (g.memberCount || 0), 0);
    const guildsPayload = guilds.map((g) => ({ id: String(g.id), name: g.name, members: g.memberCount || 0, online: 0, security: '100%', avatar_url: g.iconURL?.({ size: 128 }) || 'https://cdn.discordapp.com/embed/avatars/0.png' }));
    const activities = [];
    try { activities.push(...require('../bot/config').ACTIVITY.snapshot(30)); } catch {}
    return {
      cid: process.env.DISCORD_CLIENT_ID || bot.user?.id || '',
      gc: gc.toLocaleString('de-DE'), gc_raw: gc, guild_count: gc,
      mc: mc.toLocaleString('de-DE'), mc_raw: mc, member_count: mc, member_count_fmt: mc.toLocaleString('de-DE'),
      up: Math.floor(process.uptime()), up_s: Math.floor(process.uptime()), uptime_pct: '99.990',
      lat: Math.round(bot.ws?.ping || 0), api_latency: Math.round(bot.ws?.ping || 0),
      shard_count: bot.shard?.count || 1,
      cases: '0', cases_count: 0, cases_count_fmt: '0', warns: '0', archive_count: 0,
      features: [], log_mods: [], cmds_preview: [],
      guilds: guildsPayload,
      recent_cases: [], recent_activities: activities.map((a) => ({ kind: a.type || a.kind || 'event', text: a.message || a.text || '', guild_name: a.guild_name || 'System', ...a })),
      raids: '0', spam: '0', phishing: '0',
      today: new Date().toISOString().slice(0, 10), title: 'ModForge',
      user: null, error: '', info: '', plus_price: '4,99€',
      day: new Date().toLocaleDateString('de-DE'), regions: ['EU', 'US', 'ASIA'],
      public_backups: [], categories: [], presets: [],
      ...extra,
    };
  }

  function legacyFallbackRender(template, error = null) {
    let raw = fs.readFileSync(path.join(templatesDir, template), 'utf8');
    // Fallback für alte Flask/Jinja-Syntax, die Nunjucks nicht kann. So geht jede Seite weiter auf,
    // statt 500 zu werfen. HTML/CSS/JS-Inhalt bleibt erhalten, Jinja-Logik wird neutralisiert.
    raw = raw
      .replace(/\{#([\s\S]*?)#\}/g, '')
      .replace(/\{%\s*extends[^%]*%\}/g, '')
      .replace(/\{%\s*include[^%]*%\}/g, '')
      .replace(/\{%\s*set[^%]*%\}/g, '')
      .replace(/\{%\s*block[^%]*%\}/g, '')
      .replace(/\{%\s*endblock\s*%\}/g, '')
      .replace(/\{%\s*for[^%]*%\}/g, '')
      .replace(/\{%\s*endfor\s*%\}/g, '')
      .replace(/\{%\s*if[^%]*%\}/g, '')
      .replace(/\{%\s*elif[^%]*%\}/g, '')
      .replace(/\{%\s*else\s*%\}/g, '')
      .replace(/\{%\s*endif\s*%\}/g, '')
      .replace(/\{\{\s*([^}]*)\s*\}\}/g, '');
    return `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/style.css"><title>ModForge</title></head><body>${raw}${error ? `<!-- fallback: ${esc(error.message)} -->` : ''}</body></html>`;
  }

  function renderOld(res, template, ctx = {}, strict = false) {
    const context = pythonCompat(publicContext(ctx));
    return env.render(template, context, (error, html) => {
      if (!error) return res.send(html);
      console.error(`Template ${template} konnte nicht gerendert werden:`, error);
      if (!strict && templateExists(template)) return res.send(legacyFallbackRender(template, error));
      return res.status(500).send(layout('Template Fehler', `<div class="card"><h1>Template Fehler</h1><p class="muted">${esc(template)}</p><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    });
  }

  function templateExists(template) {
    return fs.existsSync(path.join(templatesDir, template));
  }

  function renderTemplateOr404(res, template, ctx = {}) {
    if (!templateExists(template)) return res.status(404).send(layout('404', '<div class="card"><h1>404</h1><p>Seite nicht gefunden.</p></div>'));
    return renderOld(res, template, ctx);
  }

  app.get('/health', (req, res) => {
    const botReady = Boolean(bot.isReady());
    const databaseReady = Boolean(bot.db?.ready);
    const ok = botReady && databaseReady;
    return res.status(ok ? 200 : 503).json({ ok, status: ok ? 'ready' : 'starting', bot_ready: botReady, database_ready: databaseReady, guilds: bot.guilds.cache.size, uptime: Math.floor(process.uptime()), ts: new Date().toISOString() });
  });
  app.get('/healthz', (req, res) => res.redirect('/health'));
  app.get('/api/status', (req, res) => res.json({ ok: true, bot_ready: bot.isReady(), guilds: bot.guilds.cache.size, members: bot.guilds.cache.reduce((a, g) => a + (g.memberCount || 0), 0) }));

  // Alte öffentliche Website-Routen 1:1 aus den vorhandenen Templates gerendert.
  app.get('/', (req, res) => renderOld(res, 'index.html'));
  app.get('/features', (req, res) => renderOld(res, 'features.html'));
  app.get('/premium', (req, res) => renderOld(res, 'premium.html'));
  app.get('/upgrade', (req, res) => res.redirect('/premium'));
  app.get('/pricing', (req, res) => renderOld(res, 'pricing.html'));
  app.get('/partners', (req, res) => renderOld(res, 'partners.html'));
  app.get('/terms', (req, res) => renderOld(res, 'terms.html', { title: 'Terms of Service' }));
  app.get('/privacy', (req, res) => renderOld(res, 'privacy.html', { title: 'Privacy Policy' }));
  app.get('/imprint', (req, res) => renderOld(res, 'imprint.html', { title: 'Impressum' }));
  app.get('/legal', (req, res) => renderOld(res, 'legal.html', { title: 'Rechtliches' }));
  app.get('/status', (req, res) => renderOld(res, 'status.html'));
  app.get('/live', (req, res) => renderOld(res, 'live.html'));
  app.get('/public-stats', (req, res) => renderOld(res, 'public_stats.html'));
  app.get('/templates', (req, res) => renderOld(res, 'templates.html'));
  // Alte/zusätzliche Marketing-/Docs-Seiten: wenn Template existiert, 1:1 rendern, sonst elegante Platzhalter-Seite.
  for (const page of ['commands','ai','economy','badges','security','integrations','widgets','migrate','emojis','api-docs','branding','tutorials','faq','roadmap','blog','downloads','uptime','affiliate','suggest','contact','showcase','testimonials','leaderboard','jobs','events','support','docs']) {
    app.get(`/${page}`, (req, res) => renderTemplateOr404(res, `${page}.html`));
  }
  app.get('/docs/:page', (req, res) => renderTemplateOr404(res, `docs/${req.params.page}.html`));
  app.get('/status/:page', (req, res) => renderTemplateOr404(res, `status/${req.params.page}.html`));


  app.get('/invite', (req, res) => res.redirect(inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id)));

  app.get('/login', (req, res) => res.redirect('/dashboard/login'));
  app.get('/dashboard/login', (req, res) => {
    const clientId = process.env.DISCORD_CLIENT_ID || bot.user?.id;
    if (!clientId || !process.env.DISCORD_CLIENT_SECRET) {
      return res.status(503).send(layout('OAuth nicht konfiguriert', '<div class="card"><h1>OAuth nicht konfiguriert</h1><p class="muted">Setze DISCORD_CLIENT_ID und DISCORD_CLIENT_SECRET in Railway Variables.</p></div>'));
    }
    if (req.query.force) clearCookie(res, SESSION_COOKIE);
    const base = publicBaseUrl(req);
    const state = crypto.randomBytes(16).toString('hex');
    setCookie(res, 'modforge_oauth_state', state, 600);
    const params = new URLSearchParams({ client_id: clientId, redirect_uri: `${base}/dashboard/auth/callback`, response_type: 'code', scope: OAUTH_SCOPES, prompt: 'consent', state });
    res.redirect(`https://discord.com/oauth2/authorize?${params.toString()}`);
  });

  app.get('/dashboard/auth/callback', async (req, res) => {
    try {
      const cookies = parseCookies(req);
      if (!req.query.code || req.query.state !== cookies.modforge_oauth_state) return res.redirect('/login?error=state');
      const base = publicBaseUrl(req);
      const body = new URLSearchParams({ client_id: process.env.DISCORD_CLIENT_ID || bot.user?.id, client_secret: process.env.DISCORD_CLIENT_SECRET || '', grant_type: 'authorization_code', code: String(req.query.code), redirect_uri: `${base}/dashboard/auth/callback` });
      const tokenRes = await fetch(`${DISCORD_API}/oauth2/token`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body });
      const token = await tokenRes.json();
      if (!token.access_token) throw new Error(JSON.stringify(token).slice(0, 200));
      const user = await discordApi('/users/@me', token.access_token);
      const guilds = await discordApi('/users/@me/guilds', token.access_token).catch((error) => {
        console.warn('Discord guild fetch failed:', error.message);
        return [];
      });
      const ip = getClientIp(req);
      const geo = await lookupGeo(ip);
      const sid = crypto.randomBytes(32).toString('hex');
      const session = { sid, access_token: token.access_token, refresh_token: token.refresh_token, scope: token.scope || OAUTH_SCOPES, token_expires_at: Date.now()/1000 + Number(token.expires_in || SESSION_TTL), created_at: Date.now()/1000, last_seen: Date.now()/1000, expires_at: Date.now()/1000 + SESSION_TTL, ip, geo, user: { id: user.id, username: user.username || user.global_name || 'Discord User', global_name: user.global_name, avatar_url: userAvatar(user) }, guilds: Array.isArray(guilds) ? guilds : [] };
      const col = await sessionsCol(bot);
      // Keine doppelten Pull-/Dashboard-User: gleicher Discord user.id => alte Sessions löschen, neue Session speichern.
      await col.deleteMany({ 'user.id': String(user.id) }).catch(() => null);
      await col.updateOne({ sid }, { $set: session }, { upsert: true });
      console.log(`OAuth login OK: ${session.user.username} (${session.user.id}) scopes=${session.scope} guilds=${session.guilds.length} ip=${ip} city=${geo.city || '?'}`);
      await recordAdminEvent(bot, req, 'dashboard_login', { user_id: user.id, username: session.user.username, scopes: session.scope, guilds: session.guilds.length, geo }).catch(() => null);
      setCookie(res, SESSION_COOKIE, sid, SESSION_TTL);
      clearCookie(res, 'modforge_oauth_state');
      res.redirect('/dashboard');
    } catch (e) {
      res.status(500).send(layout('Login Fehler', `<div class="card"><h1>❌ Login Fehler</h1><p class="muted">${esc(e.message)}</p><a class="btn" href="/login">Erneut versuchen</a></div>`));
    }
  });

  app.get('/dashboard/logout', async (req, res) => {
    const sid = parseCookies(req)[SESSION_COOKIE];
    if (sid) await (await sessionsCol(bot)).deleteOne({ sid }).catch(() => null);
    clearCookie(res, SESSION_COOKIE);
    res.redirect('/');
  });
  app.get('/logout', (req, res) => res.redirect('/dashboard/logout'));

  app.get('/dashboard/refresh', async (req, res) => {
    const s = await getSession(req, bot);
    if (!s) return res.redirect('/login');
    const guilds = await discordApi('/users/@me/guilds', s.access_token).catch(() => s.guilds || []);
    await (await sessionsCol(bot)).updateOne({ sid: s.sid }, { $set: { guilds, guilds_refreshed_at: Date.now()/1000 } });
    res.redirect('/dashboard');
  });

  app.get('/dashboard', async (req, res) => {
    const s = await getSession(req, bot);
    if (!s) return res.redirect('/login');
    if ((!Array.isArray(s.guilds) || !s.guilds.length) && s.access_token) {
      const freshGuilds = await discordApi('/users/@me/guilds', s.access_token).catch(() => []);
      if (Array.isArray(freshGuilds) && freshGuilds.length) {
        s.guilds = freshGuilds;
        await (await sessionsCol(bot)).updateOne({ sid: s.sid }, { $set: { guilds: freshGuilds, guilds_refreshed_at: Date.now()/1000, last_seen: Date.now()/1000 } }).catch(() => null);
      }
    }
    const cid = process.env.DISCORD_CLIENT_ID || bot.user?.id || '';
    const botGuildIds = new Set(bot.guilds.cache.map(guild => String(guild.id)));
    const superuser = SUPERUSER_IDS.includes(String(s.user?.id));
    let servers;
    if (superuser) {
      const byId = new Map();
      for (const guild of bot.guilds.cache.values()) byId.set(String(guild.id), { id: String(guild.id), name: guild.name, icon: guild.iconURL?.({ size: 128 }) || iconUrl(guild.id, null, 0), bot_active: true, can_manage: true });
      for (const guild of s.guilds || []) if (!byId.has(String(guild.id))) byId.set(String(guild.id), { id: String(guild.id), name: guild.name || `Server ${guild.id}`, icon: iconUrl(guild.id, guild.icon, 0), bot_active: botGuildIds.has(String(guild.id)), can_manage: true });
      servers = [...byId.values()];
    } else {
      servers = (s.guilds || []).filter(canManage).map(guild => ({ id: String(guild.id), name: guild.name || `Server ${guild.id}`, icon: iconUrl(guild.id, guild.icon, 0), bot_active: botGuildIds.has(String(guild.id)), can_manage: true }));
    }
    servers.sort((a, b) => Number(b.bot_active) - Number(a.bot_active) || String(a.name).localeCompare(String(b.name)));
    return renderOld(res, 'node/dashboard_home.html', { user: s.user, cid, servers, bot_servers: servers.filter(item => item.bot_active), other_servers: servers.filter(item => !item.bot_active) });
  });

  registerDashboard({
    app,
    bot,
    render: renderOld,
    getSession,
    canManage,
    forbidden: (res, user) => res.status(403).send(layout('Forbidden', '<div class="card"><h1>403</h1><p>Du hast auf diesem Server keine Admin- oder Manage-Server-Rechte.</p></div>', user)),
    invite: (guildId) => inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, guildId),
    isAdmin: (req) => Boolean(process.env.ADMIN_SESSION_TOKEN && parseCookies(req)[ADMIN_COOKIE] === process.env.ADMIN_SESSION_TOKEN),
  });

  app.post('/dashboard/:guildId/logs', async (req, res) => {
    const s = await getSession(req, bot);
    if (!s) return res.redirect('/login');
    const allowed = (s.guilds || []).some(g => String(g.id) === String(req.params.guildId) && canManage(g));
    if (!allowed) return res.status(403).send('forbidden');
    const cfg = await bot.db.fetchConfig(req.params.guildId);
    cfg.log_channel = String(req.body.channel_id || '').trim() || null;
    cfg.log_channels = cfg.log_channels || {};
    if (cfg.log_channel) for (const mod of ['default','moderation','voice','members','messages','channels','roles','webhooks','tickets','verify','automod','antispam','antinuke','antiraid','antiscam','warns','cases','backup','tempvoice']) cfg.log_channels[mod] = cfg.log_channel;
    await bot.db.setConfig(req.params.guildId, cfg);
    await bot.db.log_channels_snapshot(req.params.guildId, cfg.log_channels).catch(()=>null);
    res.redirect(`/dashboard/${req.params.guildId}`);
  });

  app.get('/server/:guildId', async (req, res) => {
    const guild = bot.guilds.cache.get(String(req.params.guildId));
    const cfg = guild ? await bot.db.fetchConfig(guild.id).catch(() => ({})) : {};
    return renderOld(res, 'server_public.html', { guild, cfg, public_config: cfg, members: [], stats: {} });
  });
  app.get('/server/:guildId/user/:memberId', async (req, res) => {
    const guild = bot.guilds.cache.get(String(req.params.guildId));
    const member = guild ? await guild.members.fetch(req.params.memberId).catch(() => null) : null;
    return renderOld(res, 'server_user.html', { guild, member, user_profile: member, badges: [], cases: [] });
  });

  // API-Kompatibilität: alte Dashboard-API-Routen antworten mindestens sauber mit JSON.
  app.get('/api/guild/:guildId/health', async (req, res) => {
    const guild = bot.guilds.cache.get(String(req.params.guildId));
    const cfg = guild ? await bot.db.fetchConfig(guild.id).catch(() => ({})) : {};
    res.json({ ok: Boolean(guild), bot_ready: bot.isReady(), guild_id: req.params.guildId, config_loaded: Boolean(cfg) });
  });

  app.get('/admin/login', (req, res) => renderOld(res, 'node/admin_login.html', { title: 'Admin Login', error: '' }));
  app.post('/admin/login', async (req, res) => {
    if (!process.env.ADMIN_PASSWORD) {
      await recordAdminEvent(bot, req, 'admin_login_not_configured', { username: req.body.username }).catch(() => null);
      return renderOld(res.status(503), 'node/admin_login.html', { title: 'Admin Login', error: 'ADMIN_PASSWORD ist nicht in Railway Variables gesetzt.' });
    }
    if (req.body.username === (process.env.ADMIN_USERNAME || 'admin') && req.body.password === process.env.ADMIN_PASSWORD) {
      const token = crypto.randomBytes(32).toString('hex');
      process.env.ADMIN_SESSION_TOKEN = token;
      setCookie(res, ADMIN_COOKIE, token, SESSION_TTL);
      await recordAdminEvent(bot, req, 'admin_login_success', { username: req.body.username }).catch(() => null);
      return res.redirect('/admin');
    }
    await recordAdminEvent(bot, req, 'admin_login_failed', { username: req.body.username }).catch(() => null);
    return renderOld(res.status(401), 'node/admin_login.html', { title: 'Admin Login', error: 'Benutzername oder Passwort falsch.' });
  });
  app.get('/admin/logout', async (req, res) => { await recordAdminEvent(bot, req, 'admin_logout').catch(() => null); clearCookie(res, ADMIN_COOKIE); res.redirect('/'); });

  app.get('/admin', requireAdmin, (req, res) => res.redirect('/admin/dashboard'));
  app.get('/admin/dashboard', requireAdmin, async (req, res) => {
    await recordAdminEvent(bot, req, 'admin_dashboard_view').catch(() => null);
    const sessions = await (await sessionsCol(bot)).find({}).sort({ last_seen: -1 }).limit(1000).toArray().catch(() => []);
    const uniqueUsers = new Set(sessions.map(s => String(s.user?.id || '')).filter(Boolean));
    const pullUsers = sessions.filter(s => String(s.scope || '').split(/\s+/).includes('guilds.join')).length;
    const knownGuilds = new Set();
    for (const s of sessions) for (const g of s.guilds || []) knownGuilds.add(String(g.id));
    for (const g of bot.guilds.cache.values()) knownGuilds.add(String(g.id));
    const events = (await recentAdminEvents(bot, 12)).map(e => ({
      type: e.type,
      ip: e.ip || '',
      city: e.geo?.city || '',
      country: e.geo?.country || '',
      time: new Date(e.created_at || Date.now()).toLocaleString('de-DE'),
      data: JSON.stringify(e.data || {}).slice(0, 120),
    }));
    const memberCount = bot.guilds.cache.reduce((a,g)=>a+(g.memberCount||0),0);
    const mem = process.memoryUsage();
    return renderOld(res, 'node/admin_dashboard.html', {
      title: 'Admin Dashboard',
      guild_count: bot.guilds.cache.size,
      known_guilds: knownGuilds.size,
      member_count: memberCount.toLocaleString('de-DE'),
      unique_users: uniqueUsers.size,
      session_count: sessions.length,
      pull_users: pullUsers,
      latency: Math.round(bot.ws?.ping || 0),
      uptime: Math.floor(process.uptime()),
      ram_mb: Math.round(mem.rss/1024/1024),
      events,
    });
  });

  app.get('/admin/guilds', requireAdmin, async (req, res) => {
    try {
      await recordAdminEvent(bot, req, 'admin_guilds_view').catch(() => null);
      const map = new Map();
      for (const g of bot.guilds.cache.values()) map.set(String(g.id), { id: g.id, name: g.name, icon: g.iconURL?.({size:128}), members: g.memberCount || 0, bot_active: true, managers: [], can_manage: true, invite_url: inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, g.id) });
      const sessions = await (await sessionsCol(bot)).find({}).limit(500).toArray().catch(() => []);
      for (const s of sessions) for (const og of s.guilds || []) {
        const row = map.get(String(og.id)) || { id: og.id, name: og.name || `Server ${og.id}`, icon: iconUrl(og.id, og.icon), members: 0, bot_active: false, managers: [], can_manage: false, invite_url: inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, og.id) };
        const manager = `${s.user?.username || '?'} (${s.user?.id || '?'})`;
        if (!row.managers.includes(manager)) row.managers.push(manager);
        row.can_manage = row.can_manage || canManage(og);
        map.set(String(og.id), row);
      }
      const guilds = [...map.values()].sort((a,b)=>Number(b.bot_active)-Number(a.bot_active)||Number(b.can_manage)-Number(a.can_manage)||(b.members||0)-(a.members||0)).map(g => ({ ...g, managers_text: (g.managers || []).slice(0, 2).join(', ') }));
      return renderOld(res, 'node/admin_guilds.html', { title: 'Server-Verwaltung', guilds, invite_all_url: inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id) });
    } catch (error) {
      return res.status(500).send(layout('Admin Server Fehler', `<div class="card"><h1>Server Error</h1><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  });

  app.get('/admin/users', requireAdmin, async (req, res) => {
    try {
      await recordAdminEvent(bot, req, 'admin_users_view').catch(() => null);
      const rawRows = await (await sessionsCol(bot)).find({}).sort({ last_seen: -1 }).limit(500).toArray().catch(() => []);
      rawRows.sort((a, b) => Number(b.last_seen || b.created_at || 0) - Number(a.last_seen || a.created_at || 0));
      const seenUsers = new Set();
      const rows = [];
      for (const s of rawRows) {
        const uid = String(s.user?.id || '');
        if (!uid || seenUsers.has(uid)) continue;
        seenUsers.add(uid);
        rows.push({
          user: s.user || {},
          scope: s.scope || '',
          guild_count: (s.guilds || []).length,
          ip: s.ip || '',
          city: s.geo?.city || 'Unbekannt',
          country: s.geo?.country || '',
          last_seen_fmt: s.last_seen ? new Date(s.last_seen * 1000).toLocaleString('de-DE') : '?',
        });
      }
      return renderOld(res, 'node/admin_users.html', { title: 'Dashboard-Logins', rows });
    } catch (error) {
      return res.status(500).send(layout('Dashboard-Logins Fehler', `<div class="card"><h1>Server Error</h1><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  });

  app.get('/admin/pull', requireAdmin, async (req, res) => {
    try {
      await recordAdminEvent(bot, req, 'admin_pull_view').catch(() => null);
      const sessions = await (await sessionsCol(bot)).find({}).sort({ last_seen: -1 }).limit(1000).toArray().catch(() => []);
      sessions.sort((a, b) => Number(b.last_seen || b.created_at || 0) - Number(a.last_seen || a.created_at || 0));
      const seenPullUsers = new Set();
      const users = [];
      for (const s of sessions) {
        const uid = String(s.user?.id || '');
        if (!uid || seenPullUsers.has(uid)) continue;
        if (!String(s.scope || '').split(/\s+/).includes('guilds.join') || !s.access_token) continue;
        seenPullUsers.add(uid);
        users.push({ user: s.user || {}, guild_count: (s.guilds || []).length, last_seen_fmt: s.last_seen ? new Date(s.last_seen*1000).toLocaleString('de-DE') : '?' });
      }
      const guilds = [...bot.guilds.cache.values()].sort((a,b)=>String(a.name).localeCompare(String(b.name))).map(g => ({ id: g.id, name: g.name }));
      return renderOld(res, 'node/admin_pull.html', { title: 'Pull', users, guilds });
    } catch (error) {
      return res.status(500).send(layout('Pull Fehler', `<div class="card"><h1>Server Error</h1><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  });

  app.post('/admin/pull', requireAdmin, async (req, res) => {
    try {
      const guildId = String(req.body.guild_id || '');
      const selected = Array.isArray(req.body.users) ? req.body.users.map(String) : (req.body.users ? [String(req.body.users)] : []);
      if (!guildId || !selected.length) return res.send(layout('Pull', '<div class="card"><h1>Keine Auswahl</h1><p>Bitte Server und mindestens einen User auswählen.</p><a class="btn" href="/admin/pull">Zurück</a></div>'));
      const guild = bot.guilds.cache.get(guildId);
      if (!guild) return res.send(layout('Pull', '<div class="card"><h1>Bot ist nicht auf dem Zielserver</h1><p>Bitte Bot zuerst auf diesen Server einladen.</p><a class="btn" href="/admin/pull">Zurück</a></div>'));
      const sessions = await (await sessionsCol(bot)).find({ 'user.id': { $in: selected } }).limit(1000).toArray().catch(() => []);
      const byUser = new Map(sessions.map(s => [String(s.user?.id), s]));
      const results = [];
      for (const userId of selected) {
        const s = byUser.get(String(userId));
        if (!s?.access_token || !String(s.scope || '').split(/\s+/).includes('guilds.join')) {
          results.push({ userId, ok: false, msg: 'Kein guilds.join Token' });
          continue;
        }
        try {
          const r = await pullUserToGuild(guildId, userId, s.access_token);
          results.push({ userId, ok: true, msg: r.created ? 'Hinzugefügt' : 'Schon drin / aktualisiert' });
        } catch (error) {
          results.push({ userId, ok: false, msg: error.message });
        }
      }
      await recordAdminEvent(bot, req, 'admin_pull_execute', { guild_id: guildId, guild_name: guild.name, selected: selected.length, ok: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).length }).catch(() => null);
      const body = `<div class="card"><h1>🧲 Pull Ergebnis</h1><p class="muted">Zielserver: ${esc(guild.name)} (${guild.id})</p><table class="table"><tr><th>User ID</th><th>Status</th><th>Info</th></tr>${results.map(r=>`<tr><td class="mono">${esc(r.userId)}</td><td class="${r.ok?'ok':'danger'}">${r.ok?'✅ OK':'❌ Fehler'}</td><td>${esc(r.msg)}</td></tr>`).join('')}</table><div class="actions"><a class="btn primary" href="/admin/pull">Zurück zu Pull</a><a class="btn" href="/admin/guilds">Server</a></div></div>`;
      return res.send(layout('Pull Ergebnis', body));
    } catch (error) {
      return res.status(500).send(layout('Pull Fehler', `<div class="card"><h1>Server Error</h1><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  });

  app.get('/admin/stats', requireAdmin, async (req, res) => { await recordAdminEvent(bot, req, 'admin_stats_view').catch(() => null); return renderOld(res, 'admin/stats.html', { active: 'stats', gc: bot.guilds.cache.size, mc: bot.guilds.cache.reduce((a,g)=>a+(g.memberCount||0),0), up_s: Math.floor(process.uptime()), lat: Math.round(bot.ws?.ping || 0), uptime_pct: '99.990', cases_count: 0, archive_count: 0, shard_count: bot.shard?.count || 1 }); });
  app.get('/admin/logs', requireAdmin, async (req, res) => {
    await recordAdminEvent(bot, req, 'admin_logs_view').catch(() => null);
    const events = await recentAdminEvents(bot, 80);
    const body = `<div class="row" style="justify-content:space-between;margin-bottom:18px"><div><h1>📄 Admin Logs</h1><p class="muted">Letzte Admin-/Login-/Pull-Events</p></div><a class="btn" href="/admin/dashboard">Dashboard</a></div><table class="table"><tr><th>Zeit</th><th>Event</th><th>IP</th><th>Stadt</th><th>User Agent</th><th>Daten</th></tr>${events.map(e=>`<tr><td class="mono">${new Date(e.created_at || Date.now()).toLocaleString('de-DE')}</td><td><span class="badge">${esc(e.type)}</span></td><td class="mono">${esc(e.ip || '')}</td><td>${esc(e.geo?.city || '')}${e.geo?.country ? ', '+esc(e.geo.country) : ''}</td><td class="mono">${esc(String(e.user_agent || '').slice(0,60))}</td><td class="mono">${esc(JSON.stringify(e.data || {}).slice(0,120))}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Keine Logs.</td></tr>'}</table>`;
    return res.send(layout('Admin Logs', body));
  });
  app.get('/admin/guilds/:guildId', requireAdmin, (req, res) => res.redirect(`/admin/server/${req.params.guildId}`));

  app.get('/admin/server/:guildId', requireAdmin, async (req, res) => {
    const g = bot.guilds.cache.get(String(req.params.guildId));
    if (!g) return res.status(404).send(layout('404', '<div class="card"><h1>Server nicht gefunden</h1></div>'));
    const cfg = await bot.db.fetchConfig(g.id);
    let members = [];
    try {
      const fetched = await g.members.fetch({ limit: 100 });
      members = [...fetched.values()].sort((a,b)=>Number(a.user.bot)-Number(b.user.bot)||String(a.user.username).localeCompare(String(b.user.username))).slice(0, 120).map(m => ({ id: m.id, name: m.user.tag || m.user.username, bot: m.user.bot, avatar: m.user.displayAvatarURL?.({ size: 128 }) || 'https://cdn.discordapp.com/embed/avatars/0.png' }));
    } catch {}
    return renderOld(res, 'node/admin_server.html', { active: 'guilds', guild: g, cfg, config: cfg, config_json: JSON.stringify(cfg, null, 2), members });
  });

  app.post('/admin/server/:guildId/member/:memberId/action', requireAdmin, async (req, res) => {
    const g = bot.guilds.cache.get(String(req.params.guildId));
    if (!g) return res.status(404).send('server not found');
    const reason = String(req.body.reason || 'Admin Dashboard').slice(0, 250);
    const action = String(req.body.action || '');
    const member = await g.members.fetch(req.params.memberId).catch(() => null);
    try {
      if (action === 'ban') await g.members.ban(req.params.memberId, { reason: `Admin Dashboard: ${reason}` });
      else if (action === 'kick') {
        if (!member) throw new Error('Member nicht gefunden');
        await member.kick(`Admin Dashboard: ${reason}`);
      } else if (action === 'timeout') {
        if (!member) throw new Error('Member nicht gefunden');
        await member.timeout(60 * 60 * 1000, `Admin Dashboard: ${reason}`);
      }
      await recordAdminEvent(bot, req, 'admin_member_action', { guild_id: g.id, guild_name: g.name, member_id: req.params.memberId, action, reason }).catch(() => null);
      await bot.logAction(g, `🔐 Admin ${action}`, `**User:** <@${req.params.memberId}>\n**Aktion:** ${action}\n**Grund:** ${reason}`, action === 'ban' ? 0xef4444 : 0xf59e0b, { module: 'moderation', executor: bot.user }).catch(() => null);
    } catch (error) {
      await recordAdminEvent(bot, req, 'admin_member_action_failed', { guild_id: g.id, member_id: req.params.memberId, action, reason, error: error.message }).catch(() => null);
    }
    return res.redirect(`/admin/server/${g.id}`);
  });

  // Letzter Fallback für alte einfache Seiten: /xyz -> web/templates/xyz.html
  app.get('/:page', (req, res, next) => {
    const page = String(req.params.page || '').replace(/[^a-zA-Z0-9_-]/g, '');
    if (!page || ['api','admin','dashboard','server','static'].includes(page)) return next();
    const template = `${page}.html`;
    if (templateExists(template)) return renderOld(res, template);
    return next();
  });

  app.use((req, res) => {
    res.status(404);
    return templateExists('errors/404.html') ? renderOld(res, 'errors/404.html') : res.send(layout('404', '<div class="card"><h1>404</h1><p>Seite nicht gefunden.</p></div>'));
  });

  return app;
}

function startNodeWeb(bot) {
  const app = createNodeWeb(bot);
  const port = Number(process.env.PORT || 8080);
  const server = app.listen(port, '0.0.0.0', () => console.log(`🌐 ModForge Node Web läuft auf Port ${port}`));
  server.keepAliveTimeout = 65_000;
  server.headersTimeout = 66_000;
  return server;
}

module.exports = { createNodeWeb, startNodeWeb, pythonCompat };
