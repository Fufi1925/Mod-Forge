/**
 * ╔══════════════════════════════════════════════════════════════╗
 * ║                    ModForge Discord Bot                      ║
 * ║              Production-Ready · discord.js v14               ║
 * ║  Requires: Node.js 18+, PostgreSQL, environment variables    ║
 * ╚══════════════════════════════════════════════════════════════╝
 *
 * ENVIRONMENT VARIABLES (set in Railway):
 *   DISCORD_TOKEN         – Bot token from Discord Developer Portal
 *   CLIENT_ID             – Application ID from Discord Developer Portal
 *   CLIENT_SECRET         – Client Secret (for OAuth2 / Dashboard login)
 *   DATABASE_URL          – PostgreSQL connection string (Railway provides this)
 *   SESSION_SECRET        – Random secret for session signing (generate with: openssl rand -hex 32)
 *   DASHBOARD_URL         – Public URL of your dashboard (e.g. https://modforge.up.railway.app)
 *   BOT_OWNER_ID          – Your personal Discord user ID (for owner-only commands)
 *   PORT                  – HTTP port for dashboard API (Railway sets this automatically)
 */

"use strict";

// ─────────────────────────────────────────────────────────────
// IMPORTS
// ─────────────────────────────────────────────────────────────
const {
  Client, GatewayIntentBits, Partials, REST, Routes,
  SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits,
  ActionRowBuilder, ButtonBuilder, ButtonStyle,
  StringSelectMenuBuilder, ModalBuilder, TextInputBuilder,
  TextInputStyle, ChannelType, AuditLogEvent, Collection,
  Events, ActivityType, InteractionType
} = require("discord.js");
const { Pool } = require("pg");
const express = require("express");
const cors = require("cors");
const crypto = require("crypto");
const https = require("https");
const http = require("http");

// ─────────────────────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────────────────────
const CONFIG = {
  token:         process.env.DISCORD_TOKEN,
  clientId:      process.env.CLIENT_ID,
  clientSecret:  process.env.CLIENT_SECRET,
  dbUrl:         process.env.DATABASE_URL,
  sessionSecret: process.env.SESSION_SECRET || crypto.randomBytes(32).toString("hex"),
  dashboardUrl:  process.env.DASHBOARD_URL || "http://localhost:3000",
  port:          parseInt(process.env.PORT) || 3001,
  ownerId:       process.env.BOT_OWNER_ID || "",
  prefix:        "!",
};

if (!CONFIG.token)    { console.error("❌ DISCORD_TOKEN fehlt!"); process.exit(1); }
if (!CONFIG.clientId) { console.error("❌ CLIENT_ID fehlt!"); process.exit(1); }
if (!CONFIG.dbUrl)    { console.error("❌ DATABASE_URL fehlt!"); process.exit(1); }

// ─────────────────────────────────────────────────────────────
// DATABASE
// ─────────────────────────────────────────────────────────────
const db = new Pool({ connectionString: CONFIG.dbUrl, ssl: { rejectUnauthorized: false } });

async function initDatabase() {
  await db.query(`
    CREATE TABLE IF NOT EXISTS guild_config (
      guild_id TEXT NOT NULL,
      key      TEXT NOT NULL,
      value    TEXT,
      PRIMARY KEY (guild_id, key)
    );

    CREATE TABLE IF NOT EXISTS cases (
      id         SERIAL PRIMARY KEY,
      guild_id   TEXT NOT NULL,
      type       TEXT NOT NULL,
      user_id    TEXT NOT NULL,
      user_tag   TEXT NOT NULL,
      mod_id     TEXT NOT NULL,
      mod_tag    TEXT NOT NULL,
      reason     TEXT DEFAULT 'Kein Grund angegeben',
      duration   TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS warns (
      id         SERIAL PRIMARY KEY,
      guild_id   TEXT NOT NULL,
      user_id    TEXT NOT NULL,
      mod_id     TEXT NOT NULL,
      reason     TEXT DEFAULT 'Kein Grund angegeben',
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS invites (
      guild_id   TEXT NOT NULL,
      code       TEXT NOT NULL,
      inviter_id TEXT NOT NULL,
      uses       INT  DEFAULT 0,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY (guild_id, code)
    );

    CREATE TABLE IF NOT EXISTS tickets (
      id         SERIAL PRIMARY KEY,
      guild_id   TEXT NOT NULL,
      user_id    TEXT NOT NULL,
      channel_id TEXT NOT NULL,
      status     TEXT DEFAULT 'open',
      topic      TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      closed_at  TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS audit_log (
      id         SERIAL PRIMARY KEY,
      guild_id   TEXT NOT NULL,
      admin_id   TEXT NOT NULL,
      admin_tag  TEXT NOT NULL,
      action     TEXT NOT NULL,
      detail     TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS join_tracker (
      guild_id   TEXT NOT NULL,
      user_id    TEXT NOT NULL,
      joined_at  TIMESTAMPTZ DEFAULT NOW(),
      invite_code TEXT,
      PRIMARY KEY (guild_id, user_id)
    );

    CREATE INDEX IF NOT EXISTS idx_cases_guild    ON cases(guild_id);
    CREATE INDEX IF NOT EXISTS idx_warns_guild    ON warns(guild_id);
    CREATE INDEX IF NOT EXISTS idx_warns_user     ON warns(guild_id, user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_guild    ON audit_log(guild_id);
    CREATE INDEX IF NOT EXISTS idx_tickets_guild  ON tickets(guild_id, status);
  `);
  console.log("✅ Datenbank initialisiert");
}

// ─────────────────────────────────────────────────────────────
// DB HELPERS
// ─────────────────────────────────────────────────────────────
async function getConfig(guildId, key, defaultValue = null) {
  const r = await db.query("SELECT value FROM guild_config WHERE guild_id=$1 AND key=$2", [guildId, key]);
  if (r.rows.length === 0) return defaultValue;
  try { return JSON.parse(r.rows[0].value); } catch { return r.rows[0].value; }
}

async function setConfig(guildId, key, value) {
  const v = typeof value === "object" ? JSON.stringify(value) : String(value);
  await db.query(
    "INSERT INTO guild_config(guild_id,key,value) VALUES($1,$2,$3) ON CONFLICT(guild_id,key) DO UPDATE SET value=$3",
    [guildId, key, v]
  );
}

async function addCase(guildId, type, userId, userTag, modId, modTag, reason, duration = null) {
  const r = await db.query(
    "INSERT INTO cases(guild_id,type,user_id,user_tag,mod_id,mod_tag,reason,duration) VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id",
    [guildId, type, userId, userTag, modId, modTag, reason, duration]
  );
  return r.rows[0].id;
}

async function addWarn(guildId, userId, modId, reason) {
  const r = await db.query(
    "INSERT INTO warns(guild_id,user_id,mod_id,reason) VALUES($1,$2,$3,$4) RETURNING id",
    [guildId, userId, modId, reason]
  );
  return r.rows[0].id;
}

async function addAudit(guildId, adminId, adminTag, action, detail) {
  await db.query(
    "INSERT INTO audit_log(guild_id,admin_id,admin_tag,action,detail) VALUES($1,$2,$3,$4,$5)",
    [guildId, adminId, adminTag, action, detail]
  );
}

// ─────────────────────────────────────────────────────────────
// COLORS & HELPERS
// ─────────────────────────────────────────────────────────────
const COLORS = {
  primary:  0x4169E1,
  success:  0x3CB371,
  warning:  0xFEE75C,
  danger:   0xED4245,
  info:     0x00B0F4,
  purple:   0x9B59B6,
};

function embed(color, title, desc) {
  const e = new EmbedBuilder().setColor(color).setTimestamp();
  if (title) e.setTitle(title);
  if (desc)  e.setDescription(desc);
  return e;
}

function errorEmbed(msg)   { return embed(COLORS.danger,  "❌ Fehler",   msg); }
function successEmbed(msg) { return embed(COLORS.success, "✅ Erfolg",   msg); }
function infoEmbed(title, desc) { return embed(COLORS.info, title, desc); }

async function sendLog(guild, module, embedData) {
  try {
    const channelId = await getConfig(guild.id, `log_${module}`) ||
                      await getConfig(guild.id, "log_default");
    if (!channelId) return;
    const ch = guild.channels.cache.get(channelId);
    if (ch) await ch.send({ embeds: [embedData] });
  } catch {}
}

