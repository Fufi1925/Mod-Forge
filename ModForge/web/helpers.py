from typing import Optional
import datetime
import logging
from bot.bot import BOT_REF, bot
from bot.config import DEFAULT_CONFIG, VALID_PUNISHMENTS
from bot.utils import _run_async
from database.db import Database

log = logging.getLogger("ModForge.Web.Helpers")

def _bot_stats():
    gc = mc = up = lat = 0
    try:
        if BOT_REF:
            gc = len(BOT_REF.guilds)
            mc = sum(g.member_count or 0 for g in BOT_REF.guilds)
            up = bot.get_uptime(BOT_REF.start_time) if hasattr(bot, 'get_uptime') else 0
            lat = round(BOT_REF.latency * 1000, 1) if BOT_REF.latency else 0
    except Exception:
        pass
    return gc, mc, up, lat

def _get_guild_config(guild_id: str) -> dict:
    if BOT_REF:
        cfg = _run_async(BOT_REF.db.aget_config(int(guild_id)))
        if cfg:
            return cfg
    return DEFAULT_CONFIG.copy()

def _build_overview(cfg: dict, guild_id: str) -> str:
    mods = ["anti_spam", "anti_nuke", "anti_raid", "anti_mention", "automod", "anti_scam"]
    rows = ""
    for m in mods:
        enabled = cfg.get(m, {}).get("enabled")
        status_icon = "✅" if enabled else "❌"
        rows += f"""<div style="display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.04)">
          <span style="font-size:.85rem">{m.replace('_', ' ').title()}</span>
          <span>{status_icon} {'Aktiv' if enabled else 'Inaktiv'}</span>
        </div>"""
    return f"""<div class="kpi-grid" style="margin-bottom:22px">
  <div class="kpi-card"><div class="ico" style="background:rgba(91,110,255,.15)">🛡️</div>
    <div class="num" style="color:var(--p)">{sum(1 for m in mods if cfg.get(m, {}).get('enabled'))}</div>
    <div class="lbl">Aktive Module</div><div class="chg">von {len(mods)}</div></div>
  <div class="kpi-card"><div class="ico" style="background:rgba(34,197,94,.15)">🔒</div>
    <div class="num" style="color:var(--ok)">{cfg.get('security_level', 0)}</div>
    <div class="lbl">Security Level</div><div class="chg">0-3</div></div>
  <div class="kpi-card"><div class="ico" style="background:rgba(234,179,8,.15)">📢</div>
    <div class="num" style="color:#eab308">{len(cfg.get('log_channels') or {})}</div>
    <div class="lbl">Log-Kanäle</div><div class="chg">konfiguriert</div></div>
</div>
<div class="settings-panel"><h3>📊 Modul-Status</h3>{rows}</div>"""

