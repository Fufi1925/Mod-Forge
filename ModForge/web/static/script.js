// Scroll-Animationen
(function(){
  var io=new IntersectionObserver(function(es){
    es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('visible');}});
  },{threshold:.12});
  document.querySelectorAll('.reveal,.reveal-left,.reveal-right').forEach(function(el){io.observe(el);});
  var nums=document.querySelectorAll('[data-count]');
  var cio=new IntersectionObserver(function(es){
    es.forEach(function(e){
      if(e.isIntersecting){
        var el=e.target,target=parseInt(el.dataset.count),suffix=el.dataset.suffix||'',start=Date.now(),dur=1600;
        var frame=function(){
          var p=Math.min(1,(Date.now()-start)/dur),v=Math.round(p*target);
          el.textContent=v.toLocaleString('de-DE')+suffix;
          if(p<1)requestAnimationFrame(frame);
        };requestAnimationFrame(frame);cio.unobserve(el);
      }
    });
  },{threshold:.5});
  nums.forEach(function(el){cio.observe(el);});
})();

// Partikel
(function(){
  var c=document.getElementById('pts');if(!c)return;
  for(var i=0;i<18;i++){
    var p=document.createElement('div');p.className='particle';
    var s=Math.random()*8+4;
    p.style.cssText='width:'+s+'px;height:'+s+'px;left:'+Math.random()*100+'%;'
      +'animation-duration:'+(Math.random()*12+8)+'s;animation-delay:'+(-Math.random()*10)+'s;'
      +'opacity:'+(Math.random()*.2+.05);
    c.appendChild(p);}
})();

// Uptime
(function(){
  var el=document.getElementById('uptime-stat');if(!el)return;
  var s=parseInt('{{ up_s }}')||0;
  var d=Math.floor(s/86400);s%=86400;var h=Math.floor(s/3600);s%=3600;var m=Math.floor(s/60);
  el.textContent=(d?d+'d ':'')+(h?h+'h ':'')+m+'m';
})();

// Demo live update
(function(){
  var rows=[
    {tag:'BAN',tc:'rgba(239,68,68,.2)',fc:'#fca5a5',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'WARN',tc:'rgba(234,179,8,.2)',fc:'#fcd34d',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'MUTE',tc:'rgba(56,189,248,.2)',fc:'#7dd3fc',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'KICK',tc:'rgba(234,179,8,.2)',fc:'#fcd34d',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'SPAM',tc:'rgba(91,110,255,.2)',fc:'#a5b4fc',user:'User#'+Math.floor(Math.random()*9000+1000)},
  ];
  var li=0;
  setInterval(function(){
    var r=rows[li%rows.length];li++;
    var list=document.getElementById('d-list');if(!list)return;
    var newRow=document.createElement('div');newRow.className='demo-list-row';
    newRow.style.animation='fadeIn .4s ease';
    newRow.innerHTML='<span class="demo-tag" style="background:'+r.tc+';color:'+r.fc+'">'+r.tag+'</span>'
      +'<span>'+r.user+'</span><span style="margin-left:auto;opacity:.5">jetzt</span>';
    list.insertBefore(newRow,list.firstChild);
    if(list.children.length>3)list.removeChild(list.lastChild);
    var dc=document.getElementById('d-c');
    if(dc)dc.textContent=parseInt(dc.textContent||0)+1;
  },3200);
})();