function formatDuration(ms) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s/60)}m`;
  if (s < 86400) return `${Math.floor(s/3600)}h`;
  return `${Math.floor(s/86400)}d`;
}

function parseDuration(str) {
  const match = str.match(/^(\d+)(s|m|h|d)$/i);
  if (!match) return null;
  const [, n, unit] = match;
  const multipliers = { s: 1000, m: 60000, h: 3600000, d: 86400000 };
  return parseInt(n) * multipliers[unit.toLowerCase()];
}

// ─────────────────────────────────────────────────────────────
// IN-MEMORY STATE (per guild, resets on restart — ephemeral data)
// ─────────────────────────────────────────────────────────────
const spamTracker   = new Map(); // guildId → Map(userId → { count, firstMsg, timestamps })
const nukeTracker   = new Map(); // guildId → Map(userId → { channelDels, roleDels, bans, kicksTs })
const raidTracker   = new Map(); // guildId → { joins: [], triggered: bool }
const inviteCache   = new Map(); // guildId → Map(code → Invite)

// ─────────────────────────────────────────────────────────────
// SLASH COMMANDS DEFINITION
// ─────────────────────────────────────────────────────────────
const COMMANDS = [
  // MODERATION
  new SlashCommandBuilder()
    .setName("ban").setDescription("🔨 Bannt einen Nutzer vom Server")
    .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Zu bannender Nutzer").setRequired(true))
    .addStringOption(o => o.setName("grund").setDescription("Grund für den Ban"))
    .addIntegerOption(o => o.setName("loeschen").setDescription("Nachrichten der letzten X Tage löschen (0-7)").setMinValue(0).setMaxValue(7)),

  new SlashCommandBuilder()
    .setName("unban").setDescription("🔓 Entbannt einen Nutzer")
    .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
    .addStringOption(o => o.setName("userid").setDescription("Discord User-ID").setRequired(true))
    .addStringOption(o => o.setName("grund").setDescription("Grund")),

  new SlashCommandBuilder()
    .setName("kick").setDescription("👢 Kickt einen Nutzer")
    .setDefaultMemberPermissions(PermissionFlagsBits.KickMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Zu kickender Nutzer").setRequired(true))
    .addStringOption(o => o.setName("grund").setDescription("Grund")),

  new SlashCommandBuilder()
    .setName("mute").setDescription("🔇 Mutet einen Nutzer per Timeout")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true))
    .addStringOption(o => o.setName("dauer").setDescription("Dauer z.B. 10m, 1h, 7d").setRequired(true))
    .addStringOption(o => o.setName("grund").setDescription("Grund")),

  new SlashCommandBuilder()
    .setName("unmute").setDescription("🔊 Hebt den Timeout auf")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true))
    .addStringOption(o => o.setName("grund").setDescription("Grund")),

  new SlashCommandBuilder()
    .setName("warn").setDescription("⚠️ Verwarnt einen Nutzer")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true))
    .addStringOption(o => o.setName("grund").setDescription("Grund").setRequired(true)),

  new SlashCommandBuilder()
    .setName("warns").setDescription("📋 Zeigt die Verwarnungen eines Nutzers")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true)),

  new SlashCommandBuilder()
    .setName("delwarn").setDescription("🗑️ Löscht eine Verwarnung")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addIntegerOption(o => o.setName("id").setDescription("Warn-ID").setRequired(true)),

  new SlashCommandBuilder()
    .setName("clear").setDescription("🧹 Löscht Nachrichten im Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
    .addIntegerOption(o => o.setName("anzahl").setDescription("Anzahl (1-100)").setRequired(true).setMinValue(1).setMaxValue(100))
    .addUserOption(o => o.setName("nutzer").setDescription("Nur von diesem Nutzer")),

  new SlashCommandBuilder()
    .setName("slowmode").setDescription("🐌 Setzt den Slowmode")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels)
    .addIntegerOption(o => o.setName("sekunden").setDescription("0 = deaktiviert, max 21600").setRequired(true).setMinValue(0).setMaxValue(21600)),

  new SlashCommandBuilder()
    .setName("lock").setDescription("🔒 Sperrt den Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels)
    .addStringOption(o => o.setName("grund").setDescription("Grund")),

  new SlashCommandBuilder()
    .setName("unlock").setDescription("🔓 Entsperrt den Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels),

  new SlashCommandBuilder()
    .setName("nick").setDescription("✏️ Ändert den Nickname eines Nutzers")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageNicknames)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true))
    .addStringOption(o => o.setName("name").setDescription("Neuer Nickname (leer lassen zum Zurücksetzen)")),

  // CASES
  new SlashCommandBuilder()
    .setName("case").setDescription("📁 Zeigt Details zu einem Case")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addIntegerOption(o => o.setName("id").setDescription("Case-ID").setRequired(true)),

  new SlashCommandBuilder()
    .setName("cases").setDescription("📁 Zeigt alle Cases eines Nutzers")
    .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true)),

  // UTILITY
  new SlashCommandBuilder()
    .setName("userinfo").setDescription("👤 Zeigt Infos zu einem Nutzer")
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer (leer = du selbst)")),

  new SlashCommandBuilder()
    .setName("serverinfo").setDescription("🏠 Zeigt Server-Informationen"),

  new SlashCommandBuilder()
    .setName("avatar").setDescription("🖼️ Zeigt den Avatar eines Nutzers")
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer")),

  new SlashCommandBuilder()
    .setName("ping").setDescription("🏓 Zeigt die Bot-Latenz"),

  new SlashCommandBuilder()
    .setName("botinfo").setDescription("ℹ️ Informationen über den Bot"),

  new SlashCommandBuilder()
    .setName("rolleninfo").setDescription("🏷️ Informationen zu einer Rolle")
    .addRoleOption(o => o.setName("rolle").setDescription("Rolle").setRequired(true)),

  // INVITES
  new SlashCommandBuilder()
    .setName("invites").setDescription("📨 Zeigt deine oder die Einladungen eines Nutzers")
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer")),

  new SlashCommandBuilder()
    .setName("inviteinfo").setDescription("📨 Infos zu einem Einladungs-Code")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption(o => o.setName("code").setDescription("Invite Code").setRequired(true)),

  // VOICE
  new SlashCommandBuilder()
    .setName("vcmute").setDescription("🎙️ Mutet einen Nutzer im Voice-Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.MuteMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true)),

  new SlashCommandBuilder()
    .setName("vcunmute").setDescription("🎙️ Entmutet einen Nutzer im Voice-Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.MuteMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true)),

  new SlashCommandBuilder()
    .setName("vcdeafen").setDescription("🔇 Deafened einen Nutzer im Voice-Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.DeafenMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true)),

  new SlashCommandBuilder()
    .setName("vcmove").setDescription("➡️ Verschiebt einen Nutzer in einen Voice-Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.MoveMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true))
    .addChannelOption(o => o.setName("channel").setDescription("Ziel-Channel").setRequired(true).addChannelTypes(ChannelType.GuildVoice)),

  new SlashCommandBuilder()
    .setName("vckick").setDescription("🚪 Kickt einen Nutzer aus dem Voice-Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.MoveMembers)
    .addUserOption(o => o.setName("nutzer").setDescription("Nutzer").setRequired(true)),

  // TICKETS
  new SlashCommandBuilder()
    .setName("ticket").setDescription("🎟️ Erstellt ein neues Support-Ticket")
    .addStringOption(o => o.setName("thema").setDescription("Thema des Tickets")),

  new SlashCommandBuilder()
    .setName("closeticket").setDescription("🔒 Schließt das aktuelle Ticket")
    .addStringOption(o => o.setName("grund").setDescription("Grund")),

  // CONFIG
  new SlashCommandBuilder()
    .setName("setup").setDescription("⚙️ Richtet den Bot auf diesem Server ein")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),

  new SlashCommandBuilder()
    .setName("setlogchannel").setDescription("📋 Setzt den Log-Kanal für ein Modul")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption(o => o.setName("modul").setDescription("Log-Modul (z.B. moderation, spam)").setRequired(true))
    .addChannelOption(o => o.setName("channel").setDescription("Log-Channel").setRequired(true).addChannelTypes(ChannelType.GuildText)),

  new SlashCommandBuilder()
    .setName("setwelcome").setDescription("👋 Setzt den Willkommens-Channel")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addChannelOption(o => o.setName("channel").setDescription("Channel").setRequired(true).addChannelTypes(ChannelType.GuildText))
    .addStringOption(o => o.setName("nachricht").setDescription("Willkommensnachricht ({user}, {server}, {count} verfügbar)")),

  new SlashCommandBuilder()
    .setName("setmutedrolle").setDescription("🔇 Setzt die Muted-Rolle")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addRoleOption(o => o.setName("rolle").setDescription("Rolle").setRequired(true)),

  new SlashCommandBuilder()
    .setName("setverify").setDescription("✅ Konfiguriert das Verifizierungssystem")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addChannelOption(o => o.setName("channel").setDescription("Verify-Channel").setRequired(true).addChannelTypes(ChannelType.GuildText))
    .addRoleOption(o => o.setName("rolle").setDescription("Rolle nach Verifizierung").setRequired(true)),

  new SlashCommandBuilder()
    .setName("setautorole").setDescription("🎭 Setzt die Auto-Rolle für neue Mitglieder")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addRoleOption(o => o.setName("rolle").setDescription("Rolle").setRequired(true)),

  new SlashCommandBuilder()
    .setName("antispam").setDescription("⚡ Konfiguriert Anti-Spam")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addBooleanOption(o => o.setName("aktiv").setDescription("An/Aus").setRequired(true))
    .addIntegerOption(o => o.setName("limit").setDescription("Max. Nachrichten in 5 Sekunden (Standard: 5)").setMinValue(2).setMaxValue(20)),

  new SlashCommandBuilder()
    .setName("antinuke").setDescription("🛡️ Konfiguriert Anti-Nuke")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addBooleanOption(o => o.setName("aktiv").setDescription("An/Aus").setRequired(true)),

  new SlashCommandBuilder()
    .setName("antiraid").setDescription("🛡️ Konfiguriert Anti-Raid")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addBooleanOption(o => o.setName("aktiv").setDescription("An/Aus").setRequired(true))
    .addIntegerOption(o => o.setName("joins").setDescription("Max. Joins in 10 Sek.").setMinValue(3).setMaxValue(30)),

  new SlashCommandBuilder()
    .setName("dashboard").setDescription("🖥️ Link zum Web-Dashboard"),

  new SlashCommandBuilder()
    .setName("help").setDescription("❓ Hilfe und alle Commands"),

  new SlashCommandBuilder()
    .setName("backup").setDescription("💾 Erstellt/stellt Backup wieder her")
    .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addStringOption(o => o.setName("aktion").setDescription("create oder restore").setRequired(true).addChoices(
      { name: "Erstellen", value: "create" },
      { name: "Liste", value: "list" },
    )),
].map(c => c.toJSON());

// ─────────────────────────────────────────────────────────────
// REGISTER SLASH COMMANDS
// ─────────────────────────────────────────────────────────────
async function registerCommands() {
  const rest = new REST({ version: "10" }).setToken(CONFIG.token);
  try {
    console.log("⚙️  Registriere Slash Commands...");
    await rest.put(Routes.applicationCommands(CONFIG.clientId), { body: COMMANDS });
    console.log(`✅ ${COMMANDS.length} Slash Commands registriert`);
  } catch (err) {
    console.error("❌ Slash Commands Fehler:", err);
  }
}

// ─────────────────────────────────────────────────────────────
// DISCORD CLIENT
// ─────────────────────────────────────────────────────────────
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildMessageReactions,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildModeration,
    GatewayIntentBits.GuildInvites,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.DirectMessages,
  ],
  partials: [Partials.Channel, Partials.Message, Partials.GuildMember],
});

// ─────────────────────────────────────────────────────────────
// SCAM / SHORTENER DOMAIN LISTS
// ─────────────────────────────────────────────────────────────
const SCAM_DOMAINS = new Set([
  "discordnitro.gift", "discord-nitro.gift", "discord-airdrop.com",
  "discordapp.gift", "steamcommunity.ru", "steamcommunity.com.ru",
  "store.steampowered.com.ru", "csgotrade.ru", "free-nitro.ru",
  "discordnltro.com", "discord-gift.xyz", "nitro.discord.gift",
  "discordsafety.xyz", "dlscord.com", "discord.com-gift.ru",
]);

const SHORTENER_DOMAINS = new Set([
  "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
  "buff.ly", "short.link", "cutt.ly", "rb.gy", "shorturl.at", "tiny.cc",
  "rebrand.ly", "bl.ink", "snip.ly", "bc.vc", "adf.ly",
]);

function extractDomains(text) {
  const domains = [];
  const urlRegex = /https?:\/\/([^\/\s]+)/gi;
  let match;
  while ((match = urlRegex.exec(text)) !== null) {
    domains.push(match[1].toLowerCase().replace(/^www\./, ""));
  }
  return domains;
}

// ─────────────────────────────────────────────────────────────
// ANTI-SPAM
// ─────────────────────────────────────────────────────────────
async function checkSpam(message) {
  if (message.author.bot) return false;
  const guildId = message.guild.id;
  const userId  = message.author.id;

  const enabled = await getConfig(guildId, "antispam_enabled", false);
  if (!enabled) return false;

  const limit = await getConfig(guildId, "antispam_limit", 5);
  const window = 5000; // 5 seconds

  if (!spamTracker.has(guildId)) spamTracker.set(guildId, new Map());
  const guild = spamTracker.get(guildId);

  const now = Date.now();
  const entry = guild.get(userId) || { timestamps: [] };
  entry.timestamps = entry.timestamps.filter(t => now - t < window);
  entry.timestamps.push(now);
  guild.set(userId, entry);

  if (entry.timestamps.length >= limit) {
    guild.set(userId, { timestamps: [] }); // reset
    return true;
  }
  return false;
}

// ─────────────────────────────────────────────────────────────
// ANTI-NUKE CHECK (on audit log events)
// ─────────────────────────────────────────────────────────────
async function checkNuke(guild, userId, action) {
  const enabled = await getConfig(guild.id, "antinuke_enabled", false);
  if (!enabled) return;

  const limit = 5;
  const window = 10000;
  const now = Date.now();

  if (!nukeTracker.has(guild.id)) nukeTracker.set(guild.id, new Map());
  const guildTrack = nukeTracker.get(guild.id);

  const entry = guildTrack.get(userId) || { actions: [] };
  entry.actions = entry.actions.filter(a => now - a.ts < window);
  entry.actions.push({ ts: now, action });
  guildTrack.set(userId, entry);

  if (entry.actions.length >= limit) {
    guildTrack.set(userId, { actions: [] });
    try {
      const member = await guild.members.fetch(userId);
      if (member && !member.permissions.has(PermissionFlagsBits.Administrator)) {
        await member.ban({ reason: "🛡️ Anti-Nuke: Zu viele destruktive Aktionen" });
        await sendLog(guild, "antinuke", embed(COLORS.danger, "🛡️ Anti-Nuke ausgelöst",
          `**Nutzer:** <@${userId}>\n**Aktion:** ${action} (${entry.actions.length}x in 10s)\n**Maßnahme:** Ban`
        ));
      }
    } catch {}
  }
}

// ─────────────────────────────────────────────────────────────
// ANTI-RAID CHECK
// ─────────────────────────────────────────────────────────────
async function checkRaid(guild, member) {
  const enabled = await getConfig(guild.id, "antiraid_enabled", false);
  if (!enabled) return;

  const limit = await getConfig(guild.id, "antiraid_limit", 10);
  const window = 10000;
  const now = Date.now();

  if (!raidTracker.has(guild.id)) raidTracker.set(guild.id, { joins: [], triggered: false });
  const tracker = raidTracker.get(guild.id);
  tracker.joins = tracker.joins.filter(t => now - t < window);
  tracker.joins.push(now);

  if (tracker.joins.length >= limit && !tracker.triggered) {
    tracker.triggered = true;
    setTimeout(() => { tracker.triggered = false; }, 30000);

    await sendLog(guild, "antiraid", embed(COLORS.danger, "🛡️ Raid erkannt!",
      `**${tracker.joins.length} Joins** in 10 Sekunden!\nNeue Konten werden gekickt.`
    ));

    // kick members with accounts younger than 7 days
    const minAge = 7 * 24 * 3600 * 1000;
    guild.members.cache.forEach(async m => {
      if (m.user.bot) return;
      if (Date.now() - m.user.createdTimestamp < minAge) {
        try { await m.kick("🛡️ Anti-Raid: Neues Konto während Raid"); } catch {}
      }
    });
  }
}

// ─────────────────────────────────────────────────────────────
// TICKET HELPERS
// ─────────────────────────────────────────────────────────────
async function createTicket(guild, user, topic = null) {
  const categoryId   = await getConfig(guild.id, "ticket_category");
  const supportRoleId = await getConfig(guild.id, "ticket_support_role");

  const overwrites = [
    { id: guild.id, deny: [PermissionFlagsBits.ViewChannel] },
    { id: user.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages] },
  ];
  if (supportRoleId) {
    overwrites.push({ id: supportRoleId, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages] });
  }

  const channelName = `ticket-${user.username.toLowerCase().replace(/[^a-z0-9]/g, "")}-${Date.now().toString(36)}`;
  const channel = await guild.channels.create({
    name: channelName,
    type: ChannelType.GuildText,
    parent: categoryId || undefined,
    permissionOverwrites: overwrites,
  });

  await db.query(
    "INSERT INTO tickets(guild_id,user_id,channel_id,topic) VALUES($1,$2,$3,$4)",
    [guild.id, user.id, channel.id, topic]
  );

  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("close_ticket").setLabel("🔒 Schließen").setStyle(ButtonStyle.Danger),
    new ButtonBuilder().setCustomId("claim_ticket").setLabel("📌 Claimen").setStyle(ButtonStyle.Secondary),
  );

  await channel.send({
    content: `<@${user.id}>${supportRoleId ? ` | <@&${supportRoleId}>` : ""}`,
    embeds: [embed(COLORS.primary, "🎟️ Support Ticket",
      `Hallo <@${user.id}>! 👋\n\nDein Ticket wurde erstellt${topic ? `:\n**Thema:** ${topic}` : ""}.\n\nEin Teammitglied wird sich bald um dich kümmern.\nSchreibe einfach dein Problem in diesen Channel.`
    )],
    components: [row],
  });

  return channel;
}

// ─────────────────────────────────────────────────────────────
// VERIFY SYSTEM
// ─────────────────────────────────────────────────────────────
const pendingVerifications = new Map(); // userId → code

// ─────────────────────────────────────────────────────────────
// EVENT: READY
// ─────────────────────────────────────────────────────────────
client.once(Events.ClientReady, async () => {
  console.log(`✅ Eingeloggt als ${client.user.tag}`);
  console.log(`📊 Aktiv auf ${client.guilds.cache.size} Server(n)`);

  client.user.setPresence({
    activities: [{ name: "🛡️ /help | modforge.bot", type: ActivityType.Watching }],
    status: "online",
  });

  // Cache invites
  for (const [, guild] of client.guilds.cache) {
    try {
      const invs = await guild.invites.fetch();
      inviteCache.set(guild.id, new Map(invs.map(i => [i.code, i])));
    } catch {}
  }
});

// ─────────────────────────────────────────────────────────────
// EVENT: GUILD JOIN
// ─────────────────────────────────────────────────────────────
client.on(Events.GuildCreate, async guild => {
  try {
    const invs = await guild.invites.fetch();
    inviteCache.set(guild.id, new Map(invs.map(i => [i.code, i])));
  } catch {}
  console.log(`➕ Server beigetreten: ${guild.name} (${guild.id}) · ${guild.memberCount} Mitglieder`);
});

// ─────────────────────────────────────────────────────────────
// EVENT: MEMBER JOIN
// ─────────────────────────────────────────────────────────────
client.on(Events.GuildMemberAdd, async member => {
  const { guild } = member;

  // Anti-Raid
  await checkRaid(guild, member);

  // Auto-Role
  try {
    const autoRoleId = await getConfig(guild.id, "autorole");
    if (autoRoleId) {
      const role = guild.roles.cache.get(autoRoleId);
      if (role) await member.roles.add(role);
    }
  } catch {}

  // Invite tracking
  try {
    const newInvites = await guild.invites.fetch();
    const oldInvites = inviteCache.get(guild.id) || new Map();
    let usedCode = null;
    let inviterId = null;

    newInvites.forEach(inv => {
      const old = oldInvites.get(inv.code);
      if (old && inv.uses > old.uses) {
        usedCode  = inv.code;
        inviterId = inv.inviter?.id;
      }
    });

    inviteCache.set(guild.id, new Map(newInvites.map(i => [i.code, i])));
    if (usedCode) {
      await db.query(
        "INSERT INTO join_tracker(guild_id,user_id,invite_code) VALUES($1,$2,$3) ON CONFLICT(guild_id,user_id) DO UPDATE SET invite_code=$3, joined_at=NOW()",
        [guild.id, member.id, usedCode]
      ).catch(() => {});
      if (inviterId) {
        await db.query(
          "INSERT INTO invites(guild_id,code,inviter_id,uses) VALUES($1,$2,$3,1) ON CONFLICT(guild_id,code) DO UPDATE SET uses=invites.uses+1",
          [guild.id, usedCode, inviterId]
        ).catch(() => {});
      }
    }
  } catch {}

  // Welcome message
  try {
    const welcomeChannelId = await getConfig(guild.id, "welcome_channel");
    if (welcomeChannelId) {
      const ch = guild.channels.cache.get(welcomeChannelId);
      if (ch) {
        let msg = await getConfig(guild.id, "welcome_message",
          "Willkommen auf **{server}**, {user}! 🎉 Du bist Mitglied **#{count}**.");
        msg = msg
          .replace("{user}", `<@${member.id}>`)
          .replace("{server}", guild.name)
          .replace("{count}", guild.memberCount);

        const title = await getConfig(guild.id, "welcome_embed_title", "Willkommen!");
        const color = await getConfig(guild.id, "welcome_embed_color", COLORS.success);

        await ch.send({
          embeds: [embed(parseInt(color) || COLORS.success, title, msg)
            .setThumbnail(member.user.displayAvatarURL({ size: 128 }))
          ]
        });
      }
    }
  } catch {}

  // DM Welcome
  try {
    const dmEnabled = await getConfig(guild.id, "welcome_dm_enabled", false);
    if (dmEnabled) {
      let dmMsg = await getConfig(guild.id, "welcome_dm_message",
        `Hey {user}! Willkommen auf **{server}**! 🎉\n\nBitte lies dir unsere Regeln durch und verhalte dich respektvoll.\nWir freuen uns auf dich!`);
      dmMsg = dmMsg.replace("{user}", member.user.username).replace("{server}", guild.name);
      await member.user.send({ content: dmMsg }).catch(() => {});
    }
  } catch {}

  // Log
  await sendLog(guild, "join", embed(COLORS.success, "👋 Mitglied beigetreten",
    `**Nutzer:** ${member.user.tag} (${member.id})\n**Konto erstellt:** <t:${Math.floor(member.user.createdTimestamp/1000)}:R>`
  ).setThumbnail(member.user.displayAvatarURL()));
});

// ─────────────────────────────────────────────────────────────
// EVENT: MEMBER LEAVE
// ─────────────────────────────────────────────────────────────
client.on(Events.GuildMemberRemove, async member => {
  await sendLog(member.guild, "leave", embed(COLORS.warning, "🚪 Mitglied verlassen",
    `**Nutzer:** ${member.user.tag} (${member.id})\n**Rollen:** ${member.roles.cache.filter(r => r.id !== member.guild.id).map(r => r.name).join(", ") || "Keine"}`
  ).setThumbnail(member.user.displayAvatarURL()));
});

// ─────────────────────────────────────────────────────────────
// EVENT: MESSAGE CREATE (Anti-Spam, Anti-Scam, Anti-Shortener, AutoMod, Prefix)
// ─────────────────────────────────────────────────────────────
client.on(Events.MessageCreate, async message => {
  if (message.author.bot || !message.guild) return;

  const member = message.member;

  // Skip mods
  const isMod = member?.permissions.has(PermissionFlagsBits.ManageMessages);

  if (!isMod) {
    // ── Anti-Scam ──
    const scamEnabled = await getConfig(message.guild.id, "antiscam_enabled", false);
    if (scamEnabled) {
      const domains = extractDomains(message.content);
      const isScam = domains.some(d => SCAM_DOMAINS.has(d) || [...SCAM_DOMAINS].some(sd => d.includes(sd)));
      if (isScam) {
        await message.delete().catch(() => {});
        const warnId = await addWarn(message.guild.id, message.author.id, client.user.id, "Anti-Scam: Scam-Link gesendet");
        await message.channel.send({
          content: `<@${message.author.id}>`,
          embeds: [errorEmbed(`⚠️ Scam-Link erkannt und gelöscht! (Warn #${warnId})`)]
        }).then(m => setTimeout(() => m.delete().catch(() => {}), 8000));
        await sendLog(message.guild, "antiscam", embed(COLORS.danger, "🔗 Scam-Link erkannt",
          `**Nutzer:** ${message.author.tag}\n**Channel:** ${message.channel}\n**Nachricht:** ${message.content.slice(0, 500)}`
        ));
        return;
      }
    }

    // ── Anti-Shortener ──
    const shortEnabled = await getConfig(message.guild.id, "antishortener_enabled", false);
    if (shortEnabled) {
      const domains = extractDomains(message.content);
      const isShort = domains.some(d => SHORTENER_DOMAINS.has(d));
      if (isShort) {
        await message.delete().catch(() => {});
        await message.channel.send({
          content: `<@${message.author.id}>`,
          embeds: [errorEmbed("URL-Kürzer sind auf diesem Server nicht erlaubt!")]
        }).then(m => setTimeout(() => m.delete().catch(() => {}), 6000));
        return;
      }
    }

    // ── Anti-Mention ──
    const mentionEnabled = await getConfig(message.guild.id, "antimention_enabled", false);
    if (mentionEnabled) {
      const mentionLimit = await getConfig(message.guild.id, "antimention_limit", 5);
      const totalMentions = message.mentions.users.size + message.mentions.roles.size;
      if (totalMentions >= mentionLimit) {
        await message.delete().catch(() => {});
        try {
          await member.timeout(5 * 60 * 1000, "Anti-Mention: Zu viele Mentions");
        } catch {}
        await message.channel.send({
          content: `<@${message.author.id}>`,
          embeds: [errorEmbed(`Zu viele Mentions (${totalMentions}/${mentionLimit})! Du wurdest gemuted.`)]
        }).then(m => setTimeout(() => m.delete().catch(() => {}), 8000));
        return;
      }
    }

    // ── AutoMod (custom word filter) ──
    const automodEnabled = await getConfig(message.guild.id, "automod_enabled", false);
    if (automodEnabled) {
      const blocklist = await getConfig(message.guild.id, "automod_words", []);
      const content = message.content.toLowerCase();
      if (blocklist.some(w => content.includes(w.toLowerCase()))) {
        await message.delete().catch(() => {});
        await message.channel.send({
          content: `<@${message.author.id}>`,
          embeds: [errorEmbed("Diese Nachricht enthält verbotene Wörter!")]
        }).then(m => setTimeout(() => m.delete().catch(() => {}), 5000));
        await sendLog(message.guild, "automod", embed(COLORS.warning, "🤖 AutoMod ausgelöst",
          `**Nutzer:** ${message.author.tag}\n**Channel:** ${message.channel}`
        ));
        return;
      }
    }

    // ── Anti-Spam ──
    const isSpam = await checkSpam(message);
    if (isSpam) {
      await message.channel.bulkDelete(
        message.channel.messages.cache.filter(m => m.author.id === message.author.id).first(5)
      ).catch(() => {});
      try {
        await member.timeout(60 * 1000, "Anti-Spam: Zu viele Nachrichten");
      } catch {}
      await message.channel.send({
        content: `<@${message.author.id}>`,
        embeds: [errorEmbed("Bitte nicht spammen! Du wurdest für 1 Minute gemuted.")]
      }).then(m => setTimeout(() => m.delete().catch(() => {}), 8000));
      await sendLog(message.guild, "spam", embed(COLORS.warning, "⚡ Anti-Spam ausgelöst",
        `**Nutzer:** ${message.author.tag}\n**Channel:** ${message.channel}\n**Maßnahme:** 1 Minute Timeout`
      ));
      return;
    }
  }

  // ── Prefix Commands (!help only for legacy) ──
  if (message.content.startsWith(CONFIG.prefix)) {
    const args = message.content.slice(CONFIG.prefix.length).trim().split(/\s+/);
    const cmd  = args.shift().toLowerCase();
    if (cmd === "help" || cmd === "hilfe") {
      await message.reply({ embeds: [embed(COLORS.primary, "❓ ModForge Hilfe",
        `Benutze `/help` für alle Befehle!\nDashboard: ${CONFIG.dashboardUrl}`
      )] });
    }
  }
});

