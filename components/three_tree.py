"""
components/three_tree.py

Python wrapper that returns the HTML/JS payload for the hyper-realistic
3D tree, rendered inside Streamlit via `streamlit.components.v1.html`.

Responsibilities:
    - 360-degree OrbitControls camera (touch + mouse).
    - Procedural tree mesh whose look changes with `stage` (see database.stage_for_level).
    - Interactive pest ("bug") spawner + raycaster click/tap handler for the
      Tozalovchi (Cleaner) role; posts a message back to Streamlit when cleared.
    - Golden "Magical Shield" force-field sphere when `shield_active=True`.
    - Fully responsive canvas, auto-resizes to the device/container width.
"""

from __future__ import annotations

import json

import streamlit.components.v1 as components

THREE_JS_CDN = "https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"
ORBIT_CONTROLS_CDN = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"


def render_tree(
    level: int,
    stage: str,
    shield_active: bool = False,
    pest_mode: bool = False,
    pest_count: int = 6,
    height: int = 480,
    key: str = "three_tree",
) -> None:
    """
    Render the 3D tree canvas.

    Args:
        level: current tree level (drives minor scale/detail tweaks).
        stage: one of 'seed' | 'sprout' | 'golden_pink' | 'ecosystem' | 'fairytale'
               (see database.stage_for_level).
        shield_active: draw the translucent golden force-field sphere.
        pest_mode: if True, spawn clickable pests on the trunk/branches for the
                   Tozalovchi role; posts {type:'pests_cleared'} to the parent
                   window (Streamlit) once all pests are removed.
        pest_count: number of pests to spawn when pest_mode is True.
        height: canvas height in px.
        key: unique Streamlit component key.
    """
    html = _build_html(
        level=level,
        stage=stage,
        shield_active=shield_active,
        pest_mode=pest_mode,
        pest_count=pest_count,
        key=key,
    )
    components.html(html, height=height, scrolling=False)


def _build_html(
    level: int, stage: str, shield_active: bool, pest_mode: bool, pest_count: int, key: str
) -> str:
    config = {
        "level": level,
        "stage": stage,
        "shieldActive": shield_active,
        "pestMode": pest_mode,
        "pestCount": pest_count,
    }
    config_json = json.dumps(config)

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<style>
  html, body {{ margin:0; padding:0; overflow:hidden; background:transparent; }}
  #tree-canvas-wrap {{ width:100%; height:100vh; position:relative; }}
  #tree-canvas-wrap canvas {{ display:block; width:100% !important; height:100% !important; touch-action:none; }}
  #hud {{
    position:absolute; top:8px; left:8px; color:#eafff0; font-family:'Segoe UI',sans-serif;
    font-size:12px; background:rgba(10,30,15,0.45); padding:6px 10px; border-radius:8px;
    pointer-events:none; letter-spacing:.3px;
  }}
  #pest-counter {{
    position:absolute; top:8px; right:8px; color:#fff; font-family:'Segoe UI',sans-serif;
    font-size:13px; background:rgba(120,20,20,0.55); padding:6px 12px; border-radius:8px;
    display:none;
  }}
</style>
</head>
<body>
<div id="tree-canvas-wrap">
  <div id="hud">🌳 Level {level} — {stage.replace('_',' ').title()}</div>
  <div id="pest-counter">🐛 Pests left: <span id="pest-left">{pest_count}</span></div>
</div>

<script src="{THREE_JS_CDN}"></script>
<script src="{ORBIT_CONTROLS_CDN}"></script>
<script>
const CONFIG = {config_json};

// --------------------------------------------------------------------- //
// Scene / Camera / Renderer
// --------------------------------------------------------------------- //
const wrap = document.getElementById('tree-canvas-wrap');
const scene = new THREE.Scene();

function stageBackground(stage) {{
  switch(stage) {{
    case 'seed': return 0x0a0f0a;
    case 'sprout': return 0x9fd8c0;
    case 'golden_pink': return 0xffd9ec;
    case 'ecosystem': return 0xbfe8ff;
    case 'fairytale': return 0xffe9c7;
    default: return 0x87ceeb;
  }}
}}
scene.background = new THREE.Color(stageBackground(CONFIG.stage));
scene.fog = new THREE.FogExp2(scene.background.getHex(), 0.012);

const camera = new THREE.PerspectiveCamera(50, wrap.clientWidth / wrap.clientHeight, 0.1, 1000);
camera.position.set(0, 6, 16);

