import { useRef, useState, useEffect, useCallback } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import SpriteText from 'three-spritetext';
import {
  NODES, LINKS,
  CATEGORY_COLORS, CATEGORY_LABELS,
  METHOD_RING, METHOD_LABELS,
  type EcoNode, type NodeCategory, type NodeMethod,
} from './ecosystem';

const AUTO_ROTATE_SPEED = 0.35;
const AUTO_ROTATE_RESUME_MS = 5000;

// ─── helpers ────────────────────────────────────────────────────────────────

function nodeRadius(val: number) { return val * 0.85 + 4; }

function hex2rgb(hex: string, alpha = 1) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// Build initial positions so categories start in rough sectors
const SECTOR: Record<string, [number, number, number]> = {
  source:   [-280,  120,   80],
  core:     [   0,    0,    0],
  pipeline: [-140,  -60, -120],
  ml:       [-200, -160,   60],
  storage:  [ 120,  -80, -100],
  pegasus:  [ 220,   80,   40],
  sync:     [  60,  140, -160],
  output:   [ 260,  -20,  160],
};

const graphData = {
  nodes: NODES.map(n => {
    const [sx, sy, sz] = SECTOR[n.category] ?? [0, 0, 0];
    return {
      ...n,
      x: sx + (Math.random() - 0.5) * 100,
      y: sy + (Math.random() - 0.5) * 100,
      z: sz + (Math.random() - 0.5) * 100,
    };
  }),
  links: LINKS,
};

// ─── component ──────────────────────────────────────────────────────────────

