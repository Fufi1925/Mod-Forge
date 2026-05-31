/**
 * ModForge Dashboard v2 — Foundation Layer JS
 * Tabs · Collapsibles · Multi-Inputs · Live-Preview Engine · Schema Save
 */
(function () {
  'use strict';

  /* ═══════════════════════════════════════════════════════════
     STATE
     ═══════════════════════════════════════════════════════════ */
  window.MF = window.MF || {};
  MF.dirty = false;
  MF.saving = false;
  MF.dirtyCount = 0;
  MF.previewHandlers = {};        // sectionName -> function(values)
  MF.guildId = null;

  /* ═══════════════════════════════════════════════════════════
     INIT (auto-run on DOMContentLoaded)
     ═══════════════════════════════════════════════════════════ */
  document.addEventListener('DOMContentLoaded', () => {
    MF.guildId = document.body.dataset.guildId || null;
    initTabs();
    initCollapsibles();
    initRangeSliders();
    initColorPickers();
    initMultiInputs();
    initSubNav();
    initChangeTracking();
    initKeyboardShortcuts();
    bootPreview();
  });

  /* ═══════════════════════════════════════════════════════════
     TAB SYSTEM
     ─ <div class="mf-tabs" data-tab-group="mygroup">
         <button class="mf-tab active" data-tab="t1">Tab 1</button>
         <button class="mf-tab" data-tab="t2">Tab 2</button>
       </div>
       <div class="mf-tab-panel active" data-tab-panel="t1" data-tab-group="mygroup">...</div>
     ═══════════════════════════════════════════════════════════ */
  function initTabs() {
    document.querySelectorAll('.mf-tabs').forEach(group => {
      const groupName = group.dataset.tabGroup || 'default';
      group.addEventListener('click', e => {
        const btn = e.target.closest('.mf-tab');
        if (!btn) return;
        const tab = btn.dataset.tab;
        if (!tab) return;
        // Deactivate siblings
        group.querySelectorAll('.mf-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        // Switch panels (scoped to group)
        document.querySelectorAll(`.mf-tab-panel[data-tab-group="${groupName}"], .mf-tab-panel:not([data-tab-group])`).forEach(p => {
          if (p.dataset.tabGroup && p.dataset.tabGroup !== groupName) return;
          p.classList.toggle('active', p.dataset.tabPanel === tab);
        });
        // Persist active tab per-page in URL hash
        try { history.replaceState(null, '', '#' + tab); } catch (e) {}
        // Re-run preview on tab switch
        if (typeof MF.refreshPreview === 'function') MF.refreshPreview();
      });
    });
    // Restore from hash on load
    const hash = location.hash.replace('#', '');
    if (hash) {
      const btn = document.querySelector(`.mf-tab[data-tab="${hash}"]`);
      if (btn) btn.click();
    }
  }

  /* ═══════════════════════════════════════════════════════════
     COLLAPSIBLES
     ═══════════════════════════════════════════════════════════ */
  function initCollapsibles() {
    document.addEventListener('click', e => {
      const h = e.target.closest('.mf-collapse-header');
      if (!h) return;
      h.parentElement.classList.toggle('open');
    });
  }

  /* ═══════════════════════════════════════════════════════════
     RANGE SLIDERS — auto-update fill + value badge
     ═══════════════════════════════════════════════════════════ */
  function initRangeSliders() {
    document.querySelectorAll('.mf-range').forEach(r => {
      const update = () => {
        const min = +r.min || 0;
        const max = +r.max || 100;
        const val = +r.value || 0;
        const pct = ((val - min) / (max - min)) * 100;
        r.style.setProperty('--mf-fill', pct + '%');
        const badge = document.querySelector(`[data-range-value="${r.id}"]`);
        if (badge) {
          const suffix = badge.dataset.suffix || '';
          badge.textContent = val + suffix;
        }
      };
      r.addEventListener('input', update);
      update();
    });
  }

  /* ═══════════════════════════════════════════════════════════
     COLOR PICKERS — sync hex label
     ═══════════════════════════════════════════════════════════ */
  function initColorPickers() {
    document.querySelectorAll('.mf-color input[type="color"]').forEach(c => {
      const hex = c.parentElement.querySelector('.mf-color-hex');
      const update = () => { if (hex) hex.textContent = c.value; };
      c.addEventListener('input', update);
      update();
    });
  }

  /* ═══════════════════════════════════════════════════════════
     MULTI-INPUT (Tag input)
     ─ <div class="mf-multi" data-cfg="automod.bad_words">
         <input placeholder="Wort hinzufügen…">
       </div>
       Initial chips can be pre-rendered server-side OR via data-values="['a','b']"
     ═══════════════════════════════════════════════════════════ */
  function initMultiInputs() {
    document.querySelectorAll('.mf-multi').forEach(multi => {
      const input = multi.querySelector('input');
      if (!input) return;

      // Pre-fill from data-values
      const initial = multi.dataset.values;
      if (initial) {
        try {
          JSON.parse(initial).forEach(v => addChip(multi, v));
        } catch (e) {}
      }

      input.addEventListener('keydown', e => {
        if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
          e.preventDefault();
          addChip(multi, input.value.trim());
          input.value = '';
          markDirty();
        } else if (e.key === 'Backspace' && !input.value) {
          const chips = multi.querySelectorAll('.mf-multi-chip');
          if (chips.length) {
            chips[chips.length - 1].remove();
            markDirty();
          }
        }
      });

      multi.addEventListener('click', e => {
        if (e.target.classList.contains('mf-chip-x')) {
          e.target.parentElement.remove();
          markDirty();
        } else if (!e.target.closest('.mf-multi-chip')) {
          input.focus();
        }
      });
    });
  }

  function addChip(multi, value) {
    if (!value) return;
    // De-dup
    const existing = [...multi.querySelectorAll('.mf-multi-chip')].map(c => c.dataset.value);
    if (existing.includes(value)) return;
    const chip = document.createElement('span');
    chip.className = 'mf-multi-chip';
    chip.dataset.value = value;
    chip.innerHTML = `<span></span><span class="mf-chip-x">×</span>`;
    chip.firstChild.textContent = value;
    multi.insertBefore(chip, multi.querySelector('input'));
  }

  /* Collect helper */
  MF.getMultiValues = function (cfgPath) {
    const el = document.querySelector(`.mf-multi[data-cfg="${cfgPath}"]`);
    if (!el) return [];
    return [...el.querySelectorAll('.mf-multi-chip')].map(c => c.dataset.value);
  };

  /* ═══════════════════════════════════════════════════════════
     SIDEBAR SUB-NAV
     ═══════════════════════════════════════════════════════════ */
  function initSubNav() {
    document.querySelectorAll('.db-nav-section').forEach(sec => {
      const head = sec.querySelector('[data-toggle-sub]');
      if (head) {
        head.addEventListener('click', e => {
          e.preventDefault();
          sec.classList.toggle('open');
        });
      }
      // Auto-open if a child is active
      if (sec.querySelector('a.active')) sec.classList.add('open');
    });
  }

  /* ═══════════════════════════════════════════════════════════
     CHANGE TRACKING (Save Bar)
     ═══════════════════════════════════════════════════════════ */
  function initChangeTracking() {
    // Auto-attach to any element with [data-cfg]
    document.addEventListener('input', e => {
      if (e.target.closest('[data-cfg]')) markDirty();
    });
    document.addEventListener('change', e => {
      if (e.target.closest('[data-cfg]')) markDirty();
    });
    // Browser-leave guard
    window.addEventListener('beforeunload', e => {
      if (MF.dirty) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  function markDirty() {
    if (MF.saving) return;
    MF.dirty = true;
    MF.dirtyCount++;
    const bar = document.getElementById('mfSaveBar');
    if (bar) {
      bar.classList.add('visible');
      const cnt = bar.querySelector('.mf-save-bar-count');
      if (cnt) cnt.textContent = MF.dirtyCount + ' ungespeichert';
    }
    // Trigger preview
    if (typeof MF.refreshPreview === 'function') MF.refreshPreview();
  }

  MF.markDirty = markDirty;
  MF.markClean = function () {
    MF.dirty = false;
    MF.dirtyCount = 0;
    const bar = document.getElementById('mfSaveBar');
    if (bar) bar.classList.remove('visible');
  };

  /* ═══════════════════════════════════════════════════════════
     SCHEMA-BASED SAVE
     Collect all [data-cfg="path.to.key"] inputs into nested object
     ═══════════════════════════════════════════════════════════ */
  MF.collectConfig = function (scope = document) {
    const out = {};
    scope.querySelectorAll('[data-cfg]').forEach(el => {
      const path = el.dataset.cfg;
      if (!path) return;
      let value;
      if (el.classList.contains('mf-multi')) {
        value = [...el.querySelectorAll('.mf-multi-chip')].map(c => c.dataset.value);
      } else if (el.type === 'checkbox') {
        value = el.checked;
      } else if (el.type === 'number' || el.type === 'range') {
        value = el.value === '' ? null : Number(el.value);
      } else if (el.tagName === 'SELECT' && el.multiple) {
        value = [...el.selectedOptions].map(o => o.value);
      } else {
        value = el.value;
      }
      setByPath(out, path, value);
    });
    return out;
  };

  function setByPath(obj, path, value) {
    const parts = path.split('.');
    let cur = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== 'object' || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  MF.saveConfig = async function () {
    if (!MF.guildId) { MF.toast('Keine Guild-ID', 'err'); return; }
    if (MF.saving) return;
    MF.saving = true;
    const data = MF.collectConfig();
    try {
      const r = await fetch(`/api/guild/${MF.guildId}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (r.ok) {
        MF.markClean();
        MF.toast('💾 Gespeichert', 'save');
      } else {
        MF.toast('❌ Fehler beim Speichern (HTTP ' + r.status + ')', 'err');
      }
    } catch (e) {
      MF.toast('❌ Netzwerk-Fehler', 'err');
    } finally {
      MF.saving = false;
    }
  };

  MF.discardChanges = function () {
    MF.markClean();
    MF.toast('↩️ Verworfen', 'info');
    setTimeout(() => location.reload(), 400);
  };

  /* ═══════════════════════════════════════════════════════════
     TOAST (wrapper über bestehende showToast in _base.html)
     ═══════════════════════════════════════════════════════════ */
  MF.toast = function (msg, type) {
    if (typeof window.showToast === 'function') return window.showToast(msg, type);
    console.log('[MF]', type, msg);
  };

  /* ═══════════════════════════════════════════════════════════
     KEYBOARD SHORTCUTS
       Ctrl/Cmd+S → save
       Esc       → discard if modal open
     ═══════════════════════════════════════════════════════════ */
  function initKeyboardShortcuts() {
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (MF.dirty) MF.saveConfig();
      }
    });
  }

  /* ═══════════════════════════════════════════════════════════
     LIVE PREVIEW ENGINE
     ─ Pages register: MF.registerPreview('welcome', (cfg) => html)
     ─ On every change, the engine collects cfg from data-cfg
       fields and re-renders the preview pane.
     ═══════════════════════════════════════════════════════════ */
  MF.registerPreview = function (name, handler) {
    MF.previewHandlers[name] = handler;
  };

  MF.refreshPreview = function () {
    const pane = document.getElementById('mfPreviewBody');
    if (!pane) return;
    const name = pane.dataset.previewName;
    const handler = MF.previewHandlers[name];
    if (typeof handler !== 'function') return;
    try {
      const cfg = MF.collectConfig();
      const html = handler(cfg);
      if (typeof html === 'string') pane.innerHTML = html;
    } catch (e) {
      console.error('[MF] preview error', e);
    }
  };

  function bootPreview() {
    // First render
    setTimeout(MF.refreshPreview, 50);
  }

  /* ═══════════════════════════════════════════════════════════
     HELPER: Discord-Embed builder for previews
     ═══════════════════════════════════════════════════════════ */
  MF.renderDiscordEmbed = function (opts) {
    const o = opts || {};
    const color = o.color || '#5865f2';
    const author = o.author || '';
    const authorIcon = o.authorIcon || '';
    const title = o.title || '';
    const desc = o.description || '';
    const fields = o.fields || [];
    const footer = o.footer || '';
    const footerIcon = o.footerIcon || '';
    const thumb = o.thumbnail || '';
    const image = o.image || '';
    const botName = o.botName || 'ModForge';
    const username = o.username || botName;

    const fieldHtml = fields.map(f =>
      `<div><div class="mf-discord-embed-field-name">${esc(f.name)}</div><div class="mf-discord-embed-field-value">${esc(f.value)}</div></div>`
    ).join('');

    return `
      <div class="mf-discord-msg">
        <div class="mf-discord-author">
          <div class="mf-discord-avatar">🛡️</div>
          <div>
            <span class="mf-discord-username">${esc(username)}</span>
            <span class="mf-discord-bot-tag">BOT</span>
            <span class="mf-discord-time">Heute um ${nowTime()}</span>
          </div>
        </div>
        <div class="mf-discord-embed" style="border-left-color:${esc(color)}">
          ${thumb ? `<img src="${esc(thumb)}" class="mf-discord-embed-thumb" onerror="this.style.display='none'">` : ''}
          ${author ? `<div class="mf-discord-embed-author">${authorIcon ? `<img src="${esc(authorIcon)}" onerror="this.style.display='none'">` : ''}${esc(author)}</div>` : ''}
          ${title ? `<div class="mf-discord-embed-title">${esc(title)}</div>` : ''}
          ${desc ? `<div class="mf-discord-embed-desc">${esc(desc)}</div>` : ''}
          ${fields.length ? `<div class="mf-discord-embed-fields">${fieldHtml}</div>` : ''}
          ${image ? `<img src="${esc(image)}" class="mf-discord-embed-image" onerror="this.style.display='none'">` : ''}
          ${footer ? `<div class="mf-discord-embed-footer">${footerIcon ? `<img src="${esc(footerIcon)}" onerror="this.style.display='none'">` : ''}${esc(footer)}</div>` : ''}
        </div>
      </div>
    `;
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function nowTime() {
    const d = new Date();
    return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
  }

  /* ═══════════════════════════════════════════════════════════
     TEMPLATE-VARIABLE EXPANDER (for Welcome/Leave previews)
     {user}, {user.mention}, {server}, {member_count}, {server.name}
     ═══════════════════════════════════════════════════════════ */
  MF.expandVars = function (text, ctx) {
    if (!text) return '';
    const c = ctx || {};
    const user = c.user || 'TestUser';
    const server = c.server || (document.body.dataset.guildName || 'Mein Server');
    const memberCount = c.memberCount || (document.body.dataset.memberCount || '128');
    return String(text)
      .replace(/\{user\.mention\}/g, '@' + user)
      .replace(/\{user\.name\}/g, user)
      .replace(/\{user\}/g, user)
      .replace(/\{server\.name\}/g, server)
      .replace(/\{server\}/g, server)
      .replace(/\{member_count\}/g, memberCount)
      .replace(/\{members\}/g, memberCount);
  };

  /* ═══════════════════════════════════════════════════════════
     UTIL: per-field cfg getter (for preview handlers)
     ═══════════════════════════════════════════════════════════ */
  MF.get = function (path, fallback) {
    const cfg = MF.collectConfig();
    const parts = path.split('.');
    let cur = cfg;
    for (const p of parts) {
      if (cur == null || typeof cur !== 'object') return fallback;
      cur = cur[p];
    }
    return cur === undefined ? fallback : cur;
  };
})();