// ─────────────────────────────────────────────────────────────
// EVENT: MESSAGE UPDATE (edit log)
// ─────────────────────────────────────────────────────────────
client.on(Events.MessageUpdate, async (oldMsg, newMsg) => {
  if (!oldMsg.guild || oldMsg.author?.bot) return;
  if (oldMsg.content === newMsg.content) return;

  await sendLog(oldMsg.guild, "message_edit", embed(COLORS.info, "✏️ Nachricht bearbeitet",
    `**Nutzer:** ${oldMsg.author?.tag}\n**Channel:** ${oldMsg.channel}\n**Vorher:** ${(oldMsg.content || "").slice(0, 400)}\n**Nachher:** ${(newMsg.content || "").slice(0, 400)}`
  ));
});

// ─────────────────────────────────────────────────────────────
// EVENT: MESSAGE DELETE (delete log)
// ─────────────────────────────────────────────────────────────
client.on(Events.MessageDelete, async message => {
  if (!message.guild || message.author?.bot) return;

  await sendLog(message.guild, "message_delete", embed(COLORS.warning, "🗑️ Nachricht gelöscht",
    `**Nutzer:** ${message.author?.tag || "Unbekannt"}\n**Channel:** ${message.channel}\n**Inhalt:** ${(message.content || "(kein Text)").slice(0, 800)}`
  ));
});