const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(wrap.clientWidth, wrap.clientHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
wrap.appendChild(renderer.domElement);

const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 6;
controls.maxDistance = 34;
controls.maxPolarAngle = Math.PI * 0.49;
controls.target.set(0, 3, 0);

// --------------------------------------------------------------------- //
// Lighting
// --------------------------------------------------------------------- //
const hemi = new THREE.HemisphereLight(0xffffff, 0x224422, 0.9);
scene.add(hemi);

const sun = new THREE.DirectionalLight(0xfff2d0, 1.15);
sun.position.set(12, 20, 8);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
sun.shadow.camera.left = -20; sun.shadow.camera.right = 20;
sun.shadow.camera.top = 20; sun.shadow.camera.bottom = -20;
scene.add(sun);

// --------------------------------------------------------------------- //
// Ground
// --------------------------------------------------------------------- //
function groundColor(stage) {{
  if (stage === 'seed') return 0x1c1a12;
  if (stage === 'sprout') return 0x3f7a3a;
  return 0x4caf50;
}}
const groundGeo = new THREE.CircleGeometry(30, 64);
const groundMat = new THREE.MeshStandardMaterial({{ color: groundColor(CONFIG.stage), roughness: 1 }});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// --------------------------------------------------------------------- //
// Procedural Tree (trunk + branches + canopy), styled by stage
// --------------------------------------------------------------------- //
const treeGroup = new THREE.Group();
scene.add(treeGroup);

function barkTexture(stage) {{
  const c = document.createElement('canvas');
  c.width = 128; c.height = 256;
  const ctx = c.getContext('2d');
  const base = (stage === 'golden_pink' || stage === 'ecosystem' || stage === 'fairytale') ? '#b8862b' : '#5b3a22';
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, 128, 256);
  ctx.strokeStyle = 'rgba(0,0,0,0.25)';
  for (let i = 0; i < 40; i++) {{
    ctx.beginPath();
    const x = Math.random() * 128;
    ctx.moveTo(x, 0);
    ctx.lineTo(x + (Math.random() * 10 - 5), 256);
    ctx.stroke();
  }}
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(2, 4);
  return tex;
}}

function leafColor(stage) {{
  switch (stage) {{
    case 'seed': return 0x2e5c2e;
    case 'sprout': return 0x5bbf5b;
    case 'golden_pink': return 0xff9ecb;
    case 'ecosystem': return 0xff8fc6;
    case 'fairytale': return 0xffb3da;
    default: return 0x3fae3f;
  }}
}}

function buildTree(stage, level) {{
  const scale = stage === 'seed' ? 0.15 : Math.min(1.6, 0.6 + level * 0.03);
  const barkMat = new THREE.MeshStandardMaterial({{
    map: barkTexture(stage), roughness: 0.9, metalness: stage === 'golden_pink' || stage === 'ecosystem' || stage === 'fairytale' ? 0.35 : 0.05,
  }});

  const trunkHeight = 6 * scale;
  const trunkGeo = new THREE.CylinderGeometry(0.35 * scale, 0.55 * scale, trunkHeight, 12);
  const trunk = new THREE.Mesh(trunkGeo, barkMat);
  trunk.position.y = trunkHeight / 2;
  trunk.castShadow = true;
  treeGroup.add(trunk);

  // Branches
  const branchCount = stage === 'seed' ? 0 : 5;
  for (let i = 0; i < branchCount; i++) {{
    const bh = trunkHeight * (0.5 + Math.random() * 0.3);
    const bGeo = new THREE.CylinderGeometry(0.08 * scale, 0.16 * scale, 2.2 * scale, 8);
    const branch = new THREE.Mesh(bGeo, barkMat);
    const angle = (i / branchCount) * Math.PI * 2;
    branch.position.set(Math.cos(angle) * 0.4 * scale, bh, Math.sin(angle) * 0.4 * scale);
    branch.rotation.z = Math.PI / 3 * (Math.random() > 0.5 ? 1 : -1);
    branch.rotation.y = angle;
    branch.castShadow = true;
    treeGroup.add(branch);
  }}

  // Canopy (icosahedron clusters for a stylized foliage look)
  if (stage !== 'seed') {{
    const leafMat = new THREE.MeshStandardMaterial({{ color: leafColor(stage), roughness: 0.7 }});
    const clusters = 9;
    for (let i = 0; i < clusters; i++) {{
      const r = (0.9 + Math.random() * 0.6) * scale;
      const geo = new THREE.IcosahedronGeometry(r, 1);
      const mesh = new THREE.Mesh(geo, leafMat);
      const angle = Math.random() * Math.PI * 2;
      const radius = Math.random() * 1.8 * scale;
      mesh.position.set(
        Math.cos(angle) * radius,
        trunkHeight + Math.random() * 1.5 * scale,
        Math.sin(angle) * radius
      );
      mesh.castShadow = true;
      treeGroup.add(mesh);
    }}
  }}

  return {{ trunk, trunkHeight, scale }};
}}