export default function App() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const [selected, setSelected] = useState<EcoNode | null>(null);
  const interactTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasInitialFit = useRef(false);
  const [dims, setDims] = useState({ w: window.innerWidth, h: window.innerHeight });
  const [hiddenCats, setHiddenCats] = useState<Set<NodeCategory>>(new Set());
  const [showLegend, setShowLegend] = useState(true);

  // Window resize
  useEffect(() => {
    const onResize = () => setDims({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Starfield + nebula cloud — added once after mount
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!fgRef.current) return;
      const scene: THREE.Scene = fgRef.current.scene();

      // Dense star field
      const starCount = 1800;
      const positions = new Float32Array(starCount * 3);
      const sizes = new Float32Array(starCount);
      for (let i = 0; i < starCount; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = 600 + Math.random() * 900;
        positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i * 3 + 2] = r * Math.cos(phi);
        sizes[i] = Math.random() < 0.04 ? 3.5 : Math.random() * 1.2 + 0.3;
      }
      const starGeo = new THREE.BufferGeometry();
      starGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      starGeo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));
      const starMat = new THREE.PointsMaterial({
        color: '#c8d8ff',
        size: 1.0,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.75,
      });
      scene.add(new THREE.Points(starGeo, starMat));

      // A few large "beacon" stars
      const beaconGeo = new THREE.BufferGeometry();
      const bPos = new Float32Array(40 * 3);
      for (let i = 0; i < 40; i++) {
        const t = Math.random() * Math.PI * 2;
        const p = Math.acos(2 * Math.random() - 1);
        const r = 700 + Math.random() * 600;
        bPos[i * 3]     = r * Math.sin(p) * Math.cos(t);
        bPos[i * 3 + 1] = r * Math.sin(p) * Math.sin(t);
        bPos[i * 3 + 2] = r * Math.cos(p);
      }
      beaconGeo.setAttribute('position', new THREE.BufferAttribute(bPos, 3));
      const beaconMat = new THREE.PointsMaterial({ color: '#ffffff', size: 2.8, transparent: true, opacity: 0.9 });
      scene.add(new THREE.Points(beaconGeo, beaconMat));

      // Ambient nebula glow (large translucent sphere)
      const nebulaMat = new THREE.MeshBasicMaterial({
        color: '#1a2a5e',
        transparent: true,
        opacity: 0.12,
        side: THREE.BackSide,
      });
      scene.add(new THREE.Mesh(new THREE.SphereGeometry(700, 32, 32), nebulaMat));
    }, 500);
    return () => clearTimeout(timer);
  }, []);

  // Apply d3 forces + enable autoRotate after engine init
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!fgRef.current) return;
      const charge = fgRef.current.d3Force('charge');
      if (charge) charge.strength(-180);
      const link = fgRef.current.d3Force('link');
      if (link) link.distance(90).strength(0.3);
    }, 200);
    return () => clearTimeout(timer);
  }, []);

  // Pause autoRotate on any user interaction, resume after delay
  const handleInteractionStart = useCallback(() => {
    const ctrl = fgRef.current?.controls();
    if (ctrl) ctrl.autoRotate = false;
    if (interactTimer.current) clearTimeout(interactTimer.current);
    interactTimer.current = setTimeout(() => {
      const ctrl2 = fgRef.current?.controls();
      if (ctrl2) ctrl2.autoRotate = true;
    }, AUTO_ROTATE_RESUME_MS);
  }, []);

  // Custom node THREE object
  const nodeThreeObject = useCallback((rawNode: object) => {
    const n = rawNode as EcoNode;
    const catColor = CATEGORY_COLORS[n.category];
    const ringColor = METHOD_RING[n.method];
    const r = nodeRadius(n.val);
    const hidden = hiddenCats.has(n.category);

    const group = new THREE.Group();

    // ── Core sphere
    const sphereGeo = new THREE.SphereGeometry(r, 22, 22);
    const sphereMat = new THREE.MeshBasicMaterial({
      color: catColor,
      transparent: true,
      opacity: hidden ? 0.04 : 0.92,
    });
    group.add(new THREE.Mesh(sphereGeo, sphereMat));

    if (!hidden) {
      // ── Outer glow halo (larger, very transparent)
      const haloGeo = new THREE.SphereGeometry(r * 2.0, 16, 16);
      const haloMat = new THREE.MeshBasicMaterial({
        color: catColor,
        transparent: true,
        opacity: 0.07,
        side: THREE.BackSide,
      });
      group.add(new THREE.Mesh(haloGeo, haloMat));

      // ── Method ring (tilted torus) — only for non-infra nodes
      if (n.method !== 'infra') {
        const torusGeo = new THREE.TorusGeometry(r * 1.75, 0.55, 8, 40);
        const torusMat = new THREE.MeshBasicMaterial({
          color: ringColor,
          transparent: true,
          opacity: n.method === 'ml_dormant' ? 0.55 : 0.85,
        });
        const ring = new THREE.Mesh(torusGeo, torusMat);
        ring.rotation.x = Math.PI * 0.35;
        ring.rotation.z = Math.PI * 0.1;
        group.add(ring);
      }
    }

    // ── Label sprite
    const label = new SpriteText(n.label);
    label.color = hidden ? '#333344' : '#e8ecf4';
    label.textHeight = 2.8;
    label.position.y = -(r + 9);
    if (!hidden) {
      label.backgroundColor = 'rgba(3, 8, 24, 0.65)';
      label.padding = 2;
      (label as unknown as { borderRadius: number }).borderRadius = 3;
    }

    group.add(label);
    return group;
  }, [hiddenCats]);

  // Compute filtered/visible links
  const filteredLinks = graphData.links.filter(l => {
    if (!hiddenCats.size) return true;
    const srcId = typeof l.source === 'object' ? (l.source as EcoNode).id : l.source as string;
    const tgtId = typeof l.target === 'object' ? (l.target as EcoNode).id : l.target as string;
    const src = graphData.nodes.find(n => n.id === srcId);
    const tgt = graphData.nodes.find(n => n.id === tgtId);
    return src && tgt && !hiddenCats.has(src.category) && !hiddenCats.has(tgt.category);
  });

  const displayData = { nodes: graphData.nodes, links: filteredLinks };

  // Node click — zoom camera to node
  const handleNodeClick = useCallback((rawNode: object) => {
    const n = rawNode as EcoNode & { x?: number; y?: number; z?: number };
    // Pause orbit while exploring — resume after delay
    handleInteractionStart();
    setSelected(n);
    if (fgRef.current && n.x !== undefined) {
      const dist = 160;
      const distRatio = 1 + dist / Math.hypot(n.x, n.y ?? 0, n.z ?? 0);
      fgRef.current.cameraPosition(
        { x: n.x * distRatio, y: (n.y ?? 0) * distRatio + 30, z: (n.z ?? 0) * distRatio },
        { x: n.x, y: n.y ?? 0, z: n.z ?? 0 },
        1200,
      );
    }
  }, []);

  const toggleCategory = (cat: NodeCategory) => {
    setHiddenCats(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  // Links connected to selected node
  const connectedLinks = selected
    ? LINKS.filter(l => l.source === selected.id || l.target === selected.id)
    : [];

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div
      style={{ background: '#030810', width: '100vw', height: '100vh', overflow: 'hidden', position: 'relative' }}
      onMouseDown={handleInteractionStart}
      onWheel={handleInteractionStart}
      onTouchStart={handleInteractionStart}
    >

      {/* ── Header HUD ── */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, zIndex: 20,
        padding: '18px 28px 0',
        background: 'linear-gradient(180deg, rgba(3,8,24,0.92) 0%, transparent 100%)',
        pointerEvents: 'none',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
          <h1 style={{ margin: 0, color: '#e8ecf4', fontSize: 22, fontWeight: 700, letterSpacing: 2 }}>
            SPORTSPREDICTOR
          </h1>
          <span style={{ color: '#ffb74d', fontSize: 13, fontWeight: 600, letterSpacing: 3 }}>
            + PEGASUS
          </span>
        </div>
        <p style={{ margin: '3px 0 0', color: '#4a5568', fontSize: 11, letterSpacing: 1 }}>
          ECOSYSTEM ARCHITECTURE &nbsp;·&nbsp; {graphData.nodes.length} NODES &nbsp;·&nbsp; {graphData.links.length} CONNECTIONS
        </p>
      </div>

      {/* ── Legend toggle button ── */}
      <button
        onClick={() => setShowLegend(p => !p)}
        style={{
          position: 'absolute', bottom: 24, left: 24, zIndex: 30,
          background: 'rgba(3,8,24,0.75)', border: '1px solid #1e2a3a',
          borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
          color: '#4a6080', fontSize: 10, letterSpacing: 1,
        }}
      >
        {showLegend ? 'HIDE LEGEND' : 'SHOW LEGEND'}
      </button>

      {/* ── Category + Method Legend ── */}
      {showLegend && (
        <div style={{
          position: 'absolute', bottom: 54, left: 24, zIndex: 20,
          display: 'flex', flexDirection: 'column', gap: 3,
          background: 'rgba(3,8,24,0.82)', border: '1px solid #1a2438',
          borderRadius: 10, padding: '12px 14px',
          backdropFilter: 'blur(8px)',
        }}>
          <div style={{ color: '#3a4a60', fontSize: 9, letterSpacing: 2, marginBottom: 4 }}>LAYER</div>
          {(Object.keys(CATEGORY_COLORS) as NodeCategory[]).map(cat => (
            <button
              key={cat}
              onClick={() => toggleCategory(cat)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0',
              }}
            >
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: hiddenCats.has(cat) ? '#1e2a3a' : CATEGORY_COLORS[cat],
                boxShadow: hiddenCats.has(cat) ? 'none' : `0 0 6px ${CATEGORY_COLORS[cat]}80`,
                flexShrink: 0,
              }} />
              <span style={{
                fontSize: 10, letterSpacing: 0.5,
                color: hiddenCats.has(cat) ? '#2a3a4a' : '#8899bb',
              }}>{CATEGORY_LABELS[cat]}</span>
            </button>
          ))}

          <div style={{ height: 1, background: '#1a2438', margin: '8px 0' }} />
          <div style={{ color: '#3a4a60', fontSize: 9, letterSpacing: 2, marginBottom: 4 }}>METHOD RING</div>
          {(Object.keys(METHOD_RING) as NodeMethod[]).map(m => (
            <div key={m} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 12, height: 3, borderRadius: 2,
                background: METHOD_RING[m],
                boxShadow: `0 0 5px ${METHOD_RING[m]}80`,
              }} />
              <span style={{ fontSize: 10, color: '#7788a8', letterSpacing: 0.4 }}>{METHOD_LABELS[m]}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Instruction hint ── */}
      <div style={{
        position: 'absolute', bottom: 24, right: selected ? 360 : 24, zIndex: 20,
        color: '#1e2d3d', fontSize: 10, letterSpacing: 1,
        textAlign: 'right', pointerEvents: 'none',
        transition: 'right 0.35s ease',
      }}>
        CLICK NODE &nbsp;·&nbsp; DRAG TO ORBIT &nbsp;·&nbsp; SCROLL TO ZOOM
      </div>

      {/* ── Info Panel ── */}
      <div style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, zIndex: 25,
        width: selected ? 320 : 0,
        overflow: 'hidden',
        transition: 'width 0.35s ease',
        pointerEvents: selected ? 'all' : 'none',
      }}>
        {selected && (
          <div style={{
            width: 320, height: '100%',
            background: 'rgba(4, 10, 22, 0.94)',
            borderLeft: `2px solid ${CATEGORY_COLORS[selected.category]}60`,
            backdropFilter: 'blur(12px)',
            overflowY: 'auto',
            padding: '70px 20px 40px',
            display: 'flex', flexDirection: 'column', gap: 14,
          }}>

            {/* close */}
            <button onClick={() => setSelected(null)} style={{
              position: 'absolute', top: 66, right: 16,
              background: 'none', border: '1px solid #1a2438',
              borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
              color: '#3a4a60', fontSize: 16, lineHeight: 1,
            }}>×</button>

            {/* Category badge */}
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '3px 10px', borderRadius: 20, width: 'fit-content',
              background: hex2rgb(CATEGORY_COLORS[selected.category], 0.15),
              border: `1px solid ${CATEGORY_COLORS[selected.category]}40`,
            }}>
              <div style={{
                width: 6, height: 6, borderRadius: '50%',
                background: CATEGORY_COLORS[selected.category],
                boxShadow: `0 0 6px ${CATEGORY_COLORS[selected.category]}`,
              }} />
              <span style={{ color: CATEGORY_COLORS[selected.category], fontSize: 9, fontWeight: 700, letterSpacing: 1.5 }}>
                {CATEGORY_LABELS[selected.category].toUpperCase()}
              </span>
            </div>

            {/* Node name */}
            <h2 style={{ margin: 0, color: '#e8ecf4', fontSize: 17, fontWeight: 700, lineHeight: 1.3 }}>
              {selected.label}
            </h2>

            {/* Method badge */}
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '3px 10px', borderRadius: 20, width: 'fit-content',
              background: hex2rgb(METHOD_RING[selected.method], 0.12),
              border: `1px solid ${METHOD_RING[selected.method]}40`,
            }}>
              <div style={{ width: 16, height: 2, borderRadius: 2, background: METHOD_RING[selected.method] }} />
              <span style={{ color: METHOD_RING[selected.method], fontSize: 9, fontWeight: 600, letterSpacing: 1 }}>
                {METHOD_LABELS[selected.method].toUpperCase()}
              </span>
            </div>

            {/* Description */}
            <p style={{ margin: 0, color: '#8899bb', fontSize: 12, lineHeight: 1.65 }}>
              {selected.desc}
            </p>

            {/* Detail bullets */}
            {selected.details && selected.details.length > 0 && (
              <div style={{ borderLeft: `2px solid ${CATEGORY_COLORS[selected.category]}30`, paddingLeft: 12 }}>
                {selected.details.map((d, i) => (
                  <div key={i} style={{
                    color: '#6678a0', fontSize: 11, lineHeight: 1.6,
                    marginBottom: 5, display: 'flex', gap: 8,
                  }}>
                    <span style={{ color: CATEGORY_COLORS[selected.category], opacity: 0.5, flexShrink: 0 }}>›</span>
                    {d}
                  </div>
                ))}
              </div>
            )}

            {/* Connections */}
            {connectedLinks.length > 0 && (
              <div>
                <div style={{ color: '#2a3a55', fontSize: 9, letterSpacing: 2, marginBottom: 8 }}>
                  CONNECTIONS ({connectedLinks.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {connectedLinks.map((l, i) => {
                    const isOut = l.source === selected.id;
                    const otherId = (isOut ? l.target : l.source) as string;
                    const other = NODES.find(n => n.id === otherId);
                    const oColor = other ? CATEGORY_COLORS[other.category] : '#888';
                    return (
                      <button
                        key={i}
                        onClick={() => {
                          const node = graphData.nodes.find(n => n.id === otherId);
                          if (node) { setSelected(node as EcoNode); handleNodeClick(node); }
                        }}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          background: 'rgba(255,255,255,0.02)', border: '1px solid #0f1a2a',
                          borderRadius: 6, padding: '6px 10px', cursor: 'pointer',
                          textAlign: 'left',
                        }}
                      >
                        <span style={{
                          fontSize: 11, color: isOut ? '#4a6080' : '#3a5050',
                          fontFamily: 'monospace',
                        }}>{isOut ? '→' : '←'}</span>
                        <span style={{ flex: 1, color: oColor, fontSize: 11 }}>{other?.label ?? otherId}</span>
                        {l.label && (
                          <span style={{ color: '#1e2d3d', fontSize: 9 }}>{l.label}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 3-D Graph ── */}
      <ForceGraph3D
        ref={fgRef}
        graphData={displayData}
        width={dims.w}
        height={dims.h}
        backgroundColor="#030810"

        nodeThreeObject={nodeThreeObject}
        nodeThreeObjectExtend={false}

        // Links
        linkColor={(link) => {
          const srcId = typeof link.source === 'object' ? (link.source as EcoNode).id : link.source as string;
          const src = graphData.nodes.find(n => n.id === srcId);
          const base = src ? CATEGORY_COLORS[src.category] : '#334466';
          return (link as { type?: string }).type === 'feedback' ? '#1a2438' : base + '55';
        }}
        linkWidth={(link) => {
          const t = (link as { type?: string }).type;
          if (t === 'feedback') return 0.4;
          if (t === 'control') return 1.6;
          return 1.0;
        }}
        linkOpacity={0.7}

        // Particles
        linkDirectionalParticles={(link) => {
          const t = (link as { type?: string }).type;
          if (t === 'feedback') return 1;
          if (t === 'control') return 5;
          return 3;
        }}
        linkDirectionalParticleWidth={2.2}
        linkDirectionalParticleSpeed={0.004}
        linkDirectionalParticleColor={(link) => {
          const srcId = typeof link.source === 'object' ? (link.source as EcoNode).id : link.source as string;
          const src = graphData.nodes.find(n => n.id === srcId);
          return src ? CATEGORY_COLORS[src.category] : '#88aaff';
        }}

        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={0.95}
        linkDirectionalArrowColor={(link) => {
          const srcId = typeof link.source === 'object' ? (link.source as EcoNode).id : link.source as string;
          const src = graphData.nodes.find(n => n.id === srcId);
          return src ? CATEGORY_COLORS[src.category] + 'cc' : '#88aaff';
        }}

        // Interaction
        onNodeClick={handleNodeClick}
        onBackgroundClick={() => { setSelected(null); }}

        // Simulation
        d3AlphaDecay={0.015}
        d3VelocityDecay={0.35}
        cooldownTicks={250}
        onEngineStop={() => {
          if (hasInitialFit.current) return;   // only act on the very first stop
          hasInitialFit.current = true;
          fgRef.current?.zoomToFit(800, 120);
          // Enable slow auto-rotate after the fit animation settles
          setTimeout(() => {
            const ctrl = fgRef.current?.controls();
            if (ctrl) {
              ctrl.autoRotate = true;
              ctrl.autoRotateSpeed = AUTO_ROTATE_SPEED;
            }
          }, 900);
        }}
      />
    </div>
  );
}
