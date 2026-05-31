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
     TAB SYSTEM v3
     ARIA-konform, Keyboard-Navigation (◀ ▶ Home End),
     Hash-Persist mit Group-Prefix damit mehrere Tab-Gruppen
     gleichzeitig auf einer Seite arbeiten können.
     ═══════════════════════════════════════════════════════════ */
  function initTabs() {
    document.querySelectorAll('.mf-tabs').forEach(group => {
      const groupName = group.dataset.tabGroup || 'default';

      // ARIA setup
      group.setAttribute('role', 'tablist');
      const tabs = [...group.querySelectorAll('.mf-tab')];
      tabs.forEach((t, idx) => {
        t.setAttribute('role', 'tab');
        t.setAttribute('tabindex', t.classList.contains('active') ? '0' : '-1');
        const target = t.dataset.tab;
        if (target) {
          t.setAttribute('aria-controls', `panel-${groupName}-${target}`);
          t.setAttribute('aria-selected', t.classList.contains('active') ? 'true' : 'false');
          t.id = `tab-${groupName}-${target}`;
        }
      });

      // Pair panels with ARIA
      document.querySelectorAll(`.mf-tab-panel[data-tab-group="${groupName}"], .mf-tab-panel:not([data-tab-group])`).forEach(p => {
        if (p.dataset.tabGroup && p.dataset.tabGroup !== groupName) return;
        const tab = p.dataset.tabPanel;
        if (tab) {
          p.setAttribute('role', 'tabpanel');
          p.id = `panel-${groupName}-${tab}`;
          p.setAttribute('aria-labelledby', `tab-${groupName}-${tab}`);
        }
      });

      // Click handler
      group.addEventListener('click', e => {
        const btn = e.target.closest('.mf-tab');
        if (!btn) return;
        const tab = btn.dataset.tab;
        if (!tab) return;
        switchTab(group, groupName, tab, btn);
      });

      // Keyboard navigation
      group.addEventListener('keydown', e => {
        const focused = document.activeElement;
        if (!focused?.classList?.contains('mf-tab')) return;
        const tabs = [...group.querySelectorAll('.mf-tab')];
        let idx = tabs.indexOf(focused);
        if (idx < 0) return;
        let next = null;
        switch (e.key) {
          case 'ArrowRight': next = tabs[(idx + 1) % tabs.length]; break;
          case 'ArrowLeft':  next = tabs[(idx - 1 + tabs.length) % tabs.length]; break;
          case 'Home':       next = tabs[0]; break;
          case 'End':        next = tabs[tabs.length - 1]; break;
          case 'Enter':
          case ' ':
            e.preventDefault();
            switchTab(group, groupName, focused.dataset.tab, focused);
            return;
        }
        if (next) {
          e.preventDefault();
          next.focus();
        }
      });
    });

    // Restore from hash on load (Format: #group=tab or simple #tab)
    const hash = location.hash.replace('#', '');
    if (hash) {
      // Try qualified format first
      if (hash.includes('=')) {
        const [g, t] = hash.split('=');
        const btn = document.querySelector(`.mf-tabs[data-tab-group="${g}"] .mf-tab[data-tab="${t}"]`);
        if (btn) btn.click();
      } else {
        // Find any tab matching this name
        const btn = document.querySelector(`.mf-tab[data-tab="${hash}"]`);
        if (btn) btn.click();
      }
    }
  }

  function switchTab(group, groupName, tab, btn) {
    // Deactivate all siblings + ARIA
    group.querySelectorAll('.mf-tab').forEach(b => {
      b.classList.remove('active');
      b.setAttribute('aria-selected', 'false');
      b.setAttribute('tabindex', '-1');
    });
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    btn.setAttribute('tabindex', '0');

    // Switch panels (scoped to group)
    document.querySelectorAll(`.mf-tab-panel[data-tab-group="${groupName}"], .mf-tab-panel:not([data-tab-group])`).forEach(p => {
      if (p.dataset.tabGroup && p.dataset.tabGroup !== groupName) return;
      p.classList.toggle('active', p.dataset.tabPanel === tab);
    });

    // Smooth-scroll btn into view (when scrolling horizontally on mobile)
    try { btn.scrollIntoView({inline: 'center', block: 'nearest', behavior: 'smooth'}); } catch (e) {}

    // Persist in URL hash (Format: group=tab) — only if NOT the first/default group
    try {
      const url = new URL(location.href);
      url.hash = `${groupName}=${tab}`;
      history.replaceState(null, '', url);
    } catch (e) {}

    // Re-run preview on tab switch
    if (typeof MF.refreshPreview === 'function') MF.refreshPreview();
    // Emit event for plugins (e.g. logs.html depends on tab-change for filtering)
    group.dispatchEvent(new CustomEvent('mf:tab-change', {detail: {group: groupName, tab}}));
  }

  // Helper: programmatisch Tab wechseln
  MF.switchTo = function(groupName, tab) {
    const btn = document.querySelector(`.mf-tabs[data-tab-group="${groupName}"] .mf-tab[data-tab="${tab}"]`);
    if (btn) btn.click();
  };

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
     LIVE BUS — SocketIO + Polling fallback
     Subscribed automatisch zur aktuellen Guild und feuert
     `mf:activity` Events auf window damit Seiten reagieren können.
     ═══════════════════════════════════════════════════════════ */
  MF.liveListeners = [];
  MF.onLive = function(handler) {
    MF.liveListeners.push(handler);
  };

  function _dispatchLive(evt) {
    try {
      window.dispatchEvent(new CustomEvent('mf:activity', {detail: evt}));
    } catch (e) {}
    MF.liveListeners.forEach(h => { try { h(evt); } catch (e) { console.error(e); } });
  }

  MF.lastLiveTs = 0;
  MF.liveBufferLast = []; // dedup ring

  function _ingest(evt) {
    if (!evt) return;
    const key = (evt.kind || '') + ':' + (evt.text || '') + ':' + (evt._ts_unix || evt.ts || '');
    if (MF.liveBufferLast.includes(key)) return;
    MF.liveBufferLast.push(key);
    if (MF.liveBufferLast.length > 200) MF.liveBufferLast.shift();
    if (evt._ts_unix && evt._ts_unix > MF.lastLiveTs) MF.lastLiveTs = evt._ts_unix;
    _dispatchLive(evt);
  }

  function startPolling() {
    if (!MF.guildId) return;
    let consecutiveErrors = 0;
    const tick = async () => {
      try {
        const url = `/api/guild/${MF.guildId}/live/feed?limit=20${MF.lastLiveTs ? `&since=${MF.lastLiveTs}` : ''}`;
        const r = await fetch(url, {cache: 'no-store'});
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        consecutiveErrors = 0;
        (d.activity || []).reverse().forEach(_ingest);
      } catch (e) {
        consecutiveErrors++;
        if (consecutiveErrors > 5) console.warn('[MF] live polling errors:', e.message);
      }
    };
    tick();
    setInterval(tick, 4000);
  }

  function startSocket() {
    if (typeof io === 'undefined' || !MF.guildId) {
      startPolling();
      return;
    }
    try {
      const sock = io({transports: ['websocket', 'polling'], reconnection: true});
      MF.socket = sock;
      sock.on('connect', () => {
        sock.emit('subscribe_guild', {guild_id: parseInt(MF.guildId)});
        window.dispatchEvent(new CustomEvent('mf:socket', {detail: {connected: true}}));
      });
      sock.on('disconnect', () => {
        window.dispatchEvent(new CustomEvent('mf:socket', {detail: {connected: false}}));
      });
      sock.on('activity', _ingest);
      sock.on('status_update', d => {
        window.dispatchEvent(new CustomEvent('mf:status', {detail: d}));
      });
      // Polling als Backup für Events die wir verpasst haben
      setInterval(async () => {
        try {
          const url = `/api/guild/${MF.guildId}/live/feed?limit=10${MF.lastLiveTs ? `&since=${MF.lastLiveTs}` : ''}`;
          const r = await fetch(url, {cache: 'no-store'});
          if (!r.ok) return;
          const d = await r.json();
          (d.activity || []).reverse().forEach(_ingest);
        } catch (e) {}
      }, 8000);
    } catch (e) {
      console.warn('[MF] socket init failed, polling fallback:', e);
      startPolling();
    }
  }

  function startLive() {
    if (!MF.guildId) return;
    // Lade SocketIO falls noch nicht da
    if (typeof io === 'undefined') {
      const s = document.createElement('script');
      s.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
      s.onload = startSocket;
      s.onerror = startPolling;
      document.head.appendChild(s);
    } else {
      startSocket();
    }
  }

  // Auto-start once DOM ready
  setTimeout(startLive, 200);

  /* ═══════════════════════════════════════════════════════════
     LIVE STATS — periodisches Fetch von /api/guild/<id>/live/stats
     Pages können MF.onStats(fn) registrieren
     ═══════════════════════════════════════════════════════════ */
  MF.statsListeners = [];
  MF.lastStats = null;
  MF.onStats = function(handler) {
    MF.statsListeners.push(handler);
    if (MF.lastStats) try { handler(MF.lastStats); } catch (e) {}
  };

  async function _fetchStats() {
    if (!MF.guildId) return;
    try {
      const r = await fetch(`/api/guild/${MF.guildId}/live/stats`, {cache: 'no-store'});
      if (!r.ok) return;
      const d = await r.json();
      MF.lastStats = d;
      MF.statsListeners.forEach(h => { try { h(d); } catch (e) { console.error(e); } });
      window.dispatchEvent(new CustomEvent('mf:stats', {detail: d}));
    } catch (e) {}
  }

  function startStatsPoll() {
    if (!MF.guildId) return;
    _fetchStats();
    setInterval(_fetchStats, 10000);
  }
  setTimeout(startStatsPoll, 500);

  /* ═══════════════════════════════════════════════════════════
     CONNECTION INDICATOR — kleiner Live-Status oben rechts
     ═══════════════════════════════════════════════════════════ */
  function injectConnIndicator() {
    if (document.getElementById('mfConnInd') || !MF.guildId) return;
    const ind = document.createElement('div');
    ind.id = 'mfConnInd';
    ind.style.cssText = 'position:fixed;top:14px;right:18px;z-index:9990;display:flex;align-items:center;gap:6px;padding:5px 10px;border-radius:999px;background:rgba(8,8,20,0.85);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.06);font-size:.65rem;font-weight:700;color:var(--muted);pointer-events:none;transition:all .3s';
    ind.innerHTML = '<span id="mfConnDot" style="width:7px;height:7px;border-radius:50%;background:var(--muted)"></span><span id="mfConnTxt">Verbinde…</span>';
    document.body.appendChild(ind);
    window.addEventListener('mf:socket', e => {
      const c = e.detail.connected;
      document.getElementById('mfConnDot').style.background = c ? 'var(--green)' : 'var(--red)';
      document.getElementById('mfConnDot').style.boxShadow = c ? '0 0 8px rgba(74,222,128,0.6)' : 'none';
      document.getElementById('mfConnTxt').textContent = c ? 'Live' : 'Getrennt';
      ind.style.color = c ? 'var(--green)' : 'var(--red)';
    });
  }
  setTimeout(injectConnIndicator, 800);

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
