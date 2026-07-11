process.env.IP_HASH_SECRET = 'a'.repeat(64);

const { Collection, PermissionFlagsBits } = require('discord.js');
const { ipFingerprint, fingerprintLabel } = require('../web/server');
const { enforceBlockedUserEverywhere, removeBlockedUserEverywhere } = require('../bot/bot');

async function main() {
  const first = ipFingerprint('203.0.113.42');
  const second = ipFingerprint('203.0.113.42');
  const different = ipFingerprint('203.0.113.43');
  if (first !== second || first === different || first.includes('203.0.113.42')) throw new Error('IP-HMAC-Fingerprint ist nicht deterministisch oder nicht sicher abstrahiert');
  if (!fingerprintLabel(first).startsWith('IP-FP-')) throw new Error('Fingerprint-Label fehlt');

  const ownerMessages = [];
  const events = [];
  let globallyBanned = false;
  const successfulGuild = {
    id: '100000000000000001', name: 'Success Guild', ownerId: '400000000000000001',
    members: { me: { permissions: { has: permission => permission === PermissionFlagsBits.BanMembers } }, async ban(id) { if (id !== '222222222222222222') throw new Error('Falsche ID'); globallyBanned = true; return true; } },
    bans: { async fetch() { return globallyBanned ? { user: { id: '222222222222222222' } } : null; }, async remove() { globallyBanned = false; } },
    async fetchOwner() { return { async send(message) { ownerMessages.push(message); } }; },
  };
  const failingGuild = {
    id: '100000000000000002', name: 'Fail Guild', ownerId: '400000000000000002',
    members: { me: { permissions: { has: () => false } }, async ban() { throw new Error('Sollte wegen fehlender Rechte nicht aufgerufen werden'); } },
    bans: { async fetch() { return null; }, async remove() {} },
    async fetchOwner() { return { async send(message) { ownerMessages.push(message); } }; },
  };
  const eventCollection = { async findOne() { return null; } };
  const bot = {
    user: { id: '999999999999999999' },
    guilds: { cache: new Collection([[successfulGuild.id, successfulGuild], [failingGuild.id, failingGuild]]) },
    db: {
      isGlobalDiscordBlocked: id => id === '222222222222222222',
      global_security_events: eventCollection,
      async recordGlobalSecurityEvent(event) { events.push(event); },
    },
  };
  const entry = { value: '222222222222222222', username: 'Danger Test', reason: 'Automatischer Sicherheitstest' };
  const results = await enforceBlockedUserEverywhere(bot, entry.value, entry);
  if (results.filter(result => result.ok).length !== 1 || results.filter(result => result.ok === false).length !== 1) throw new Error(`Unerwartete Bann-Ergebnisse: ${JSON.stringify(results)}`);
  if (ownerMessages.length !== 1 || !String(ownerMessages[0].content).includes('Botrolle')) throw new Error('Owner-DM bei fehlenden Bannrechten wurde nicht erzeugt');
  if (!events.some(event => event.type === 'global_ban_success') || !events.some(event => event.type === 'owner_notification')) throw new Error('Global-Security-Audit-Events fehlen');
  const removalResults = await removeBlockedUserEverywhere(bot, entry.value);
  if (globallyBanned || removalResults.filter(result => result.ok).length !== 1) throw new Error('Globales Entbannen beim Entfernen ist fehlgeschlagen');
  console.log('Global-Security-Test erfolgreich: HMAC, Auto-Ban, Fehlerbehandlung, Owner-DM und vollständiges Entbannen');
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