// ─────────────────────────────────────────────────────────────
// EVENT: GUILD AUDIT LOG (nuke detection + moderation logging)
// ─────────────────────────────────────────────────────────────
client.on(Events.GuildAuditLogEntryCreate, async (entry, guild) => {
  const { action, executor, target } = entry;
  if (!executor || executor.bot) return;

  const nukeActions = [
    AuditLogEvent.ChannelDelete,
    AuditLogEvent.RoleDelete,
    AuditLogEvent.GuildUpdate,
    AuditLogEvent.MemberBanAdd,
    AuditLogEvent.WebhookCreate,
  ];

  if (nukeActions.includes(action)) {
    await checkNuke(guild, executor.id, AuditLogEvent[action]);
  }

  // Moderation log
  if ([AuditLogEvent.MemberBanAdd, AuditLogEvent.MemberBanRemove, AuditLogEvent.MemberKick].includes(action)) {
    const actionNames = {
      [AuditLogEvent.MemberBanAdd]:    "🔨 Ban",
      [AuditLogEvent.MemberBanRemove]: "🔓 Unban",
      [AuditLogEvent.MemberKick]:      "👢 Kick",
    };
    await sendLog(guild, "moderation", embed(COLORS.danger, actionNames[action],
      `**Moderator:** ${executor.tag}\n**Nutzer:** ${target?.tag || target?.id}\n**Grund:** ${entry.reason || "Kein Grund"}`
    ));
  }
});

// ─────────────────────────────────────────────────────────────
// EVENT: ROLE CREATE / DELETE (log)
// ─────────────────────────────────────────────────────────────
client.on(Events.GuildRoleCreate, async role => {
  await sendLog(role.guild, "role_create", embed(COLORS.success, "🏷️ Rolle erstellt",
    `**Name:** ${role.name}\n**ID:** ${role.id}\n**Farbe:** ${role.hexColor}`
  ));
});

client.on(Events.GuildRoleDelete, async role => {
  await sendLog(role.guild, "role_delete", embed(COLORS.danger, "🗑️ Rolle gelöscht",
    `**Name:** ${role.name}\n**ID:** ${role.id}`
  ));
});

// ─────────────────────────────────────────────────────────────
// EVENT: CHANNEL CREATE / DELETE (log)
// ─────────────────────────────────────────────────────────────
client.on(Events.ChannelCreate, async channel => {
  if (!channel.guild) return;
  await sendLog(channel.guild, "channel_create", embed(COLORS.success, "📁 Channel erstellt",
    `**Name:** ${channel.name}\n**Typ:** ${ChannelType[channel.type]}\n**ID:** ${channel.id}`
  ));
});

client.on(Events.ChannelDelete, async channel => {
  if (!channel.guild) return;
  await sendLog(channel.guild, "channel_delete", embed(COLORS.danger, "🗑️ Channel gelöscht",
    `**Name:** ${channel.name}\n**Typ:** ${ChannelType[channel.type]}\n**ID:** ${channel.id}`
  ));
});