const treeInfo = buildTree(CONFIG.stage, CONFIG.level);

// Gentle wind sway (shader-free, cheap vertex-group animation)
let t = 0;

// --------------------------------------------------------------------- //
// Stage extras: grass patches, wildlife, cottage (levels 16+/31+)
// --------------------------------------------------------------------- //
if (['golden_pink','ecosystem','fairytale'].includes(CONFIG.stage)) {{
  const grassMat = new THREE.MeshStandardMaterial({{ color: 0x7fd858, roughness: 1 }});
  for (let i = 0; i < 40; i++) {{
    const blade = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.5, 4), grassMat);
    const a = Math.random() * Math.PI * 2, r = 2 + Math.random() * 8;
    blade.position.set(Math.cos(a) * r, 0.25, Math.sin(a) * r);
    blade.rotation.y = Math.random() * Math.PI;
    scene.add(blade);
  }}
}}

if (['ecosystem','fairytale'].includes(CONFIG.stage)) {{
  const critterMat = new THREE.MeshStandardMaterial({{ color: 0xffffff, roughness: 0.8 }});
  for (let i = 0; i < 3; i++) {{
    const sheep = new THREE.Mesh(new THREE.SphereGeometry(0.5, 10, 10), critterMat);
    const a = Math.random() * Math.PI * 2, r = 4 + Math.random() * 5;
    sheep.position.set(Math.cos(a) * r, 0.5, Math.sin(a) * r);
    sheep.userData.orbit = {{ a, r, speed: 0.05 + Math.random() * 0.05 }};
    scene.add(sheep);
    sheep.userData.isCritter = true;
  }}
}}

if (CONFIG.stage === 'fairytale') {{
  const cottageGroup = new THREE.Group();
  const wallMat = new THREE.MeshStandardMaterial({{ color: 0xe8c79b }});
  const roofMat = new THREE.MeshStandardMaterial({{ color: 0xaa3b3b }});
  const base = new THREE.Mesh(new THREE.BoxGeometry(2.4, 1.6, 2.4), wallMat);
  base.position.set(6, 0.8, -2);
  const roof = new THREE.Mesh(new THREE.ConeGeometry(1.9, 1.3, 4), roofMat);
  roof.position.set(6, 2.25, -2);
  roof.rotation.y = Math.PI / 4;
  cottageGroup.add(base, roof);
  cottageGroup.traverse(o => o.castShadow = true);
  scene.add(cottageGroup);
}}

// --------------------------------------------------------------------- //
// Magical Shield force-field
// --------------------------------------------------------------------- //
let shieldMesh = null;
if (CONFIG.shieldActive) {{
  const shieldGeo = new THREE.SphereGeometry(treeInfo.trunkHeight * 1.15, 32, 32);
  const shieldMat = new THREE.MeshPhysicalMaterial({{
    color: 0xffd966, transparent: true, opacity: 0.22, roughness: 0.1,
    metalness: 0.1, emissive: 0xffcf40, emissiveIntensity: 0.35,
  }});
  shieldMesh = new THREE.Mesh(shieldGeo, shieldMat);
  shieldMesh.position.y = treeInfo.trunkHeight * 0.6;
  scene.add(shieldMesh);
}}

// --------------------------------------------------------------------- //
// Particles: falling leaves / glowing spores
// --------------------------------------------------------------------- //
const particleCount = 60;
const particleGeo = new THREE.BufferGeometry();
const positions = new Float32Array(particleCount * 3);
for (let i = 0; i < particleCount; i++) {{
  positions[i*3] = (Math.random() - 0.5) * 20;
  positions[i*3+1] = Math.random() * 12;
  positions[i*3+2] = (Math.random() - 0.5) * 20;
}}
particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
const particleMat = new THREE.PointsMaterial({{
  color: CONFIG.stage === 'golden_pink' || CONFIG.stage === 'ecosystem' || CONFIG.stage === 'fairytale' ? 0xffc4e6 : 0xbfffcf,
  size: 0.12, transparent: true, opacity: 0.8,
}});
const particles = new THREE.Points(particleGeo, particleMat);
scene.add(particles);