def _build_module_form(section: str, cfg: dict, guild_id: str) -> str:
    mod = {
        "antispam": "anti_spam", "antinuke": "anti_nuke", "antiraid": "anti_raid",
        "antimention": "anti_mention", "antiscam": "anti_scam", "automod": "automod",
        "verify": "verify_system", "tickets": "ticket_system", "autorole": "auto_role",
        "logs": "log_channels", "warns": "warn_system"
    }.get(section, section)
    mcfg = cfg.get(mod, {}) if not isinstance(cfg.get(mod, {}), bool) else {}
    enabled = mcfg.get("enabled", False)
    punishment = mcfg.get("punishment", "warn")
    icon = {
        "antispam": "⚡", "antinuke": "💥", "antiraid": "🚨",
        "antimention": "🔔", "antiscam": "🎣", "automod": "🤖",
        "verify": "✅", "tickets": "🎫", "autorole": "🏷️",
        "logs": "📢", "warns": "⚠️"
    }.get(section, "⚙️")
    pun_opts = "".join(f'<option value="{p}" {"selected" if punishment == p else ""}>{p}</option>'
                       for p in VALID_PUNISHMENTS)
    extra = ""
    if section == "antispam":
        extra = f"""<div class="settings-row"><div><div class="settings-row-label">Max. Nachrichten</div>
          <div class="settings-row-desc">Nachrichten-Limit pro Zeitfenster</div></div>
          <input id="mx" class="form-input" type="number" value="{mcfg.get('max_messages', 7)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Zeitfenster (Sekunden)</div></div>
          <input id="iv" class="form-input" type="number" value="{mcfg.get('interval', 6)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">CAPS-Schwelle (%)</div></div>
          <input id="cp" class="form-input" type="number" value="{mcfg.get('caps_pct', 70)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Max. Emojis</div></div>
          <input id="em" class="form-input" type="number" value="{mcfg.get('emoji_max', 10)}" style="width:80px;text-align:center"></div>"""
    elif section == "antinuke":
        extra = f"""<div class="settings-row"><div><div class="settings-row-label">Ban-Schwelle</div></div>
          <input id="bt" class="form-input" type="number" value="{mcfg.get('ban_threshold', 3)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Kanal-Lösch-Schwelle</div></div>
          <input id="ct" class="form-input" type="number" value="{mcfg.get('channel_delete_threshold', 3)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Zeitfenster (Sekunden)</div></div>
          <input id="ws" class="form-input" type="number" value="{mcfg.get('window_seconds', 10)}" style="width:80px;text-align:center"></div>"""
    elif section == "antiraid":
        extra = f"""<div class="settings-row"><div><div class="settings-row-label">Join-Schwelle</div></div>
          <input id="jt" class="form-input" type="number" value="{mcfg.get('join_threshold', 10)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Zeitfenster (Sekunden)</div></div>
          <input id="ws" class="form-input" type="number" value="{mcfg.get('window_seconds', 15)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Mindest-Account-Alter (Tage)</div></div>
          <input id="ma" class="form-input" type="number" value="{mcfg.get('min_account_age_days', 7)}" style="width:80px;text-align:center"></div>"""
    elif section == "antimention":
        extra = f"""<div class="settings-row"><div><div class="settings-row-label">Max. Mentions</div></div>
          <input id="mm" class="form-input" type="number" value="{mcfg.get('max_mentions', 5)}" style="width:80px;text-align:center"></div>
          <div class="settings-row"><div><div class="settings-row-label">Timeout-Dauer (Sekunden)</div></div>
          <input id="td" class="form-input" type="number" value="{mcfg.get('timeout_seconds', 120)}" style="width:80px;text-align:center"></div>"""

    def save_fn() -> str:
        m = mod
        fields = {"enabled": "getToggle('en')", "punishment": "getVal('pn')"}
        if section == "antispam":
            fields.update({
                "max_messages": "getInt('mx')", "interval": "getInt('iv')",
                "caps_pct": "getInt('cp')", "emoji_max": "getInt('em')"
            })
        elif section == "antinuke":
            fields.update({
                "ban_threshold": "getInt('bt')",
                "channel_delete_threshold": "getInt('ct')",
                "window_seconds": "getInt('ws')"
            })
        elif section == "antiraid":
            fields.update({
                "join_threshold": "getInt('jt')",
                "window_seconds": "getInt('ws')",
                "min_account_age_days": "getInt('ma')"
            })
        elif section == "antimention":
            fields.update({
                "max_mentions": "getInt('mm')",
                "timeout_seconds": "getInt('td')"
            })
        obj = ",".join(f'"{k}":{v}' for k, v in fields.items())
        return f"saveMod('{m}',{{{obj}}})"

    return f"""<div class="settings-panel">
  <h3>{icon} {section.replace('anti', 'Anti-').title()} Einstellungen</h3>
  <div class="settings-row">
    <div><div class="settings-row-label">Aktiviert</div><div class="settings-row-desc">Modul ein- oder ausschalten</div></div>
    <label class="toggle"><input type="checkbox" id="en" {"checked" if enabled else ""}><div class="toggle-track"></div><div class="toggle-thumb"></div></label>
  </div>
  <div class="settings-row">
    <div><div class="settings-row-label">Bestrafung</div><div class="settings-row-desc">Aktion bei Regelverstoß</div></div>
    <select id="pn" class="form-select" style="width:140px">{pun_opts}</select>
  </div>
  {extra}
  <button class="save-btn" id="save-{mod}" onclick="{save_fn()}">Änderungen speichern</button>
</div>"""