// ─────────────────────────────────────────────────────────────
// EVENT: VOICE STATE (Voice log)
// ─────────────────────────────────────────────────────────────
client.on(Events.VoiceStateUpdate, async (oldState, newState) => {
  const member = newState.member || oldState.member;
  if (!member || member.user.bot) return;
  const guild = newState.guild;

  if (!oldState.channelId && newState.channelId) {
    await sendLog(guild, "voice", embed(COLORS.info, "🎙️ Voice beigetreten",
      `**Nutzer:** ${member.user.tag}\n**Channel:** ${newState.channel?.name}`
    ));
  } else if (oldState.channelId && !newState.channelId) {
    await sendLog(guild, "voice", embed(COLORS.warning, "🎙️ Voice verlassen",
      `**Nutzer:** ${member.user.tag}\n**Channel:** ${oldState.channel?.name}`
    ));
  } else if (oldState.channelId !== newState.channelId) {
    await sendLog(guild, "voice", embed(COLORS.info, "🔀 Voice Channel gewechselt",
      `**Nutzer:** ${member.user.tag}\n**Von:** ${oldState.channel?.name} → **Nach:** ${newState.channel?.name}`
    ));
  }
});

// ─────────────────────────────────────────────────────────────
// EVENT: INVITE CREATE / DELETE (cache update)
// ─────────────────────────────────────────────────────────────
client.on(Events.InviteCreate, async invite => {
  if (!invite.guild) return;
  const cache = inviteCache.get(invite.guild.id) || new Map();
  cache.set(invite.code, invite);
  inviteCache.set(invite.guild.id, cache);
});

client.on(Events.InviteDelete, async invite => {
  if (!invite.guild) return;
  const cache = inviteCache.get(invite.guild.id);
  if (cache) cache.delete(invite.code);
});