// --------------------------------------------------------------------- //
// Pest spawner + raycaster (Tozalovchi role)
// --------------------------------------------------------------------- //
const pests = [];
let pestsRemaining = 0;

if (CONFIG.pestMode) {{
  pestsRemaining = CONFIG.pestCount;
  document.getElementById('pest-counter').style.display = 'block';
  const pestMat = new THREE.MeshStandardMaterial({{ color: 0x3a2a1a, roughness: 0.6 }});
  for (let i = 0; i < CONFIG.pestCount; i++) {{
    const bug = new THREE.Group();
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.18, 8, 8), pestMat);
    bug.add(body);
    for (let l = 0; l < 6; l++) {{
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.25, 4), pestMat);
      const ang = (l / 6) * Math.PI * 2;
      leg.position.set(Math.cos(ang) * 0.18, -0.1, Math.sin(ang) * 0.18);
      leg.rotation.z = Math.PI / 2.2;
      bug.add(leg);
    }}
    const h = Math.random() * treeInfo.trunkHeight;
    const ang = Math.random() * Math.PI * 2;
    const rad = 0.4 * treeInfo.scale + Math.random() * 0.3;
    bug.position.set(Math.cos(ang) * rad, h, Math.sin(ang) * rad);
    bug.userData.isPest = true;
    treeGroup.add(bug);
    pests.push(bug);
  }}

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function handlePointer(clientX, clientY) {{
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const targets = pests.flatMap(p => p.children);
    const hits = raycaster.intersectObjects(targets, false);
    if (hits.length > 0) {{
      let hitObj = hits[0].object;
      const bug = pests.find(p => p.children.includes(hitObj));
      if (bug) {{
        treeGroup.remove(bug);
        const idx = pests.indexOf(bug);
        if (idx > -1) pests.splice(idx, 1);
        pestsRemaining -= 1;
        document.getElementById('pest-left').innerText = pestsRemaining;
        if (pestsRemaining <= 0) {{
          document.getElementById('pest-counter').innerText = '✅ All pests cleared!';
          try {{
            window.parent.postMessage({{ type: 'pests_cleared', key: '{key}' }}, '*');
          }} catch (e) {{}}
        }}
      }}
    }}
  }}

  renderer.domElement.addEventListener('click', (e) => handlePointer(e.clientX, e.clientY));
  renderer.domElement.addEventListener('touchstart', (e) => {{
    if (e.touches.length > 0) {{
      handlePointer(e.touches[0].clientX, e.touches[0].clientY);
    }}
  }}, {{ passive: true }});
}}

// --------------------------------------------------------------------- //
// Resize handling
// --------------------------------------------------------------------- //
function onResize() {{
  const w = wrap.clientWidth, h = wrap.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}}
window.addEventListener('resize', onResize);

// --------------------------------------------------------------------- //
// Animation loop
// --------------------------------------------------------------------- //
function animate() {{
  requestAnimationFrame(animate);
  t += 0.01;

  treeGroup.rotation.y += 0.0006;          // slow idle spin
  treeGroup.children.forEach((child, i) => {{
    if (child.geometry && child.geometry.type === 'IcosahedronGeometry') {{
      child.position.x += Math.sin(t + i) * 0.0008;   // wind motion on leaf clusters
    }}
  }});

  if (shieldMesh) {{
    shieldMesh.rotation.y += 0.003;
    shieldMesh.material.opacity = 0.18 + Math.sin(t * 2) * 0.06;
  }}

  const posAttr = particleGeo.attributes.position;
  for (let i = 0; i < particleCount; i++) {{
    posAttr.array[i*3+1] -= 0.01;
    if (posAttr.array[i*3+1] < 0) posAttr.array[i*3+1] = 12;
  }}
  posAttr.needsUpdate = true;

  scene.children.forEach(obj => {{
    if (obj.userData && obj.userData.isCritter) {{
      obj.userData.orbit.a += obj.userData.orbit.speed * 0.01;
      obj.position.x = Math.cos(obj.userData.orbit.a) * obj.userData.orbit.r;
      obj.position.z = Math.sin(obj.userData.orbit.a) * obj.userData.orbit.r;
    }}
  }});

  controls.update();
  renderer.render(scene, camera);
}}
animate();
</script>
</body>
</html>
"""
