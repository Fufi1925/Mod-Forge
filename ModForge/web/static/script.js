// === 2059 3D HOLOGRAM CUBE + FUTURISTIC CURSOR + SCROLL ANIMATIONS ===

// ----- 3D Würfel im Hero -----
(function() {
  const hero = document.querySelector('.hero');
  if (!hero) return;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, hero.clientWidth / hero.clientHeight, 0.1, 1000);
  camera.position.z = 5;

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(hero.clientWidth, hero.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.domElement.style.position = 'absolute';
  renderer.domElement.style.top = '0';
  renderer.domElement.style.left = '0';
  renderer.domElement.style.pointerEvents = 'none';
  hero.insertBefore(renderer.domElement, hero.firstChild);

  // Holografischer Würfel
  const geometry = new THREE.BoxGeometry(1.5, 1.5, 1.5);
  const edges = new THREE.EdgesGeometry(geometry);
  const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x00ffff, linewidth: 1 }));
  scene.add(line);

  // Zusätzlicher innerer Würfel (cyan)
  const innerGeo = new THREE.BoxGeometry(1.2, 1.2, 1.2);
  const innerEdges = new THREE.EdgesGeometry(innerGeo);
  const innerLine = new THREE.LineSegments(innerEdges, new THREE.LineBasicMaterial({ color: 0xff00ff }));
  scene.add(innerLine);

  // Partikel um den Würfel
  const particlesGeo = new THREE.BufferGeometry();
  const particlesCount = 200;
  const posArray = new Float32Array(particlesCount * 3);
  for (let i = 0; i < particlesCount * 3; i += 3) {
    posArray[i] = (Math.random() - 0.5) * 4;
    posArray[i+1] = (Math.random() - 0.5) * 4;
    posArray[i+2] = (Math.random() - 0.5) * 4;
  }
  particlesGeo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
  const particlesMat = new THREE.PointsMaterial({size: 0.02, color: 0x00ffff, blending: THREE.AdditiveBlending});
  const particles = new THREE.Points(particlesGeo, particlesMat);
  scene.add(particles);

  // Animation
  function animate() {
    requestAnimationFrame(animate);
    line.rotation.x += 0.005;
    line.rotation.y += 0.01;
    innerLine.rotation.x -= 0.003;
    innerLine.rotation.y -= 0.008;
    particles.rotation.y += 0.002;
    renderer.render(scene, camera);
  }
  animate();

  // Responsive
  window.addEventListener('resize', () => {
    camera.aspect = hero.clientWidth / hero.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(hero.clientWidth, hero.clientHeight);
  });
})();

// ----- Custom Cursor (Laserpunkt) -----
(function() {
  const cursor = document.createElement('div');
  cursor.classList.add('custom-cursor');
  document.body.appendChild(cursor);
  const dot = document.createElement('div');
  dot.classList.add('custom-cursor-dot');
  document.body.appendChild(dot);

  document.addEventListener('mousemove', (e) => {
    cursor.style.transform = `translate(${e.clientX - 10}px, ${e.clientY - 10}px)`;
    dot.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 3}px)`;
  });
})();

// ----- Scroll Reveal (3D) -----
(function() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) entry.target.classList.add('visible');
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.reveal, .reveal-left, .reveal-right').forEach(el => observer.observe(el));
})();

// ----- Count-up Animation -----
(function() {
  const nums = document.querySelectorAll('[data-count]');
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el = entry.target,
              target = parseInt(el.dataset.count),
              suffix = el.dataset.suffix || '',
              start = Date.now(),
              dur = 2000;
        const frame = () => {
          const p = Math.min(1, (Date.now() - start) / dur),
                v = Math.round(p * target);
          el.textContent = v.toLocaleString('de-DE') + suffix;
          if (p < 1) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
        counterObserver.unobserve(el);
      }
    });
  }, { threshold: 0.5 });
  nums.forEach(el => counterObserver.observe(el));
})();

// ----- Demo Live Update (unverändert) -----
(function(){
  var rows=[
    {tag:'BAN',tc:'rgba(255,51,102,.3)',fc:'#ff3366',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'WARN',tc:'rgba(255,204,0,.3)',fc:'#ffcc00',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'MUTE',tc:'rgba(0,191,255,.3)',fc:'#00bfff',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'KICK',tc:'rgba(255,204,0,.3)',fc:'#ffcc00',user:'User#'+Math.floor(Math.random()*9000+1000)},
    {tag:'SPAM',tc:'rgba(0,255,255,.3)',fc:'#00ffff',user:'User#'+Math.floor(Math.random()*9000+1000)},
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