// ─────────────────────────────────────────────────────────────
// EVENT: INTERACTION CREATE (Slash Commands + Buttons)
// ─────────────────────────────────────────────────────────────
client.on(Events.InteractionCreate, async interaction => {
  // ── Buttons ──
  if (interaction.isButton()) {
    if (interaction.customId === "close_ticket") {
      await handleCloseTicket(interaction);
    } else if (interaction.customId === "claim_ticket") {
      await handleClaimTicket(interaction);
    } else if (interaction.customId === "verify_button") {
      await handleVerifyButton(interaction);
    }
    return;
  }

  if (!interaction.isChatInputCommand()) return;

  const { commandName, guild, member, user } = interaction;
  if (!guild) return;

  // Helper: defer ephemeral
  const deferE = () => interaction.deferReply({ ephemeral: true });
  const deferP = () => interaction.deferReply();

  try {
    // ──────────────────────────────
    // MODERATION COMMANDS
    // ──────────────────────────────

    if (commandName === "ban") {
      await deferE();
      const target  = interaction.options.getMember("nutzer");
      const reason  = interaction.options.getString("grund") || "Kein Grund angegeben";
      const delDays = interaction.options.getInteger("loeschen") ?? 0;

      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });
      if (!member.permissions.has(PermissionFlagsBits.BanMembers))
        return interaction.editReply({ embeds: [errorEmbed("Keine Berechtigung.")] });
      if (target.id === user.id)
        return interaction.editReply({ embeds: [errorEmbed("Du kannst dich nicht selbst bannen.")] });

      try {
        await target.user.send({ embeds: [embed(COLORS.danger, "🔨 Du wurdest gebannt",
          `**Server:** ${guild.name}\n**Grund:** ${reason}\n**Moderator:** ${user.tag}`
        )] }).catch(() => {});
        await guild.members.ban(target.id, { reason: `${user.tag}: ${reason}`, deleteMessageDays: delDays });
        const caseId = await addCase(guild.id, "Ban", target.id, target.user.tag, user.id, user.tag, reason);
        await addAudit(guild.id, user.id, user.tag, "Ban", `${target.user.tag} — ${reason}`);

        await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** wurde gebannt. (Case #${caseId})`)] });
        await sendLog(guild, "moderation", embed(COLORS.danger, "🔨 Ban",
          `**Nutzer:** ${target.user.tag} (${target.id})\n**Moderator:** ${user.tag}\n**Grund:** ${reason}\n**Case:** #${caseId}`
        ));
      } catch (e) {
        await interaction.editReply({ embeds: [errorEmbed(`Konnte nicht bannen: ${e.message}`)] });
      }
    }

    else if (commandName === "unban") {
      await deferE();
      const userId = interaction.options.getString("userid");
      const reason = interaction.options.getString("grund") || "Kein Grund angegeben";
      try {
        await guild.members.unban(userId, `${user.tag}: ${reason}`);
        const caseId = await addCase(guild.id, "Unban", userId, userId, user.id, user.tag, reason);
        await interaction.editReply({ embeds: [successEmbed(`Nutzer \`${userId}\` entbannt. (Case #${caseId})`)] });
      } catch {
        await interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gebannt oder ID ungültig.")] });
      }
    }

    else if (commandName === "kick") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      const reason = interaction.options.getString("grund") || "Kein Grund angegeben";
      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht auf diesem Server.")] });
      try {
        await target.user.send({ embeds: [embed(COLORS.warning, "👢 Du wurdest gekickt",
          `**Server:** ${guild.name}\n**Grund:** ${reason}`
        )] }).catch(() => {});
        await target.kick(`${user.tag}: ${reason}`);
        const caseId = await addCase(guild.id, "Kick", target.id, target.user.tag, user.id, user.tag, reason);
        await addAudit(guild.id, user.id, user.tag, "Kick", `${target.user.tag} — ${reason}`);
        await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** wurde gekickt. (Case #${caseId})`)] });
        await sendLog(guild, "moderation", embed(COLORS.warning, "👢 Kick",
          `**Nutzer:** ${target.user.tag}\n**Moderator:** ${user.tag}\n**Grund:** ${reason}`
        ));
      } catch (e) {
        await interaction.editReply({ embeds: [errorEmbed(`Fehler: ${e.message}`)] });
      }
    }

    else if (commandName === "mute") {
      await deferE();
      const target   = interaction.options.getMember("nutzer");
      const durStr   = interaction.options.getString("dauer");
      const reason   = interaction.options.getString("grund") || "Kein Grund angegeben";
      const duration = parseDuration(durStr);
      if (!duration) return interaction.editReply({ embeds: [errorEmbed("Ungültige Dauer. Beispiele: 10m, 1h, 7d")] });
      if (!target)   return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });
      if (duration > 28 * 24 * 3600 * 1000) return interaction.editReply({ embeds: [errorEmbed("Max. 28 Tage.")] });
      try {
        await target.timeout(duration, `${user.tag}: ${reason}`);
        const caseId = await addCase(guild.id, "Mute", target.id, target.user.tag, user.id, user.tag, reason, durStr);
        await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** für **${durStr}** gemuted. (Case #${caseId})`)] });
        await sendLog(guild, "moderation", embed(COLORS.warning, "🔇 Mute",
          `**Nutzer:** ${target.user.tag}\n**Dauer:** ${durStr}\n**Grund:** ${reason}`
        ));
      } catch (e) {
        await interaction.editReply({ embeds: [errorEmbed(`Fehler: ${e.message}`)] });
      }
    }

    else if (commandName === "unmute") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      const reason = interaction.options.getString("grund") || "Kein Grund angegeben";
      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });
      try {
        await target.timeout(null, `${user.tag}: ${reason}`);
        await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** entmuted.`)] });
      } catch (e) {
        await interaction.editReply({ embeds: [errorEmbed(`Fehler: ${e.message}`)] });
      }
    }

    else if (commandName === "warn") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      const reason = interaction.options.getString("grund");
      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });

      const warnId = await addWarn(guild.id, target.id, user.id, reason);
      const warnCount = (await db.query("SELECT COUNT(*) FROM warns WHERE guild_id=$1 AND user_id=$2", [guild.id, target.id])).rows[0].count;

      await target.user.send({ embeds: [embed(COLORS.warning, "⚠️ Du wurdest verwarnt",
        `**Server:** ${guild.name}\n**Grund:** ${reason}\n**Gesamt:** ${warnCount} Verwarnungen`
      )] }).catch(() => {});

      await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** verwarnt. Warn #${warnId} (Gesamt: ${warnCount})`)] });
      await sendLog(guild, "moderation", embed(COLORS.warning, "⚠️ Warn",
        `**Nutzer:** ${target.user.tag}\n**Moderator:** ${user.tag}\n**Grund:** ${reason}\n**Warn #:** ${warnId}`
      ));

      // Auto-escalation
      const autoMute = await getConfig(guild.id, "warn_automute_count", 3);
      const autoBan  = await getConfig(guild.id, "warn_autoban_count",  5);
      if (parseInt(warnCount) >= autoBan) {
        await guild.members.ban(target.id, { reason: `Auto-Ban: ${warnCount} Verwarnungen` }).catch(() => {});
        await addCase(guild.id, "Auto-Ban", target.id, target.user.tag, client.user.id, client.user.tag, `${warnCount} Verwarnungen`);
      } else if (parseInt(warnCount) >= autoMute) {
        await target.timeout(30 * 60 * 1000, `Auto-Mute: ${warnCount} Verwarnungen`).catch(() => {});
      }
    }

    else if (commandName === "warns") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });
      const warns = await db.query(
        "SELECT id, reason, created_at FROM warns WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 20",
        [guild.id, target.id]
      );
      const e = embed(COLORS.warning, `⚠️ Verwarnungen — ${target.user.tag}`,
        warns.rows.length === 0
          ? "Keine Verwarnungen."
          : warns.rows.map(w => `**#${w.id}** — ${w.reason} · <t:${Math.floor(new Date(w.created_at)/1000)}:R>`).join("\n")
      );
      await interaction.editReply({ embeds: [e] });
    }

    else if (commandName === "delwarn") {
      await deferE();
      const id = interaction.options.getInteger("id");
      const r  = await db.query("DELETE FROM warns WHERE id=$1 AND guild_id=$2 RETURNING id", [id, guild.id]);
      if (r.rowCount === 0) return interaction.editReply({ embeds: [errorEmbed("Warn nicht gefunden.")] });
      await interaction.editReply({ embeds: [successEmbed(`Warn #${id} gelöscht.`)] });
    }

    else if (commandName === "clear") {
      await deferE();
      const amount    = interaction.options.getInteger("anzahl");
      const targetUser = interaction.options.getUser("nutzer");
      const ch = interaction.channel;
      let messages = await ch.messages.fetch({ limit: 100 });
      if (targetUser) messages = messages.filter(m => m.author.id === targetUser.id);
      const toDelete = [...messages.values()].slice(0, amount);
      if (toDelete.length === 0) return interaction.editReply({ embeds: [errorEmbed("Keine Nachrichten zum Löschen.")] });
      await ch.bulkDelete(toDelete, true).catch(() => {});
      await interaction.editReply({ embeds: [successEmbed(`${toDelete.length} Nachricht(en) gelöscht.`)] });
    }

    else if (commandName === "slowmode") {
      await deferE();
      const secs = interaction.options.getInteger("sekunden");
      await interaction.channel.setRateLimitPerUser(secs);
      await interaction.editReply({ embeds: [successEmbed(secs === 0 ? "Slowmode deaktiviert." : `Slowmode auf ${secs}s gesetzt.`)] });
    }

    else if (commandName === "lock") {
      await deferE();
      const reason = interaction.options.getString("grund") || "Channel gesperrt";
      await interaction.channel.permissionOverwrites.edit(guild.id, { SendMessages: false });
      await interaction.editReply({ embeds: [successEmbed(`🔒 Channel gesperrt. Grund: ${reason}`)] });
      await interaction.channel.send({ embeds: [embed(COLORS.danger, "🔒 Channel gesperrt", reason)] });
    }

    else if (commandName === "unlock") {
      await deferE();
      await interaction.channel.permissionOverwrites.edit(guild.id, { SendMessages: null });
      await interaction.editReply({ embeds: [successEmbed("🔓 Channel entsperrt.")] });
      await interaction.channel.send({ embeds: [embed(COLORS.success, "🔓 Channel entsperrt", "Ihr könnt wieder schreiben!")] });
    }

    else if (commandName === "nick") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      const name   = interaction.options.getString("name") || null;
      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });
      try {
        await target.setNickname(name);
        await interaction.editReply({ embeds: [successEmbed(name ? `Nickname auf **${name}** gesetzt.` : "Nickname zurückgesetzt.")] });
      } catch {
        await interaction.editReply({ embeds: [errorEmbed("Konnte Nickname nicht setzen (fehlende Berechtigung?).")] });
      }
    }

    // ──────────────────────────────
    // CASES
    // ──────────────────────────────

    else if (commandName === "case") {
      await deferE();
      const id = interaction.options.getInteger("id");
      const r  = await db.query("SELECT * FROM cases WHERE id=$1 AND guild_id=$2", [id, guild.id]);
      if (r.rows.length === 0) return interaction.editReply({ embeds: [errorEmbed(`Case #${id} nicht gefunden.`)] });
      const c = r.rows[0];
      await interaction.editReply({ embeds: [embed(COLORS.primary, `📁 Case #${c.id}`,
        `**Typ:** ${c.type}\n**Nutzer:** <@${c.user_id}> (${c.user_tag})\n**Moderator:** <@${c.mod_id}> (${c.mod_tag})\n**Grund:** ${c.reason}${c.duration ? `\n**Dauer:** ${c.duration}` : ""}\n**Datum:** <t:${Math.floor(new Date(c.created_at)/1000)}:F>`
      )] });
    }

    else if (commandName === "cases") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      if (!target) return interaction.editReply({ embeds: [errorEmbed("Nutzer nicht gefunden.")] });
      const r = await db.query(
        "SELECT id,type,reason,created_at FROM cases WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 15",
        [guild.id, target.id]
      );
      await interaction.editReply({ embeds: [embed(COLORS.primary, `📁 Cases — ${target.user.tag}`,
        r.rows.length === 0
          ? "Keine Cases."
          : r.rows.map(c => `**#${c.id}** [${c.type}] — ${c.reason.slice(0, 50)} · <t:${Math.floor(new Date(c.created_at)/1000)}:R>`).join("\n")
      )] });
    }

    // ──────────────────────────────
    // UTILITY
    // ──────────────────────────────

    else if (commandName === "userinfo") {
      await deferP();
      const target = interaction.options.getMember("nutzer") || member;
      const u = target.user;
      await interaction.editReply({ embeds: [
        embed(COLORS.primary, `👤 ${u.tag}`)
          .setThumbnail(u.displayAvatarURL({ size: 256 }))
          .addFields(
            { name: "ID",               value: u.id,                                            inline: true },
            { name: "Erstellt",          value: `<t:${Math.floor(u.createdTimestamp/1000)}:R>`, inline: true },
            { name: "Beigetreten",       value: `<t:${Math.floor(target.joinedTimestamp/1000)}:R>`, inline: true },
            { name: "Rollen",            value: target.roles.cache.filter(r=>r.id!==guild.id).map(r=>`<@&${r.id}>`).join(" ") || "Keine", inline: false },
            { name: "Bot?",              value: u.bot ? "Ja" : "Nein", inline: true },
          )
      ] });
    }

    else if (commandName === "serverinfo") {
      await deferP();
      await interaction.editReply({ embeds: [
        embed(COLORS.primary, `🏠 ${guild.name}`)
          .setThumbnail(guild.iconURL({ size: 256 }) || "")
          .addFields(
            { name: "ID",          value: guild.id,                                                     inline: true },
            { name: "Inhaber",     value: `<@${guild.ownerId}>`,                                        inline: true },
            { name: "Erstellt",    value: `<t:${Math.floor(guild.createdTimestamp/1000)}:R>`,           inline: true },
            { name: "Mitglieder",  value: guild.memberCount.toString(),                                  inline: true },
            { name: "Channels",    value: guild.channels.cache.size.toString(),                          inline: true },
            { name: "Rollen",      value: guild.roles.cache.size.toString(),                             inline: true },
            { name: "Boost-Level", value: `Level ${guild.premiumTier} (${guild.premiumSubscriptionCount} Boosts)`, inline: true },
          )
      ] });
    }

    else if (commandName === "avatar") {
      await deferP();
      const target = interaction.options.getMember("nutzer") || member;
      const url = target.user.displayAvatarURL({ size: 1024, extension: "png" });
      await interaction.editReply({ embeds: [
        embed(COLORS.primary, `🖼️ Avatar — ${target.user.tag}`)
          .setImage(url)
      ] });
    }

    else if (commandName === "ping") {
      const sent = await interaction.reply({ content: "Messe...", fetchReply: true });
      await interaction.editReply(`🏓 Pong! Bot-Latenz: **${client.ws.ping}ms** · API-Latenz: **${sent.createdTimestamp - interaction.createdTimestamp}ms**`);
    }

    else if (commandName === "botinfo") {
      await deferP();
      const uptime = formatDuration(client.uptime || 0);
      await interaction.editReply({ embeds: [
        embed(COLORS.purple, "ℹ️ ModForge Bot")
          .setThumbnail(client.user.displayAvatarURL({ size: 256 }))
          .addFields(
            { name: "Version",     value: "3.1.0",                       inline: true },
            { name: "Server",      value: `${client.guilds.cache.size}`, inline: true },
            { name: "Nutzer",      value: `${client.users.cache.size}`,  inline: true },
            { name: "Uptime",      value: uptime,                         inline: true },
            { name: "Node.js",     value: process.version,               inline: true },
            { name: "discord.js",  value: require("discord.js").version, inline: true },
            { name: "Dashboard",   value: CONFIG.dashboardUrl,            inline: false },
          )
      ] });
    }

    else if (commandName === "rolleninfo") {
      await deferP();
      const role = interaction.options.getRole("rolle");
      await interaction.editReply({ embeds: [
        embed(role.color || COLORS.primary, `🏷️ ${role.name}`)
          .addFields(
            { name: "ID",       value: role.id,                                                    inline: true },
            { name: "Farbe",    value: role.hexColor,                                              inline: true },
            { name: "Mitglieder", value: role.members.size.toString(),                             inline: true },
            { name: "Erstellt",  value: `<t:${Math.floor(role.createdTimestamp/1000)}:R>`,         inline: true },
            { name: "Hoist",    value: role.hoist ? "Ja" : "Nein",                                inline: true },
            { name: "Erwähnbar",value: role.mentionable ? "Ja" : "Nein",                          inline: true },
          )
      ] });
    }

    // ──────────────────────────────
    // INVITES
    // ──────────────────────────────

    else if (commandName === "invites") {
      await deferE();
      const target = interaction.options.getMember("nutzer") || member;
      const r = await db.query(
        "SELECT COALESCE(SUM(uses),0) AS total FROM invites WHERE guild_id=$1 AND inviter_id=$2",
        [guild.id, target.id]
      );
      const total = parseInt(r.rows[0].total);
      await interaction.editReply({ embeds: [embed(COLORS.info, `📨 Einladungen — ${target.user.tag}`,
        `**${target.user.tag}** hat **${total}** Mitglied(er) eingeladen.`
      )] });
    }

    else if (commandName === "inviteinfo") {
      await deferE();
      const code = interaction.options.getString("code");
      try {
        const inv = await client.fetchInvite(code);
        await interaction.editReply({ embeds: [embed(COLORS.info, `📨 Invite — ${code}`,
          `**Server:** ${inv.guild?.name}\n**Einlader:** ${inv.inviter?.tag || "Unbekannt"}\n**Uses:** ${inv.uses || 0}\n**Ablauf:** ${inv.expiresAt ? `<t:${Math.floor(inv.expiresAt/1000)}:R>` : "Nie"}`
        )] });
      } catch {
        await interaction.editReply({ embeds: [errorEmbed("Invite nicht gefunden.")] });
      }
    }

    // ──────────────────────────────
    // VOICE
    // ──────────────────────────────

    else if (commandName === "vcmute") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      if (!target?.voice.channel) return interaction.editReply({ embeds: [errorEmbed("Nutzer ist in keinem Voice-Channel.")] });
      await target.voice.setMute(true, `Gemuted von ${user.tag}`);
      await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** im Voice gemuted.`)] });
    }

    else if (commandName === "vcunmute") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      if (!target?.voice.channel) return interaction.editReply({ embeds: [errorEmbed("Nutzer ist in keinem Voice-Channel.")] });
      await target.voice.setMute(false, `Entmuted von ${user.tag}`);
      await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** im Voice entmuted.`)] });
    }

    else if (commandName === "vcdeafen") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      if (!target?.voice.channel) return interaction.editReply({ embeds: [errorEmbed("Nutzer ist in keinem Voice-Channel.")] });
      await target.voice.setDeaf(true, `Deafened von ${user.tag}`);
      await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** im Voice deafened.`)] });
    }

    else if (commandName === "vcmove") {
      await deferE();
      const target  = interaction.options.getMember("nutzer");
      const channel = interaction.options.getChannel("channel");
      if (!target?.voice.channel) return interaction.editReply({ embeds: [errorEmbed("Nutzer ist in keinem Voice-Channel.")] });
      await target.voice.setChannel(channel);
      await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** nach **${channel.name}** verschoben.`)] });
    }

    else if (commandName === "vckick") {
      await deferE();
      const target = interaction.options.getMember("nutzer");
      if (!target?.voice.channel) return interaction.editReply({ embeds: [errorEmbed("Nutzer ist in keinem Voice-Channel.")] });
      await target.voice.disconnect(`Gekickt von ${user.tag}`);
      await interaction.editReply({ embeds: [successEmbed(`**${target.user.tag}** aus dem Voice-Channel entfernt.`)] });
    }

    // ──────────────────────────────
    // TICKETS
    // ──────────────────────────────

    else if (commandName === "ticket") {
      await deferE();
      const topic = interaction.options.getString("thema");
      // Check if user already has open ticket
      const existing = await db.query(
        "SELECT channel_id FROM tickets WHERE guild_id=$1 AND user_id=$2 AND status='open'",
        [guild.id, user.id]
      );
      if (existing.rows.length > 0) {
        const ch = guild.channels.cache.get(existing.rows[0].channel_id);
        return interaction.editReply({ embeds: [errorEmbed(`Du hast bereits ein offenes Ticket: ${ch || "Kanal nicht mehr vorhanden"}`)] });
      }
      const channel = await createTicket(guild, user, topic);
      await interaction.editReply({ embeds: [successEmbed(`🎟️ Ticket erstellt: ${channel}`)] });
    }

    else if (commandName === "closeticket") {
      await deferE();
      const reason = interaction.options.getString("grund") || "Kein Grund";
      const ticket = await db.query(
        "SELECT * FROM tickets WHERE channel_id=$1 AND status='open'",
        [interaction.channelId]
      );
      if (ticket.rows.length === 0) return interaction.editReply({ embeds: [errorEmbed("Kein offenes Ticket in diesem Channel.")] });
      await db.query("UPDATE tickets SET status='closed', closed_at=NOW() WHERE channel_id=$1", [interaction.channelId]);
      await interaction.editReply({ embeds: [successEmbed(`Ticket geschlossen. Grund: ${reason}`)] });
      setTimeout(async () => {
        await interaction.channel.delete().catch(() => {});
      }, 5000);
    }

    // ──────────────────────────────
    // CONFIG COMMANDS
    // ──────────────────────────────

    else if (commandName === "setup") {
      await deferE();
      await interaction.editReply({ embeds: [embed(COLORS.primary, "⚙️ ModForge Setup",
        `Willkommen auf dem Server!\n\n**Nächste Schritte:**\n1. Setze Log-Kanäle: \`/setlogchannel\`\n2. Willkommens-Channel: \`/setwelcome\`\n3. Verify einrichten: \`/setverify\`\n4. Auto-Rolle: \`/setautorole\`\n5. Anti-Spam aktivieren: \`/antispam aktiv:true\`\n\n**Dashboard:** ${CONFIG.dashboardUrl}\n\nAlle Einstellungen können auch im Dashboard vorgenommen werden!`
      )] });
    }

    else if (commandName === "setlogchannel") {
      await deferE();
      const modul   = interaction.options.getString("modul").toLowerCase();
      const channel = interaction.options.getChannel("channel");
      await setConfig(guild.id, `log_${modul}`, channel.id);
      await interaction.editReply({ embeds: [successEmbed(`Log-Kanal für **${modul}** → ${channel} gesetzt.`)] });
    }

    else if (commandName === "setwelcome") {
      await deferE();
      const channel = interaction.options.getChannel("channel");
      const msg     = interaction.options.getString("nachricht");
      await setConfig(guild.id, "welcome_channel", channel.id);
      if (msg) await setConfig(guild.id, "welcome_message", msg);
      await interaction.editReply({ embeds: [successEmbed(`Willkommens-Channel: ${channel}\nNachricht: ${msg || "(Standard)"}`)] });
    }

    else if (commandName === "setmutedrolle") {
      await deferE();
      const role = interaction.options.getRole("rolle");
      await setConfig(guild.id, "muted_role", role.id);
      await interaction.editReply({ embeds: [successEmbed(`Muted-Rolle: <@&${role.id}> gesetzt.`)] });
    }

    else if (commandName === "setverify") {
      await deferE();
      const channel = interaction.options.getChannel("channel");
      const role    = interaction.options.getRole("rolle");
      await setConfig(guild.id, "verify_channel", channel.id);
      await setConfig(guild.id, "verify_role", role.id);

      const row = new ActionRowBuilder().addComponents(
        new ButtonBuilder().setCustomId("verify_button").setLabel("✅ Verifizieren").setStyle(ButtonStyle.Success)
      );
      await channel.send({
        embeds: [embed(COLORS.success, "✅ Verifizierung",
          `Klicke den Button unten, um dich zu verifizieren und Zugang zum Server zu erhalten.\n\nDanach erhältst du die Rolle <@&${role.id}>.`
        )],
        components: [row],
      });
      await interaction.editReply({ embeds: [successEmbed(`Verify-System eingerichtet in ${channel}.`)] });
    }

    else if (commandName === "setautorole") {
      await deferE();
      const role = interaction.options.getRole("rolle");
      await setConfig(guild.id, "autorole", role.id);
      await interaction.editReply({ embeds: [successEmbed(`Auto-Rolle: <@&${role.id}> gesetzt.`)] });
    }

    else if (commandName === "antispam") {
      await deferE();
      const aktiv = interaction.options.getBoolean("aktiv");
      const limit = interaction.options.getInteger("limit");
      await setConfig(guild.id, "antispam_enabled", aktiv);
      if (limit) await setConfig(guild.id, "antispam_limit", limit);
      await interaction.editReply({ embeds: [successEmbed(`Anti-Spam ${aktiv ? "aktiviert" : "deaktiviert"}${limit ? ` (Limit: ${limit})` : ""}.`)] });
    }

    else if (commandName === "antinuke") {
      await deferE();
      const aktiv = interaction.options.getBoolean("aktiv");
      await setConfig(guild.id, "antinuke_enabled", aktiv);
      await interaction.editReply({ embeds: [successEmbed(`Anti-Nuke ${aktiv ? "aktiviert" : "deaktiviert"}.`)] });
    }

    else if (commandName === "antiraid") {
      await deferE();
      const aktiv = interaction.options.getBoolean("aktiv");
      const joins  = interaction.options.getInteger("joins");
      await setConfig(guild.id, "antiraid_enabled", aktiv);
      if (joins) await setConfig(guild.id, "antiraid_limit", joins);
      await interaction.editReply({ embeds: [successEmbed(`Anti-Raid ${aktiv ? "aktiviert" : "deaktiviert"}${joins ? ` (Limit: ${joins}/10s)` : ""}.`)] });
    }

    else if (commandName === "dashboard") {
      await interaction.reply({ embeds: [embed(COLORS.primary, "🖥️ Dashboard",
        `Verwalte deinen Server bequem im Web-Dashboard:\n${CONFIG.dashboardUrl}`
      )], ephemeral: true });
    }

    else if (commandName === "help") {
      await interaction.reply({ embeds: [
        embed(COLORS.primary, "❓ ModForge Hilfe", null)
          .addFields(
            { name: "🔨 Moderation",    value: "`/ban` `/unban` `/kick` `/mute` `/unmute` `/warn` `/warns` `/clear` `/lock` `/unlock` `/slowmode` `/nick`", inline: false },
            { name: "📁 Cases",          value: "`/case` `/cases` `/delwarn`",               inline: false },
            { name: "🎟️ Tickets",        value: "`/ticket` `/closeticket`",                  inline: false },
            { name: "📨 Invites",         value: "`/invites` `/inviteinfo`",                  inline: false },
            { name: "🎙️ Voice",           value: "`/vcmute` `/vcunmute` `/vcdeafen` `/vcmove` `/vckick`", inline: false },
            { name: "⚙️ Konfiguration",   value: "`/setup` `/setlogchannel` `/setwelcome` `/setverify` `/setautorole` `/antispam` `/antinuke` `/antiraid`", inline: false },
            { name: "ℹ️ Sonstiges",       value: "`/userinfo` `/serverinfo` `/avatar` `/ping` `/botinfo` `/dashboard`", inline: false },
            { name: "🖥️ Dashboard",       value: CONFIG.dashboardUrl, inline: false },
          )
      ], ephemeral: true });
    }

    else if (commandName === "backup") {
      await deferE();
      const action = interaction.options.getString("aktion");
      if (action === "create") {
        const backup = {
          id:       crypto.randomBytes(4).toString("hex"),
          created:  new Date().toISOString(),
          guild:    guild.name,
          roles:    guild.roles.cache.map(r => ({ id: r.id, name: r.name, color: r.color, position: r.position })),
          channels: guild.channels.cache.map(c => ({ id: c.id, name: c.name, type: c.type })),
        };
        await setConfig(guild.id, `backup_${backup.id}`, backup);
        await interaction.editReply({ embeds: [successEmbed(`💾 Backup erstellt! ID: \`${backup.id}\`\nRollen: ${backup.roles.length} · Channels: ${backup.channels.length}`)] });
      } else {
        const rows = await db.query("SELECT key, value FROM guild_config WHERE guild_id=$1 AND key LIKE 'backup_%'", [guild.id]);
        if (rows.rows.length === 0) return interaction.editReply({ embeds: [errorEmbed("Keine Backups gefunden.")] });
        const list = rows.rows.map(r => {
          try { const b = JSON.parse(r.value); return `\`${b.id}\` — ${b.guild} · <t:${Math.floor(new Date(b.created)/1000)}:R>`; } catch { return r.key; }
        }).join("\n");
        await interaction.editReply({ embeds: [embed(COLORS.info, "💾 Backup-Liste", list)] });
      }
    }

  } catch (err) {
    console.error(`[COMMAND ERROR] ${commandName}:`, err);
    const errMsg = { embeds: [errorEmbed("Ein unerwarteter Fehler ist aufgetreten.")], ephemeral: true };
    if (interaction.deferred) await interaction.editReply(errMsg).catch(() => {});
    else await interaction.reply(errMsg).catch(() => {});
  }
});