def _build_welcome_content(cfg: dict, guild_id: str) -> str:
    wc = cfg.get("welcome", {})
    lc = cfg.get("leave", {})
    wc_col = wc.get("embed_color", "#22c55e")
    lc_col = lc.get("embed_color", "#ef4444")
    EMBED_FOOTER = "ModForge"
    return f"""
<div class="settings-panel">
  <h3>👋 Welcome-Nachricht</h3>
  <p style="font-size:.8rem;color:var(--muted);margin-bottom:16px">
    Wird gesendet wenn ein neues Mitglied beitritt. Variablen:
    <code style="color:var(--p)">{{mention}}</code> <code style="color:var(--p)">{{user}}</code>
    <code style="color:var(--p)">{{server}}</code> <code style="color:var(--p)">{{count}}</code></p>
  <div class="settings-row">
    <div><div class="settings-row-label">Aktiviert</div></div>
    <label class="toggle"><input type="checkbox" id="wc-en" {"checked" if wc.get('enabled') else ""}><div class="toggle-track"></div><div class="toggle-thumb"></div></label>
  </div>
  <div class="embed-builder" style="margin-top:16px">
    <div class="embed-form">
      <div class="form-group">
        <label class="form-label">Titel</label>
        <input class="form-input" id="wc-title" value="{wc.get('embed_title', '👋 Willkommen auf {{server}}!')}">
      </div>
      <div class="form-group">
        <label class="form-label">Beschreibung</label>
        <textarea class="form-textarea" id="wc-desc">{wc.get('embed_description', '')}</textarea>
      </div>
      <div class="form-group">
        <label class="form-label">Farbe</label>
        <div class="color-row">
          <div class="color-preview" id="wc-prev" style="background:{wc_col}" onclick="document.getElementById('wc-col').click()"></div>
          <input class="form-input" type="color" id="wc-col" value="{wc_col}" style="width:0;height:0;opacity:0;position:absolute" onchange="document.getElementById('wc-prev').style.background=this.value">
          <input class="form-input" id="wc-col-txt" value="{wc_col}" placeholder="#22c55e" style="flex:1">
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Bild-URL (optional)</label>
        <input class="form-input" id="wc-img" value="{wc.get('embed_image', '')}" placeholder="https://...">
      </div>
      <div class="settings-row" style="padding:8px 0">
        <div><div class="settings-row-label">User-Avatar als Thumbnail</div></div>
        <label class="toggle"><input type="checkbox" id="wc-thumb" {"checked" if wc.get('embed_thumbnail', True) else ""}><div class="toggle-track"></div><div class="toggle-thumb"></div></label>
      </div>
      <div style="border-top:1px solid var(--border);margin:12px 0;padding-top:12px">
        <div class="settings-row" style="padding:0;margin-bottom:10px">
          <div><div class="settings-row-label">DM-Nachricht senden</div></div>
          <label class="toggle"><input type="checkbox" id="wc-dm" {"checked" if wc.get('dm_enabled') else ""}><div class="toggle-track"></div><div class="toggle-thumb"></div></label>
        </div>
        <input class="form-input" id="wc-dm-msg" value="{wc.get('dm_description', '')}" placeholder="DM-Text wenn DM aktiviert…">
      </div>
      <button class="save-btn" id="save-welcome" onclick="saveWelcome()">Änderungen speichern</button>
    </div>
    <div>
      <div class="form-label" style="margin-bottom:8px">Live-Vorschau</div>
      <div class="discord-preview">
        <div class="discord-msg">
          <div class="discord-avatar">M</div>
          <div class="discord-content">
            <div class="discord-username">ModForge <span style="background:#5b6eff;color:#fff;font-size:.6rem;padding:1px 5px;border-radius:4px;font-weight:600">BOT</span></div>
            <div class="discord-embed" id="wc-embed-preview" style="border-left-color:{wc_col}">
              <div class="discord-embed-title" id="wc-p-title">{wc.get('embed_title', '👋 Willkommen!')}</div>
              <div class="discord-embed-desc" id="wc-p-desc">{wc.get('embed_description', 'Willkommen auf dem Server!')}</div>
              <div class="discord-embed-footer">{EMBED_FOOTER}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="settings-panel">
  <h3>👋 Leave-Nachricht</h3>
  <div class="settings-row">
    <div><div class="settings-row-label">Aktiviert</div></div>
    <label class="toggle"><input type="checkbox" id="lv-en" {"checked" if lc.get('enabled') else ""}><div class="toggle-track"></div><div class="toggle-thumb"></div></label>
  </div>
  <div class="embed-form" style="margin-top:14px">
    <div class="form-group">
      <label class="form-label">Titel</label>
      <input class="form-input" id="lv-title" value="{lc.get('embed_title', '👋 Auf Wiedersehen!')}">
    </div>
    <div class="form-group">
      <label class="form-label">Beschreibung</label>
      <textarea class="form-textarea" id="lv-desc">{lc.get('embed_description', '')}</textarea>
    </div>
    <div class="form-group">
      <label class="form-label">Farbe</label>
      <input class="form-input" id="lv-col" value="{lc_col}" placeholder="#ef4444">
    </div>
    <div class="form-group">
      <label class="form-label">Bild-URL (optional)</label>
      <input class="form-input" id="lv-img" value="{lc.get('embed_image', '')}" placeholder="https://...">
    </div>
    <button class="save-btn" id="save-leave" onclick="saveLeave()">Leave-Einstellungen speichern</button>
  </div>
</div>

<script>
// Live preview for welcome
function updatePreview(){{
  var t=document.getElementById('wc-title').value;
  var d=document.getElementById('wc-desc').value;
  var c=document.getElementById('wc-col-txt').value||document.getElementById('wc-col').value;
  document.getElementById('wc-p-title').textContent=t;
  document.getElementById('wc-p-desc').textContent=d;
  document.getElementById('wc-embed-preview').style.borderLeftColor=c;
  document.getElementById('wc-prev').style.background=c;
}}
['wc-title','wc-desc','wc-col-txt'].forEach(function(id){{
  var el=document.getElementById(id);
  if(el)el.addEventListener('input',updatePreview);
}});
document.getElementById('wc-col').addEventListener('input',function(){{
  document.getElementById('wc-col-txt').value=this.value;updatePreview();
}});
async function saveWelcome(){{
  await saveMod('welcome',{{
    enabled:getToggle('wc-en'),
    embed_title:getVal('wc-title'),
    embed_description:getVal('wc-desc'),
    embed_color:getVal('wc-col-txt')||getVal('wc-col'),
    embed_image:getVal('wc-img'),
    embed_thumbnail:getToggle('wc-thumb'),
    embed:true,
    dm_enabled:getToggle('wc-dm'),
    dm_description:getVal('wc-dm-msg')
  }});
}}
async function saveLeave(){{
  await saveMod('leave',{{
    enabled:getToggle('lv-en'),
    embed_title:getVal('lv-title'),
    embed_description:getVal('lv-desc'),
    embed_color:getVal('lv-col'),
    embed_image:getVal('lv-img'),
    embed:true
  }});
}}
</script>"""
