// ── Mouse Tracker ──
(function() {
  const circle = document.getElementById('mouse-circle');
  const dot = document.getElementById('mouse-dot');
  if (!circle || !dot) return;
  let mouseX = 0, mouseY = 0;
  let circleX = 0, circleY = 0;
  let dotX = 0, dotY = 0;
  const speed = 0.1;

  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  function animate() {
    circleX += (mouseX - circleX) * speed;
    circleY += (mouseY - circleY) * speed;
    circle.style.transform = `translate(${circleX}px, ${circleY}px) translate(-50%, -50%)`;
    dotX += (mouseX - dotX) * speed * 2;
    dotY += (mouseY - dotY) * speed * 2;
    dot.style.transform = `translate(${dotX}px, ${dotY}px) translate(-50%, -50%)`;
    requestAnimationFrame(animate);
  }
  animate();
})();

// ── Scroll Reveal ──
(function() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  }, { threshold: 0.15 });

  document.querySelectorAll('.reveal, .reveal-left, .reveal-right').forEach(el => observer.observe(el));
})();

// ── Count-up Animation ──
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

// ── Demo Live Update ──
(function() {
  const rows = [
    { tag: 'BAN', tc: 'rgba(248,113,113,.2)', fc: '#f87171', user: 'User#' + Math.floor(Math.random()*9000+1000) },
    { tag: 'WARN', tc: 'rgba(251,191,36,.2)', fc: '#fbbf24', user: 'User#' + Math.floor(Math.random()*9000+1000) },
    { tag: 'MUTE', tc: 'rgba(56,189,248,.2)', fc: '#38bdf8', user: 'User#' + Math.floor(Math.random()*9000+1000) },
    { tag: 'KICK', tc: 'rgba(251,191,36,.2)', fc: '#fbbf24', user: 'User#' + Math.floor(Math.random()*9000+1000) },
    { tag: 'SPAM', tc: 'rgba(91,127,255,.2)', fc: '#5b7fff', user: 'User#' + Math.floor(Math.random()*9000+1000) }
  ];
  let li = 0;
  setInterval(() => {
    const r = rows[li % rows.length]; li++;
    const list = document.getElementById('d-list'); if (!list) return;
    const newRow = document.createElement('div'); newRow.className = 'demo-list-row';
    newRow.style.animation = 'fadeIn .4s ease';
    newRow.innerHTML = '<span class="demo-tag" style="background:'+r.tc+';color:'+r.fc+'">'+r.tag+'</span>'
      + '<span>'+r.user+'</span><span style="margin-left:auto;opacity:.5">jetzt</span>';
    list.insertBefore(newRow, list.firstChild);
    if (list.children.length > 3) list.removeChild(list.lastChild);
    const dc = document.getElementById('d-c');
    if (dc) dc.textContent = parseInt(dc.textContent || 0) + 1;
  }, 3200);
})();

// ── 3D Background (Three.js) ──
(function() {
  const container = document.getElementById('hero-canvas');
  if (!container || !window.THREE) return;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 7;

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  container.appendChild(renderer.domElement);

  // Soft geometric shape
  const geometry = new THREE.IcosahedronGeometry(1.6, 0);
  const material = new THREE.MeshStandardMaterial({
    color: 0x5b7fff,
    roughness: 0.3,
    metalness: 0.1,
    transparent: true,
    opacity: 0.15,
  });
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  const wireframe = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry),
    new THREE.LineBasicMaterial({ color: 0x9275ff, transparent: true, opacity: 0.3 })
  );
  scene.add(wireframe);

  // Lights
  const ambientLight = new THREE.AmbientLight(0x404080);
  scene.add(ambientLight);
  const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6);
  directionalLight.position.set(5, 5, 5);
  scene.add(directionalLight);

  // Animation
  function animate() {
    requestAnimationFrame(animate);
    mesh.rotation.x += 0.001;
    mesh.rotation.y += 0.003;
    wireframe.rotation.x = mesh.rotation.x;
    wireframe.rotation.y = mesh.rotation.y;
    renderer.render(scene, camera);
  }
  animate();

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });
})();