// ─────────────────────────────────────────────────────────────
// BUTTON HANDLERS
// ─────────────────────────────────────────────────────────────
async function handleVerifyButton(interaction) {
  const { guild, member } = interaction;
  const roleId = await getConfig(guild.id, "verify_role");
  if (!roleId) return interaction.reply({ embeds: [errorEmbed("Verify-Rolle nicht konfiguriert.")], ephemeral: true });
  const role = guild.roles.cache.get(roleId);
  if (!role)  return interaction.reply({ embeds: [errorEmbed("Verify-Rolle nicht gefunden.")], ephemeral: true });
  if (member.roles.cache.has(roleId))
    return interaction.reply({ embeds: [successEmbed("Du bist bereits verifiziert!")], ephemeral: true });
  await member.roles.add(role);
  await interaction.reply({ embeds: [successEmbed(`✅ Verifiziert! Du hast die Rolle <@&${roleId}> erhalten.`)], ephemeral: true });
  await sendLog(guild, "verify", embed(COLORS.success, "✅ Nutzer verifiziert", `**Nutzer:** ${member.user.tag}`));
}

async function handleCloseTicket(interaction) {
  const { guild, member } = interaction;
  const isMod = member.permissions.has(PermissionFlagsBits.ManageMessages);
  if (!isMod) {
    const ticket = await db.query("SELECT user_id FROM tickets WHERE channel_id=$1 AND status='open'", [interaction.channelId]);
    if (ticket.rows.length === 0 || ticket.rows[0].user_id !== member.id)
      return interaction.reply({ embeds: [errorEmbed("Nur Moderatoren oder der Ticket-Ersteller können schließen.")], ephemeral: true });
  }
  await db.query("UPDATE tickets SET status='closed', closed_at=NOW() WHERE channel_id=$1", [interaction.channelId]);
  await interaction.reply({ embeds: [embed(COLORS.danger, "🔒 Ticket geschlossen", "Channel wird in 5 Sekunden gelöscht.")] });
  setTimeout(() => interaction.channel.delete().catch(() => {}), 5000);
}

