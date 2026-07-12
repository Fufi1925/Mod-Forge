const { MessageFlags } = require('discord.js');
const { buildTicketPanel, buildTicketControls, buildModal } = require('../bot/cogs/tickets');

function assertNoEmbeds(payload, label) {
  if ('embeds' in payload || 'content' in payload) throw new Error(`${label} enthält verbotene content/embeds Felder`);
  if ((payload.flags & MessageFlags.IsComponentsV2) !== MessageFlags.IsComponentsV2) throw new Error(`${label} hat kein IsComponentsV2 Flag`);
  const json = JSON.stringify(payload.components.map(component => component.toJSON()));
  if (/"embeds"/.test(json)) throw new Error(`${label} enthält Legacy-Embeds`);
}

async function main() {
  const settings = { panel_title: 'Support', panel_description: 'Kategorie wählen', panel_placeholder: 'Auswählen', claim_enabled: true, unclaim_enabled: true };
  const category = { key: 'support', name: 'Support', description: 'Technische Hilfe', emoji: '🛠️', enabled: true, modal_enabled: true, modal_questions: [
    { id: 'topic', label: 'Worum geht es?', style: 'short', required: true, min_length: 3, max_length: 100 },
    { id: 'description', label: 'Beschreibe dein Problem', style: 'paragraph', required: true, min_length: 10, max_length: 1000 },
  ] };
  const panel = buildTicketPanel(settings, [category]);
  assertNoEmbeds(panel, 'Ticket-Panel');
  const panelJson = panel.components[0].toJSON();
  if (panelJson.type !== 17 || !JSON.stringify(panelJson).includes('mf:t:create')) throw new Error('Panel enthält keinen Components-V2 Container mit Select-Menü');

  const ticket = { ticket_id: 42, owner_id: '222222222222222222', category_key: 'support', status: 'open', created_at: new Date(), modal_answers: [{ label: 'Worum geht es?', value: 'Test' }] };
  const controls = buildTicketControls(ticket, category, settings);
  assertNoEmbeds(controls, 'Ticket-Control-Nachricht');
  const controlJson = JSON.stringify(controls.components[0].toJSON());
  for (const customId of ['mf:t:claim:42', 'mf:t:unclaim:42', 'mf:t:close:42', 'mf:t:archive:42', 'mf:t:delete:42']) if (!controlJson.includes(customId)) throw new Error(`Ticket-Button fehlt: ${customId}`);

  const { modal, questions } = buildModal(category);
  if (questions.length !== 2 || modal.toJSON().components.length !== 2 || modal.toJSON().custom_id !== 'mf:t:modal:support') throw new Error('Modal-Fragen wurden nicht korrekt gebaut');
  console.log('Ticket Components V2 Test erfolgreich: Panel, Dropdown, Buttons, Modal und Embed-Verbot');
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
