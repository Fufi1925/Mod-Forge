// Scroll reveal
(function(){
  var io = new IntersectionObserver(function(es){
    es.forEach(function(e){
      if(e.isIntersecting) e.target.classList.add('visible');
    });
  }, {threshold: .12});
  document.querySelectorAll('.reveal,.reveal-left,.reveal-right').forEach(function(el){
    io.observe(el);
  });

  // Count-up animation
  var nums = document.querySelectorAll('[data-count]');
  var cio = new IntersectionObserver(function(es){
    es.forEach(function(e){
      if(e.isIntersecting){
        var el = e.target,
            target = parseInt(el.dataset.count),
            suffix = el.dataset.suffix || '',
            start = Date.now(),
            dur = 1600;
        var frame = function(){
          var p = Math.min(1, (Date.now() - start) / dur),
              v = Math.round(p * target);
          el.textContent = v.toLocaleString('de-DE') + suffix;
          if(p < 1) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
        cio.unobserve(el);
      }
    });
  }, {threshold: .5});
  nums.forEach(function(el){ cio.observe(el); });
})();

// Particles (Hero)
(function(){
  var c = document.getElementById('pts');
  if(!c) return;
  for(var i = 0; i < 18; i++){
    var p = document.createElement('div');
    p.className = 'particle';
    var s = Math.random() * 8 + 4;
    p.style.cssText = 'width:' + s + 'px;height:' + s + 'px;left:' + Math.random()*100 + '%;'
      + 'animation-duration:' + (Math.random()*12+8) + 's;animation-delay:' + (-Math.random()*10) + 's;'
      + 'opacity:' + (Math.random()*.2+.05);
    c.appendChild(p);
  }
})();

// Demo live update (for landing page)
(function(){
  var rows = [
    {tag:'BAN',tc:'rgba(239,68,68,.2)',fc:'#fca5a5',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'WARN',tc:'rgba(234,179,8,.2)',fc:'#fcd34d',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'MUTE',tc:'rgba(56,189,248,.2)',fc:'#7dd3fc',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'KICK',tc:'rgba(234,179,8,.2)',fc:'#fcd34d',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'SPAM',tc:'rgba(91,110,255,.2)',fc:'#a5b4fc',user:'User#'+Math.floor(Math.random()*9000+1000)}
  ];
  var li = 0;
  setInterval(function(){
    var r = rows[li % rows.length]; li++;
    var list = document.getElementById('d-list');
    if(!list) return;
    var newRow = document.createElement('div');
    newRow.className = 'demo-list-row';
    newRow.style.animation = 'fadeIn .4s ease';
    newRow.innerHTML = '<span class="demo-tag" style="background:'+r.tc+';color:'+r.fc+'">'+r.tag+'</span>'
      +'<span>'+r.user+'</span><span style="margin-left:auto;opacity:.5">jetzt</span>';
    list.insertBefore(newRow, list.firstChild);
    if(list.children.length > 3) list.removeChild(list.lastChild);
    var dc = document.getElementById('d-c');
    if(dc) dc.textContent = parseInt(dc.textContent||0) + 1;
  }, 3200);
})();

// Admin dashboard periodic update
async function tick(){
  try{
    var r = await fetch('/admin/api/state');
    if(!r.ok) return;
    var d = await r.json();
    var st = d.stats;
    document.getElementById('k-g').textContent = st.guild_count||0;
    document.getElementById('k-m').textContent = (st.member_total||0).toLocaleString('de-DE') + ' Members';
    document.getElementById('k-u').textContent = fmtUp(st.uptime_s||0);
    document.getElementById('k-l').textContent = Math.round(st.latency_ms||0);
    document.getElementById('k-c').textContent = st.cases_total||0;
    document.getElementById('k-a').textContent = (st.archive_total||0) + ' im Archiv';
    document.getElementById('topbar-sub').textContent = st.guild_count + ' Server · ' + Math.round(st.latency_ms) + 'ms';
    document.getElementById('last-refresh').textContent = new Date().toLocaleTimeString('de-DE');
    document.getElementById('g-cnt').textContent = '(' + st.guild_count + ')';
    var gt = document.querySelector('#t-guilds tbody');
    gt.innerHTML = (d.guilds||[]).slice(0,50).map(function(g){
      return '<tr><td><b>'+esc(g.name)+'</b></td><td><span class="tag tag-def">'+g.id+'</span></td><td>'+(g.member_count||0).toLocaleString('de-DE')+'</td><td>'+esc(g.owner||'?')+'</td><td style="color:var(--muted)">'+esc(g.created||'')+'</td></tr>';
    }).join('') || '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:20px">Keine Server</td></tr>';
    document.getElementById('ev-act').innerHTML = (d.activity||[]).slice(0,40).map(function(a){
      return '<div class="ev-row"><span class="ev-kind">'+esc(a.kind)+'</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(a.text)+'</span><span class="ev-ts">'+esc(a.ts)+'</span></div>';
    }).join('') || '<div class="ev-row" style="color:var(--muted)">Leer</div>';
    document.getElementById('ev-guild').innerHTML = (d.guild_events||[]).slice(0,30).map(function(e){
      return '<div class="ev-row"><span class="ev-kind">'+(e.event==='join'?'✅ join':'❌ leave')+'</span><span>'+esc(e.guild_name)+'</span><span class="ev-ts">'+esc(e.timestamp)+'</span></div>';
    }).join('') || '<div class="ev-row" style="color:var(--muted)">Leer</div>';
    var ct = document.querySelector('#t-cases tbody');
    ct.innerHTML = (d.recent_cases||[]).map(function(c){
      return '<tr><td><b>#'+esc(c.case_id)+'</b></td><td><span class="tag tag-def">'+esc(c.guild_id)+'</span></td><td><span class="tag tag-def">'+esc(c.user_id)+'</span></td><td>'+atag(c.action)+'</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc((c.reason||'').slice(0,120))+'</td><td style="color:var(--muted)">'+esc(c.created_at)+'</td></tr>';
    }).join('') || '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:20px">Keine Cases</td></tr>';
    var mt = document.querySelector('#t-msgs tbody');
    mt.innerHTML = (d.recent_messages||[]).map(function(m){
      return '<tr><td style="color:var(--muted)">'+esc(m.timestamp)+'</td><td><span class="tag tag-def">'+esc(m.guild_id)+'</span></td><td><span class="tag tag-def">'+esc(m.user_id)+'</span></td><td><span class="tag tag-def">'+esc(m.channel_id)+'</span></td><td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc((m.content||'').slice(0,200))+'</td><td>'+(m.deleted?'<span class="tag tag-err">del</span>':'<span class="tag tag-ok">ok</span>')+'</td></tr>';
    }).join('') || '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:20px">Leer</td></tr>';
  }catch(ex){console.error(ex);}
}

function esc(s){return (s||'').toString().replace(/[&<>\"']/g, function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;','\'':'&#39;'}[c];})}
function fmtUp(s){s=Math.floor(s);var d=Math.floor(s/86400);s%=86400;var h=Math.floor(s/3600);s%=3600;var m=Math.floor(s/60);return (d?d+'d ':'')+(h?h+'h ':'')+m+'m'}
function atag(a){var m={ban:'tag-err',tempban:'tag-err',kick:'tag-warn',tempkick:'tag-warn',warn:'tag-warn',mute:'tag-info',tempmute:'tag-info',unmute:'tag-ok'};return '<span class="tag '+(m[a]||'tag-def')+'">'+esc(a)+'</span>'}
function showSec(id){['guilds','activity','cases','msgs'].forEach(function(s){var el=document.getElementById('v-'+s);if(el)el.style.display=s===id||id==='all'?'':'none';})}

// Call tick on admin dashboard if present
if(document.getElementById('k-g')) {
  tick();
  setInterval(tick, 5000);
  }