async function handleClaimTicket(interaction) {
  const { member } = interaction;
  const isMod = member.permissions.has(PermissionFlagsBits.ManageMessages);
  if (!isMod) return interaction.reply({ embeds: [errorEmbed("Nur Moderatoren können Tickets claimen.")], ephemeral: true });
  await interaction.channel.permissionOverwrites.edit(member.id, { ViewChannel: true, SendMessages: true });
  await interaction.reply({ embeds: [successEmbed(`📌 Ticket geclaimed von ${member.user.tag}.`)] });
}

// ─────────────────────────────────────────────────────────────
// EXPRESS API (Dashboard OAuth2 + REST API)
// ─────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());
app.use(cors({
  origin: CONFIG.dashboardUrl,
  credentials: true,
}));

// Simple in-memory session store (for production use Redis)
const sessions = new Map();

function generateToken() { return crypto.randomBytes(32).toString("hex"); }

function authMiddleware(req, res, next) {
  const token = req.headers.authorization?.replace("Bearer ", "");
  if (!token || !sessions.has(token)) return res.status(401).json({ error: "Nicht autorisiert" });
  req.session = sessions.get(token);
  next();
}

// ── Discord OAuth2 ──
app.get("/api/auth/login", (req, res) => {
  const state    = crypto.randomBytes(16).toString("hex");
  const redirectUri = encodeURIComponent(`${CONFIG.dashboardUrl}/api/auth/callback`);
  const url = `https://discord.com/oauth2/authorize?client_id=${CONFIG.clientId}&redirect_uri=${redirectUri}&response_type=code&scope=identify+guilds&state=${state}`;
  res.json({ url });
});

app.get("/api/auth/callback", async (req, res) => {
  const { code } = req.query;
  if (!code) return res.status(400).json({ error: "Kein Code" });

  try {
    // Exchange code for token
    const tokenRes = await fetch("https://discord.com/api/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id:     CONFIG.clientId,
        client_secret: CONFIG.clientSecret,
        grant_type:    "authorization_code",
        code,
        redirect_uri:  `${CONFIG.dashboardUrl}/api/auth/callback`,
      }),
    });
    const tokenData = await tokenRes.json();
    if (!tokenData.access_token) return res.status(400).json({ error: "OAuth2-Fehler", details: tokenData });

    // Fetch user
    const userRes  = await fetch("https://discord.com/api/users/@me", { headers: { Authorization: `Bearer ${tokenData.access_token}` } });
    const userData = await userRes.json();

    // Fetch guilds
    const guildsRes  = await fetch("https://discord.com/api/users/@me/guilds", { headers: { Authorization: `Bearer ${tokenData.access_token}` } });
    const guildsData = await guildsRes.json();

    const sessionToken = generateToken();
    sessions.set(sessionToken, {
      user:   userData,
      guilds: guildsData,
      accessToken: tokenData.access_token,
    });
    setTimeout(() => sessions.delete(sessionToken), tokenData.expires_in * 1000);

    // Redirect to dashboard with token
    res.redirect(`${CONFIG.dashboardUrl}/?token=${sessionToken}`);
  } catch (err) {
    console.error("OAuth2 error:", err);
    res.status(500).json({ error: "OAuth2-Fehler" });
  }
});

app.get("/api/auth/me", authMiddleware, (req, res) => {
  res.json({ user: req.session.user, guilds: req.session.guilds });
});

app.post("/api/auth/logout", authMiddleware, (req, res) => {
  const token = req.headers.authorization?.replace("Bearer ", "");
  sessions.delete(token);
  res.json({ ok: true });
});

// ── Guild API ──
app.get("/api/guilds/:id", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const guild = client.guilds.cache.get(id);
  if (!guild) return res.status(404).json({ error: "Guild nicht gefunden (Bot ist nicht auf diesem Server)" });

  const userGuild = req.session.guilds.find(g => g.id === id);
  if (!userGuild) return res.status(403).json({ error: "Kein Zugriff" });
  const hasAdmin = (BigInt(userGuild.permissions) & BigInt(0x8)) === BigInt(0x8);
  if (!hasAdmin) return res.status(403).json({ error: "Keine Administratorrechte" });

  res.json({
    id:          guild.id,
    name:        guild.name,
    icon:        guild.iconURL({ size: 256 }),
    memberCount: guild.memberCount,
    channels:    guild.channels.cache.filter(c => c.type === ChannelType.GuildText).map(c => ({ id: c.id, name: c.name })),
    roles:       guild.roles.cache.filter(r => r.id !== guild.id).map(r => ({ id: r.id, name: r.name, color: r.hexColor })),
  });
});

app.get("/api/guilds/:id/config", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const rows = await db.query("SELECT key, value FROM guild_config WHERE guild_id=$1", [id]);
  const config = {};
  for (const row of rows.rows) {
    try { config[row.key] = JSON.parse(row.value); } catch { config[row.key] = row.value; }
  }
  res.json(config);
});

app.post("/api/guilds/:id/config", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const updates = req.body;
  for (const [key, value] of Object.entries(updates)) {
    await setConfig(id, key, value);
  }
  res.json({ ok: true });
});

app.get("/api/guilds/:id/cases", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const { page = 1, limit = 20, type } = req.query;
  const offset = (parseInt(page) - 1) * parseInt(limit);
  let query = "SELECT * FROM cases WHERE guild_id=$1";
  const params = [id];
  if (type) { query += " AND type=$2"; params.push(type); }
  query += ` ORDER BY created_at DESC LIMIT ${parseInt(limit)} OFFSET ${offset}`;
  const r = await db.query(query, params);
  const count = await db.query("SELECT COUNT(*) FROM cases WHERE guild_id=$1", [id]);
  res.json({ cases: r.rows, total: parseInt(count.rows[0].count) });
});

app.get("/api/guilds/:id/warns", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const { userId } = req.query;
  let query = "SELECT * FROM warns WHERE guild_id=$1";
  const params = [id];
  if (userId) { query += " AND user_id=$2"; params.push(userId); }
  query += " ORDER BY created_at DESC LIMIT 50";
  const r = await db.query(query, params);
  res.json(r.rows);
});

app.get("/api/guilds/:id/audit", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const r = await db.query(
    "SELECT * FROM audit_log WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 50", [id]
  );
  res.json(r.rows);
});

app.get("/api/guilds/:id/tickets", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const r = await db.query(
    "SELECT * FROM tickets WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 50", [id]
  );
  res.json(r.rows);
});

app.get("/api/guilds/:id/stats", authMiddleware, async (req, res) => {
  const { id } = req.params;
  const guild = client.guilds.cache.get(id);
  const [cases7d, warns, bans, members] = await Promise.all([
    db.query("SELECT COUNT(*) FROM cases WHERE guild_id=$1 AND created_at > NOW()-INTERVAL'7 days'", [id]),
    db.query("SELECT COUNT(*) FROM warns WHERE guild_id=$1 AND created_at > NOW()-INTERVAL'7 days'", [id]),
    db.query("SELECT COUNT(*) FROM cases WHERE guild_id=$1 AND type='Ban' AND created_at > NOW()-INTERVAL'7 days'", [id]),
    db.query("SELECT COUNT(*) FROM join_tracker WHERE guild_id=$1", [id]),
  ]);
  res.json({
    memberCount:  guild?.memberCount || 0,
    cases7d:      parseInt(cases7d.rows[0].count),
    warns7d:      parseInt(warns.rows[0].count),
    bans7d:       parseInt(bans.rows[0].count),
    totalJoins:   parseInt(members.rows[0].count),
  });
});

// Health check for Railway
app.get("/health", (req, res) => res.json({ status: "ok", bot: client.isReady() }));
app.get("/",       (req, res) => res.json({ name: "ModForge Bot API", version: "3.1.0" }));

// ─────────────────────────────────────────────────────────────
// GRACEFUL SHUTDOWN
// ─────────────────────────────────────────────────────────────
process.on("SIGTERM", async () => {
  console.log("🛑 Bot wird gestoppt...");
  client.destroy();
  await db.end();
  process.exit(0);
});

process.on("uncaughtException",  err => console.error("[uncaughtException]",  err));
process.on("unhandledRejection", err => console.error("[unhandledRejection]", err));

// ─────────────────────────────────────────────────────────────
// START
// ─────────────────────────────────────────────────────────────
(async () => {
  await initDatabase();
  await registerCommands();

  app.listen(CONFIG.port, () => console.log(`🌐 API-Server läuft auf Port ${CONFIG.port}`));

  await client.login(CONFIG.token);
})();
