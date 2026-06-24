// ModForge Node Web Dashboard – Bot + Web zusammen deploybar
const express = require('express');
const nunjucks = require('nunjucks');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { URLSearchParams } = require('node:url');

const SESSION_COOKIE = 'modforge_session';
const ADMIN_COOKIE = 'modforge_admin';
const SESSION_TTL = Number(process.env.DASHBOARD_SESSION_TTL || 30 * 24 * 3600);
const DISCORD_API = 'https://discord.com/api/v10';
// Discord OAuth2 Scopes: space-separated in URL, shown here as requested: identify,guilds,guilds.join
const OAUTH_SCOPES = 'identify guilds guilds.join';

function esc(value = '') {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
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

function setCookie(res, name, value, maxAge = SESSION_TTL) {
  const secure = String(process.env.DASHBOARD_BASE_URL || '').startsWith('https://') || process.env.NODE_ENV === 'production';
  const parts = [`${name}=${encodeURIComponent(value)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax', `Max-Age=${maxAge}`];
  if (secure) parts.push('Secure');
  res.append('Set-Cookie', parts.join('; '));
}

function clearCookie(res, name) {
  res.append('Set-Cookie', `${name}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`);
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

function layout(title, body, user = null) {
  return `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)} – ModForge</title><style>
:root{color-scheme:dark;--bg:#070712;--card:rgba(255,255,255,.055);--line:rgba(255,255,255,.11);--fg:#f8fafc;--muted:#94a3b8;--blue:#60a5fa;--green:#4ade80;--red:#fb7185;--yellow:#fbbf24;--violet:#8b5cf6}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#1e1b4b,#070712 55%);color:var(--fg);font-family:Inter,system-ui,Segoe UI,sans-serif;min-height:100vh}a{color:inherit;text-decoration:none}.top{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:rgba(5,5,16,.85);border-bottom:1px solid var(--line);position:sticky;top:0;backdrop-filter:blur(18px);z-index:10}.brand{display:flex;align-items:center;gap:10px;font-weight:900}.logo{width:36px;height:36px;border-radius:12px;background:linear-gradient(135deg,var(--blue),var(--violet));display:grid;place-items:center}.user{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:.9rem}.user img{width:32px;height:32px;border-radius:50%}.wrap{max-width:1180px;margin:0 auto;padding:28px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.25)}.row{display:flex;align-items:center;gap:12px}.grow{flex:1;min-width:0}.muted{color:var(--muted)}.btn{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:rgba(255,255,255,.07);padding:9px 13px;border-radius:12px;font-weight:700;font-size:.85rem}.btn:hover{border-color:rgba(96,165,250,.45)}.primary{background:linear-gradient(135deg,#2563eb,#7c3aed);border:0}.danger{background:rgba(239,68,68,.14);border-color:rgba(239,68,68,.25);color:#fecaca}.ok{color:var(--green)}.warn{color:var(--yellow)}.badge{font-size:.68rem;padding:4px 9px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.05);font-weight:800}.servericon{width:48px;height:48px;border-radius:15px;object-fit:cover;background:rgba(255,255,255,.08);display:grid;place-items:center;font-weight:900}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.input{width:100%;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:12px;color:var(--fg);padding:10px 12px;margin:6px 0 12px}.table{width:100%;border-collapse:collapse}.table td,.table th{padding:12px;border-bottom:1px solid var(--line);text-align:left}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem;color:var(--muted)}h1{margin:0 0 8px}h2{margin:0 0 12px;font-size:1.1rem}</style></head><body><header class="top"><a class="brand" href="/"><span class="logo">🛡️</span><span>ModForge</span></a><nav class="actions"><a class="btn" href="/dashboard">Dashboard</a><a class="btn" href="/admin">Admin</a><a class="btn primary" href="/invite">Bot einladen</a>${user ? `<span class="user"><img src="${esc(user.avatar_url)}"><span>${esc(user.username)}</span></span>` : `<a class="btn" href="/login">Login</a>`}</nav></header><main class="wrap">${body}</main></body></html>`;
}

async function sessionsCol(bot) {
  await bot.db.connect();
  const col = bot.db.db.collection('dashboard_sessions');
  await col.createIndex({ sid: 1 }, { unique: true }).catch(() => null);
  await col.createIndex({ expires_at: 1 }).catch(() => null);
  return col;
}

async function getSession(req, bot) {
  const sid = parseCookies(req)[SESSION_COOKIE];
  if (!sid) return null;
  const col = await sessionsCol(bot);
  const doc = await col.findOne({ sid });
  if (!doc || (doc.expires_at && doc.expires_at < Date.now() / 1000)) return null;
  await col.updateOne({ sid }, { $set: { last_seen: Date.now() / 1000 } }).catch(() => null);
  return doc;
}

function requireAdmin(req, res, next) {
  const cookies = parseCookies(req);
  if (cookies[ADMIN_COOKIE] === process.env.ADMIN_SESSION_TOKEN) return next();
  return res.redirect('/admin/login');
}

function canManage(guild) {
  const p = Number(guild.permissions || 0);
  return Boolean(guild.owner || (p & 0x8) || (p & 0x20));
}

function createNodeWeb(bot) {
  const app = express();
  const templatesDir = path.join(__dirname, 'templates');
  const env = nunjucks.configure(templatesDir, { autoescape: true, express: app, noCache: process.env.NODE_ENV !== 'production' });
  env.addGlobal('url_for', (name) => name === 'static' ? '/static' : `/${name}`);
  env.addFilter('tojson', (value) => JSON.stringify(value ?? null));
  env.addFilter('sum', (arr, attr) => Array.isArray(arr) ? arr.reduce((n, x) => n + Number(attr ? x?.[attr] : x || 0), 0) : 0);
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

  function renderOld(res, template, ctx = {}) {
    try {
      return res.render(template, publicContext(ctx));
    } catch (error) {
      if (templateExists(template)) return res.send(legacyFallbackRender(template, error));
      return res.status(500).send(layout('Template Fehler', `<div class="card"><h1>Template Fehler</h1><p class="muted">${esc(template)}</p><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  }

  function templateExists(template) {
    return fs.existsSync(path.join(templatesDir, template));
  }

  function renderTemplateOr404(res, template, ctx = {}) {
    if (!templateExists(template)) return res.status(404).send(layout('404', '<div class="card"><h1>404</h1><p>Seite nicht gefunden.</p></div>'));
    return renderOld(res, template, ctx);
  }

  app.get('/health', (req, res) => res.json({ ok: true, bot_ready: bot.isReady(), guilds: bot.guilds.cache.size, uptime: Math.floor(process.uptime()), ts: new Date().toISOString() }));
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
    const base = (process.env.DASHBOARD_BASE_URL || `${req.protocol}://${req.get('host')}`).replace(/\/$/, '');
    const state = crypto.randomBytes(16).toString('hex');
    setCookie(res, 'modforge_oauth_state', state, 600);
    const params = new URLSearchParams({ client_id: clientId, redirect_uri: `${base}/dashboard/auth/callback`, response_type: 'code', scope: OAUTH_SCOPES, prompt: 'consent', state });
    res.redirect(`https://discord.com/oauth2/authorize?${params.toString()}`);
  });

  app.get('/dashboard/auth/callback', async (req, res) => {
    try {
      const cookies = parseCookies(req);
      if (!req.query.code || req.query.state !== cookies.modforge_oauth_state) return res.redirect('/login?error=state');
      const base = (process.env.DASHBOARD_BASE_URL || `${req.protocol}://${req.get('host')}`).replace(/\/$/, '');
      const body = new URLSearchParams({ client_id: process.env.DISCORD_CLIENT_ID || bot.user?.id, client_secret: process.env.DISCORD_CLIENT_SECRET || '', grant_type: 'authorization_code', code: String(req.query.code), redirect_uri: `${base}/dashboard/auth/callback` });
      const tokenRes = await fetch(`${DISCORD_API}/oauth2/token`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body });
      const token = await tokenRes.json();
      if (!token.access_token) throw new Error(JSON.stringify(token).slice(0, 200));
      const user = await discordApi('/users/@me', token.access_token);
      const guilds = await discordApi('/users/@me/guilds', token.access_token).catch((error) => {
        console.warn('Discord guild fetch failed:', error.message);
        return [];
      });
      const sid = crypto.randomBytes(32).toString('hex');
      const session = { sid, access_token: token.access_token, refresh_token: token.refresh_token, scope: token.scope || OAUTH_SCOPES, token_expires_at: Date.now()/1000 + Number(token.expires_in || SESSION_TTL), created_at: Date.now()/1000, last_seen: Date.now()/1000, expires_at: Date.now()/1000 + SESSION_TTL, user: { id: user.id, username: user.username || user.global_name || 'Discord User', global_name: user.global_name, avatar_url: userAvatar(user) }, guilds: Array.isArray(guilds) ? guilds : [] };
      await (await sessionsCol(bot)).updateOne({ sid }, { $set: session }, { upsert: true });
      console.log(`OAuth login OK: ${session.user.username} (${session.user.id}) scopes=${session.scope} guilds=${session.guilds.length}`);
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
    // Wenn nach Login noch keine Server da sind: sofort Discord-Guilds neu laden und in DB speichern.
    if ((!Array.isArray(s.guilds) || !s.guilds.length) && s.access_token) {
      const freshGuilds = await discordApi('/users/@me/guilds', s.access_token).catch(() => []);
      if (Array.isArray(freshGuilds) && freshGuilds.length) {
        s.guilds = freshGuilds;
        await (await sessionsCol(bot)).updateOne({ sid: s.sid }, { $set: { guilds: freshGuilds, guilds_refreshed_at: Date.now()/1000, last_seen: Date.now()/1000 } }).catch(() => null);
      }
    }
    const botGuildIds = new Set(bot.guilds.cache.map(g => String(g.id)));
    // Zeige ALLE Discord-Server des Users, nicht nur managebare. Managebare bekommen Bot-Invite/Öffnen.
    const guilds = (s.guilds || []).map(g => ({
      ...g,
      id: String(g.id),
      name: g.name || `Server ${g.id}`,
      can_manage: canManage(g),
      bot_active: botGuildIds.has(String(g.id)),
      icon_url: iconUrl(g.id, g.icon, 0),
    })).sort((a,b)=>Number(b.bot_active)-Number(a.bot_active)||Number(b.can_manage)-Number(a.can_manage)||String(a.name).localeCompare(String(b.name)));

    const noGuildHelp = !guilds.length ? `<div class="card" style="margin-bottom:16px;border-color:rgba(251,191,36,.35)"><h2>⚠️ Keine Discord-Server empfangen</h2><p class="muted">Discord hat für deine OAuth-Session keine Guilds geliefert. Klicke auf Neu anmelden mit Scopes und bestätige <span class="mono">identify guilds guilds.join</span>.</p><div class="actions"><a class="btn primary" href="/dashboard/login?force=1">Neu anmelden mit Scopes</a><a class="btn" href="/dashboard/refresh">Server neu laden</a></div></div>` : '';
    const body = `${noGuildHelp}<div class="row" style="justify-content:space-between;margin-bottom:18px;align-items:flex-start"><div><h1>Dashboard</h1><p class="muted">Alle Server aus deinem Discord-Login · OAuth Scopes: <span class="mono">identify guilds guilds.join</span></p></div><div class="actions"><a class="btn" href="/dashboard/refresh">🔄 Server neu laden</a><a class="btn primary" target="_blank" href="${inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id)}">➕ Bot einladen</a></div></div>
    <div class="grid">${guilds.map(g => `<div class="card"><div class="row"><img class="servericon" src="${esc(g.icon_url)}"><div class="grow"><b>${esc(g.name)}</b><div class="mono">${esc(g.id)}</div><div class="muted">${g.can_manage ? 'Du kannst diesen Server verwalten' : 'Keine Admin/Manage-Server Rechte erkannt'}</div></div><span class="badge ${g.bot_active?'ok':(g.can_manage?'warn':'')}">${g.bot_active?'✅ Bot aktiv':(g.can_manage?'➕ Bot fehlt':'👁️ Nur sichtbar')}</span></div><div class="actions">${g.bot_active ? `<a class="btn primary" href="/dashboard/${g.id}">Öffnen</a>` : (g.can_manage ? `<a class="btn primary" target="_blank" href="${inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, g.id)}">Hinzufügen</a>` : `<span class="btn" style="opacity:.55;cursor:not-allowed">Keine Rechte</span>`)}</div></div>`).join('') || '<div class="card"><h2>Keine Server gefunden</h2><p class="muted">Klicke auf „Server neu laden“. Falls weiter nichts erscheint, prüfe im Discord Developer Portal, dass OAuth2 Redirect und Scopes stimmen.</p><a class="btn primary" href="/dashboard/refresh">Neu laden</a></div>'}</div>`;
    res.send(layout('Dashboard', body, s.user));
  });

  app.get('/dashboard/:guildId/:subpage', async (req, res) => {
    const s = await getSession(req, bot);
    if (!s) return res.redirect('/login');
    const allowed = (s.guilds || []).some(g => String(g.id) === String(req.params.guildId) && canManage(g));
    if (!allowed) return res.status(403).send(layout('Forbidden', '<div class="card"><h1>403</h1><p>Kein Zugriff.</p></div>', s.user));
    const guild = bot.guilds.cache.get(String(req.params.guildId));
    if (!guild) return res.redirect(inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, req.params.guildId));
    const cfg = await bot.db.fetchConfig(guild.id);
    const map = { 'staff-applications': 'staff_applications' };
    const sub = map[req.params.subpage] || req.params.subpage;
    const allowedPages = new Set(['activity_feed','appeals','audit','automod','autonick','autoresponse','backup','badges','beta','cases','design','embed','livefeed','logs','members','modules','overview','roles','security','settings','staff_applications','stats','templates','tempvoice','tickets','user_risk','verification','warns','welcome','whitelist']);
    if (!allowedPages.has(sub)) return res.status(404).send(layout('404', '<div class="card"><h1>Seite nicht gefunden</h1></div>', s.user));
    return renderOld(res, `dashboard/${sub}.html`, { guild, cfg, user: s.user, active: sub, overview: {}, cases: [], warns: [], members: [], activities: [] });
  });

  app.get('/dashboard/:guildId', async (req, res) => {
    const s = await getSession(req, bot);
    if (!s) return res.redirect('/login');
    const allowed = (s.guilds || []).some(g => String(g.id) === String(req.params.guildId) && canManage(g));
    if (!allowed) return res.status(403).send(layout('Forbidden', '<div class="card"><h1>403</h1><p>Kein Zugriff.</p></div>', s.user));
    const guild = bot.guilds.cache.get(String(req.params.guildId));
    if (!guild) return res.send(layout('Bot fehlt', `<div class="card"><h1>Bot fehlt</h1><p class="muted">Der Bot ist noch nicht auf diesem Server.</p><a class="btn primary" target="_blank" href="${inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, req.params.guildId)}">Bot hinzufügen</a></div>`, s.user));
    const cfg = await bot.db.fetchConfig(guild.id);
    return renderOld(res, 'dashboard/overview.html', { guild, cfg, user: s.user, active: 'overview', overview: {} });
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
  app.get('/api/guild/:guildId/config', async (req, res) => res.json(await bot.db.fetchConfig(req.params.guildId).catch(() => ({}))));
  app.post('/api/guild/:guildId/config', async (req, res) => { const cfg = await bot.db.fetchConfig(req.params.guildId).catch(() => ({})); Object.assign(cfg, req.body || {}); await bot.db.setConfig(req.params.guildId, cfg); res.json({ ok: true, config: cfg }); });
  app.get('/api/guild/:guildId/activity', async (req, res) => res.json([]));
  app.get('/api/guild/:guildId/:module', async (req, res) => res.json({ ok: true, module: req.params.module, guild_id: req.params.guildId }));
  app.post('/api/guild/:guildId/:module', async (req, res) => res.json({ ok: true, module: req.params.module, guild_id: req.params.guildId }));
  app.get('/api/guild/:guildId/:module/:rest(*)', async (req, res) => res.json({ ok: true, module: req.params.module, path: req.params.rest }));
  app.post('/api/guild/:guildId/:module/:rest(*)', async (req, res) => res.json({ ok: true, module: req.params.module, path: req.params.rest }));
  app.delete('/api/guild/:guildId/:module/:rest(*)', async (req, res) => res.json({ ok: true }));

  app.get('/admin/login', (req, res) => renderOld(res, 'admin/login.html', { error: null }));
  app.post('/admin/login', (req, res) => {
    if (req.body.username === (process.env.ADMIN_USERNAME || 'admin') && req.body.password === process.env.ADMIN_PASSWORD) {
      const token = crypto.randomBytes(32).toString('hex');
      process.env.ADMIN_SESSION_TOKEN = token;
      setCookie(res, ADMIN_COOKIE, token, SESSION_TTL);
      return res.redirect('/admin');
    }
    return renderOld(res.status(401), 'admin/login.html', { error: 'Benutzername oder Passwort falsch.' });
  });
  app.get('/admin/logout', (req, res) => { clearCookie(res, ADMIN_COOKIE); res.redirect('/'); });

  app.get('/admin', requireAdmin, (req, res) => res.redirect('/admin/dashboard'));
  app.get('/admin/dashboard', requireAdmin, (req, res) => renderOld(res, 'admin/dashboard.html', { active: 'dashboard', gc: bot.guilds.cache.size, mc: bot.guilds.cache.reduce((a,g)=>a+(g.memberCount||0),0), up_s: Math.floor(process.uptime()), lat: Math.round(bot.ws?.ping || 0), cases_count: 0, archive_count: 0, bot_ready: bot.isReady(), shard_count: bot.shard?.count || 1, bot_user: bot.user }));

  app.get('/admin/guilds', requireAdmin, async (req, res) => {
    try {
      const map = new Map();
      for (const g of bot.guilds.cache.values()) map.set(String(g.id), { id: g.id, name: g.name, icon: g.iconURL?.({size:128}), members: g.memberCount || 0, bot_active: true, managers: [] });
      const sessions = await (await sessionsCol(bot)).find({}).limit(500).toArray().catch(() => []);
      for (const s of sessions) for (const og of s.guilds || []) {
        const row = map.get(String(og.id)) || { id: og.id, name: og.name || `Server ${og.id}`, icon: iconUrl(og.id, og.icon), members: 0, bot_active: false, managers: [] };
        const manager = `${s.user?.username || '?'} (${s.user?.id || '?'})`;
        if (!row.managers.includes(manager)) row.managers.push(manager);
        row.can_manage = row.can_manage || canManage(og);
        map.set(String(og.id), row);
      }
      const rows = [...map.values()].sort((a,b)=>Number(b.bot_active)-Number(a.bot_active)||Number(b.can_manage)-Number(a.can_manage)||(b.members||0)-(a.members||0));
      const body = `<div class="row" style="justify-content:space-between;margin-bottom:18px"><div><h1>🏠 Server-Verwaltung</h1><p class="muted">Alle Bot-Server + alle Server aus Dashboard-Logins</p></div><a class="btn primary" target="_blank" href="${inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id)}">➕ Bot zu neuem Server</a></div><div class="grid">${rows.map(g=>`<div class="card"><div class="row"><img class="servericon" src="${esc(g.icon || 'https://cdn.discordapp.com/embed/avatars/0.png')}"><div class="grow"><b>${esc(g.name)}</b><div class="mono">${esc(g.id)}</div><div class="muted">${esc((g.managers||[]).slice(0,2).join(', '))}</div></div><span class="badge ${g.bot_active?'ok':(g.can_manage?'warn':'')}">${g.bot_active?'✅ Aktiv':(g.can_manage?'➕ Bot fehlt':'👁️ Bekannt')}</span></div><div class="actions">${g.bot_active?`<a class="btn primary" href="/admin/server/${g.id}">Öffnen</a>`:(g.can_manage?`<a class="btn primary" target="_blank" href="${inviteUrl(process.env.DISCORD_CLIENT_ID || bot.user?.id, g.id)}">Hinzufügen</a>`:`<span class="btn" style="opacity:.55">Keine Rechte</span>`)}</div></div>`).join('') || '<div class="card">Keine Server gefunden.</div>'}</div>`;
      return res.send(layout('Server-Verwaltung', body));
    } catch (error) {
      return res.status(500).send(layout('Admin Server Fehler', `<div class="card"><h1>Server Error</h1><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  });

  app.get('/admin/users', requireAdmin, async (req, res) => {
    try {
      const rows = await (await sessionsCol(bot)).find({}).sort({ last_seen: -1 }).limit(500).toArray().catch(() => []);
      const body = `<div class="row" style="justify-content:space-between;margin-bottom:18px"><div><h1>👥 Dashboard-Logins</h1><p class="muted">Persistente Discord OAuth Sessions aus MongoDB</p></div><a class="btn" href="/admin/guilds">Server anzeigen</a></div><table class="table"><tr><th>User</th><th>ID</th><th>Scopes</th><th>Server</th><th>Last seen</th></tr>${rows.map(s=>`<tr><td><div class="row"><img class="servericon" style="width:34px;height:34px;border-radius:50%" src="${esc(s.user?.avatar_url || 'https://cdn.discordapp.com/embed/avatars/0.png')}"><b>${esc(s.user?.username || '?')}</b></div></td><td class="mono">${esc(s.user?.id || '?')}</td><td class="mono">${esc(s.scope || '')}</td><td>${(s.guilds || []).length}</td><td class="mono">${s.last_seen ? new Date(s.last_seen * 1000).toLocaleString('de-DE') : '?'}</td></tr>`).join('') || '<tr><td colspan="5" class="muted">Keine Logins gespeichert.</td></tr>'}</table>`;
      return res.send(layout('Dashboard-Logins', body));
    } catch (error) {
      return res.status(500).send(layout('Dashboard-Logins Fehler', `<div class="card"><h1>Server Error</h1><pre class="mono">${esc(error.stack || error.message)}</pre></div>`));
    }
  });

  app.get('/admin/stats', requireAdmin, (req, res) => renderOld(res, 'admin/stats.html', { active: 'stats', gc: bot.guilds.cache.size, mc: bot.guilds.cache.reduce((a,g)=>a+(g.memberCount||0),0), up_s: Math.floor(process.uptime()), lat: Math.round(bot.ws?.ping || 0), uptime_pct: '99.990', cases_count: 0, archive_count: 0, shard_count: bot.shard?.count || 1 }));
  app.get('/admin/logs', requireAdmin, (req, res) => renderOld(res, 'admin/logs.html', { active: 'logs', logs: [] }));
  app.get('/admin/guilds/:guildId', requireAdmin, (req, res) => res.redirect(`/admin/server/${req.params.guildId}`));

  app.get('/admin/server/:guildId', requireAdmin, async (req, res) => {
    const g = bot.guilds.cache.get(String(req.params.guildId));
    if (!g) return res.status(404).send(layout('404', '<div class="card"><h1>Server nicht gefunden</h1></div>'));
    const cfg = await bot.db.fetchConfig(g.id);
    return renderOld(res, 'admin/guild_detail.html', { active: 'guilds', guild: g, cfg, config: cfg, config_json: JSON.stringify(cfg, null, 2), cases: [], active_modules: 0 });
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
  const port = Number(process.env.PORT || 7860);
  app.listen(port, '0.0.0.0', () => console.log(`🌐 ModForge Node Web läuft auf Port ${port}`));
}

module.exports = { createNodeWeb, startNodeWeb };
