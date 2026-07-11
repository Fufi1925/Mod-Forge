const { checkPhishingUrl } = require('../utils');
const { COLOR_DANGER, COLOR_WARNING, ACTIVITY } = require('../config');

function regexSource(pattern) {
  return String(pattern || '').replace(/^\(\?i\)/, '');
}

function findAutomodHit(config, content) {
  const lower = String(content || '').toLowerCase();
  for (const word of config.bad_words || []) {
    const normalized = String(word || '').trim().toLowerCase();
    if (normalized && lower.includes(normalized)) return { type: 'BadWord', detail: word };
  }
  for (const pattern of config.regex_patterns || config.regex_rules || []) {
    try { if (new RegExp(regexSource(pattern), 'iu').test(content)) return { type: 'Regex', detail: pattern }; }
    catch {}
  }
  if (config.invite_filter && /(?:discord\.gg|discord(?:app)?\.com\/invite)\/[a-z0-9-]+/iu.test(content)) return { type: 'Discord Invite', detail: 'Einladungslink' };
  if (config.zalgo_filter) {
    const combining = (String(content).match(/[\u0300-\u036f]/g) || []).length;
    if (combining >= 8) return { type: 'Zalgo', detail: `${combining} kombinierende Zeichen` };
  }
  if (config.unicode_abuse && /[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]/u.test(content)) return { type: 'Unicode-Abuse', detail: 'Unsichtbare oder bidirektionale Steuerzeichen' };
  if (config.link_filter) {
    const allowed = new Set((config.allowed_domains || []).map(domain => String(domain).toLowerCase().replace(/^www\./, '')));
    const urls = String(content || '').match(/https?:\/\/[^\s<]+/giu) || [];
    for (const value of urls) {
      try {
        const hostname = new URL(value).hostname.toLowerCase().replace(/^www\./, '');
        if (![...allowed].some(domain => hostname === domain || hostname.endsWith(`.${domain}`))) return { type: 'Link-Filter', detail: hostname };
      } catch { return { type: 'Link-Filter', detail: 'Ungültiger Link' }; }
    }
  }
  return null;
}

function findAutoResponse(config, content) {
  const input = String(content || '').trim().toLowerCase();
  if (!input) return null;
  return (config.auto_responses || []).find(rule => {
    if (rule?.enabled === false) return false;
    const trigger = String(rule?.trigger || '').trim().toLowerCase();
    if (!trigger) return false;
    if (rule.match === 'exact') return input === trigger;
    if (rule.match === 'starts_with') return input.startsWith(trigger);
    return input.includes(trigger);
  }) || null;
}

const events = [{
  name: 'messageCreate',
  async execute(bot, message) {
    if (!message.guild || message.author.bot || !message.member) return;
    const cfg = await bot.db.fetchConfig(message.guild.id);
    if (bot.isWhitelisted(message.member)) return;
    const content = message.content || '';

    if (cfg.anti_scam?.enabled || cfg.automod?.phishing_check) {
      const hit = checkPhishingUrl(content);
      if (hit.detected) {
        await message.delete().catch(() => null);
        const punishment = cfg.anti_scam?.punishment || cfg.automod?.punishment || 'timeout';
        await bot.punish(message.member, punishment, `Anti-Scam: ${hit.domain}`, cfg.anti_scam?.timeout_duration || 3600).catch(() => null);
        await bot.logAction(message.guild, '🎣 Anti-Scam', `${message.author} verdächtiger Link: **${hit.domain}**`, COLOR_DANGER, { module: 'antiscam', user: message.author });
        ACTIVITY.push('antiscam', `${message.author.tag} verdächtiger Link ${hit.domain}`, { guild_id: message.guild.id, guild_name: message.guild.name });
        return;
      }
    }

    if (cfg.automod?.enabled) {
      const hit = findAutomodHit(cfg.automod, content);
      if (hit) {
        await message.delete().catch(() => null);
        const punishment = cfg.automod.punishment || 'warn';
        await bot.punish(message.member, punishment, `AutoMod ${hit.type}: ${hit.detail}`, cfg.automod.timeout_duration || 600).catch(() => null);
        await bot.logAction(message.guild, `🤖 AutoMod · ${hit.type}`, `**User:** ${message.author}\n**Treffer:** ${hit.detail}\n**Aktion:** ${punishment}`, COLOR_WARNING, { module: 'automod', user: message.author });
        ACTIVITY.push('automod', `${message.author.tag}: ${hit.type}`, { guild_id: message.guild.id, guild_name: message.guild.name });
        return;
      }
    }

    if (cfg.anti_mention?.enabled) {
      const mentions = message.mentions.users.size + message.mentions.roles.size + (message.mentions.everyone ? 1 : 0);
      const limit = Number(cfg.anti_mention.mention_limit || 5);
      if (mentions >= limit) {
        await message.delete().catch(() => null);
        const punishment = cfg.anti_mention.punishment || 'timeout';
        await bot.punish(message.member, punishment, `Anti-Mention: ${mentions} Mentions`, cfg.anti_mention.timeout_duration || 600).catch(() => null);
        await bot.logAction(message.guild, '🔔 Anti-Mention', `${message.author} verwendete **${mentions}** Mentions.`, COLOR_DANGER, { module: 'antimention', user: message.author });
        return;
      }
    }

    if (cfg.anti_spam?.enabled) {
      const key = `${message.guild.id}:${message.author.id}`;
      const entries = bot.tracker.spamTracker.get(key) || [];
      const now = Date.now();
      const windowSeconds = Number(cfg.anti_spam.msg_window || cfg.anti_spam.window || 10);
      const limit = Number(cfg.anti_spam.msg_limit || cfg.anti_spam.max_messages || 5);
      entries.push(now);
      while (entries.length && now - entries[0] > windowSeconds * 1000) entries.shift();
      bot.tracker.spamTracker.set(key, entries);
      if (entries.length >= limit) {
        bot.tracker.spamTracker.set(key, []);
        const punishment = cfg.anti_spam.punishment || 'timeout';
        await bot.punish(message.member, punishment, `Anti-Spam: ${entries.length} Nachrichten in ${windowSeconds}s`, cfg.anti_spam.timeout_duration || 30).catch(() => null);
        await bot.logAction(message.guild, '⚡ Anti-Spam', `${message.author} wurde wegen Spam bestraft (**${punishment}**).`, COLOR_DANGER, { module: 'antispam', user: message.author });
        return;
      }
    }

    const response = findAutoResponse(cfg, content);
    if (response?.response) {
      await message.reply({ content: String(response.response).slice(0, 2000), allowedMentions: { repliedUser: false, parse: [] } }).catch(() => null);
    }
  },
}];

module.exports = { events, findAutomodHit, findAutoResponse };
