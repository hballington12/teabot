// The home page's background: a 3D branching fractal in metal-grey line art, turning slowly. Branches grow out
// from the centre over a sphere and split, at random angles and lengths, into two or three, several levels deep.
// Each of the main branches lives its own cycle: it grows out a level at a time, holds, withers from the tips back to
// the centre, then regrows in a new random shape. The cycles are staggered, so some branches are always growing and
// some withering, and the whole never repeats. Nearer lines are brighter and thicker, farther ones fainter, and the
// branches sway a little as it turns. It runs only on the home page, pauses in a hidden tab, and draws one still
// frame for readers who ask for reduced motion.
(() => {
  const FPS = 30;
  const DEPTH = 7; // levels of branching
  const ROOTS = 7; // branches from the centre
  const TURN = 0.006; // radians a second about the vertical axis
  const SWAY = 0.035; // how far the branches sway, in radians
  const LIFE = 16; // seconds in one branch's cycle of growing, holding and withering
  const GROWING = 0.9; // the weight of growing out in a cycle
  const HOLDING = 0.2; // the weight of staying full
  const WITHERING = 0.6; // the weight of withering back; at least a sixth of the cycle, whatever the weights
  const LAG = 0.7; // how far, in levels, nodes of one level spread their start, so a level never sprouts at once

  const INK = {
    // Light steel on the dark page.
    slate: { line: [196, 202, 212], tip: [226, 230, 236], alpha: [0.05, 0.42] },
    // Graphite on the light page.
    default: { line: [72, 78, 90], tip: [44, 48, 58], alpha: [0.06, 0.5] },
  };

  let canvas = null;
  let ctx = null;
  let frame = 0;
  let last = 0;
  let width = 0;
  let height = 0;
  let scale = 1;
  let roots = [];
  let seed = 0;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const scheme = () => (document.body.getAttribute("data-md-color-scheme") === "slate" ? "slate" : "default");

  // A small seeded generator, so one visit's fractal stays the same shape while it turns.
  function generator(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s + 0x6d2b79f5) >>> 0;
      let r = Math.imul(s ^ (s >>> 15), 1 | s);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const times = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = (a) => times(a, 1 / (Math.hypot(a[0], a[1], a[2]) || 1));

  // `d` turned by `angle` about the axis `k` (Rodrigues' rotation).
  function turn(d, k, angle) {
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const dot = d[0] * k[0] + d[1] * k[1] + d[2] * k[2];
    return add(add(times(d, c), times(cross(k, d), s)), times(k, dot * (1 - c)));
  }

  // The main branches, each with its own place in the cycle and, once grown, its nodes. Each node has its parent,
  // its direction and length relative to the parent, and a phase for its sway; positions are worked out each frame,
  // so the sway runs down every branch below.
  function sow() {
    const golden = Math.PI * (3 - Math.sqrt(5));
    return Array.from({ length: ROOTS }, (_, i) => {
      const y = 1 - (2 * (i + 0.5)) / ROOTS;
      const r = Math.sqrt(1 - y * y);
      const a = golden * i;
      return { home: [Math.cos(a) * r, y, Math.sin(a) * r], offset: (LIFE * i) / ROOTS, cycle: -1, nodes: [] };
    });
  }

  // A branch's shape for one cycle: a new random shape, leaning a little away from its home direction.
  function regrow(root, cycle) {
    const random = generator(seed + root.offset * 1000 + cycle * 7919);
    const jitter = () => (random() - 0.5) * 0.5;
    const dir = unit(add(root.home, [jitter(), jitter(), jitter()]));
    root.nodes = [];
    root.cycle = cycle;
    branch(root.nodes, -1, dir, 0.3 + random() * 0.08, 0, random);
    for (const node of root.nodes) node.leaf = true;
    for (const node of root.nodes) if (node.parent >= 0) root.nodes[node.parent].leaf = false;
  }

  // The three phases as shares of the cycle that add up to it. Withering always keeps a sixth, so every cycle ends
  // with nothing grown, and a branch is never wiped while it shows.
  const PHASES = (() => {
    const wither = Math.max(WITHERING, (GROWING + HOLDING) / 5);
    const total = GROWING + HOLDING + wither;
    return { grow: GROWING / total, hold: HOLDING / total };
  })();

  // How far out a branch has grown, in levels, at `u` seconds into its cycle: it rises, holds, then falls back to
  // nothing. It reaches past the last level by LAG, so the latest-starting nodes grow fully too.
  function front(u) {
    const share = u / LIFE;
    const ease = (x) => x * x * (3 - 2 * x);
    const full = DEPTH + 1 + LAG;
    const { grow, hold } = PHASES;
    if (share < grow) return full * ease(share / grow);
    if (share < grow + hold) return full;
    return full * (1 - ease((share - grow - hold) / (1 - grow - hold)));
  }

  function branch(nodes, parent, dir, length, depth, random) {
    const index = nodes.length;
    const axis = unit(cross(dir, Math.abs(dir[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]));
    nodes.push({ parent, dir, length, depth, axis, phase: random() * Math.PI * 2, lag: random() * LAG });
    if (depth >= DEPTH) return;
    const count = random() < 0.22 ? 3 : 2;
    const spin = random() * Math.PI * 2;
    for (let c = 0; c < count; c++) {
      // Each child leans away from its parent's line, spread evenly around it, with some randomness.
      const around = turn(axis, dir, spin + (c * Math.PI * 2) / count + (random() - 0.5) * 0.6);
      const lean = 0.42 + random() * 0.38;
      const child = unit(turn(dir, around, lean));
      if (random() < 0.08 && depth > 2) continue; // now and then a branch stops early
      branch(nodes, index, child, length * (0.66 + random() * 0.12), depth + 1, random);
    }
  }

  // Each node's end, in the fractal's own space, and how grown it is, from 0 to 1. A node grows out of its parent's
  // end as the branch's front passes its level, and withers back into it as the front returns.
  function place(root, t) {
    const reach = front((t + root.offset) % LIFE);
    const ends = new Array(root.nodes.length);
    const grown = new Array(root.nodes.length);
    for (let i = 0; i < root.nodes.length; i++) {
      const n = root.nodes[i];
      const sway = Math.sin(t * 0.4 + n.phase) * SWAY * (1 + n.depth * 0.15);
      const dir = n.parent < 0 ? n.dir : turn(n.dir, n.axis, sway);
      const g = Math.min(1, Math.max(0, reach - n.depth - n.lag));
      grown[i] = g * g * (3 - 2 * g);
      const start = n.parent < 0 ? [0, 0, 0] : ends[n.parent];
      ends[i] = add(start, times(dir, n.length * grown[i]));
    }
    return { ends, grown, reach };
  }

  function draw(now) {
    const t = now / 1000;
    const ink = INK[scheme()];
    const yaw = t * TURN;
    const pitch = 0.32 + Math.sin(t * 0.045) * 0.12;
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const cp = Math.cos(pitch);
    const sp = Math.sin(pitch);
    const size = Math.min(width, height) * 0.62;
    const camera = 3.2;
    const project = (p) => {
      const x = p[0] * cy + p[2] * sy;
      const z0 = -p[0] * sy + p[2] * cy;
      const y = p[1] * cp - z0 * sp;
      const z = p[1] * sp + z0 * cp;
      const k = camera / (camera - z);
      return [width / 2 + x * size * k, height / 2 - y * size * k, z];
    };
    const centre = project([0, 0, 0]);
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.lineCap = "round";
    const [lo, hi] = ink.alpha;
    for (const root of roots) {
      const cycle = Math.floor((t + root.offset) / LIFE);
      if (cycle !== root.cycle) regrow(root, cycle);
      const { ends, grown, reach } = place(root, t);
      const points = ends.map(project);
      for (let i = 0; i < root.nodes.length; i++) {
        const node = root.nodes[i];
        if (grown[i] <= 0.001) continue;
        const a = node.parent < 0 ? centre : points[node.parent];
        const b = points[i];
        const near = Math.min(1, Math.max(0, ((a[2] + b[2]) / 2 + 1.1) / 2.2)); // 0 far, 1 near
        const fade = (1 - node.depth / (DEPTH + 2)) * grown[i];
        ctx.strokeStyle = `rgba(${ink.line.join(",")},${(lo + (hi - lo) * near * fade).toFixed(3)})`;
        ctx.lineWidth = 0.5 + near * 1.3 * fade + 0.3;
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(b[0], b[1]);
        ctx.stroke();
        // A dot marks a tip. It fades out as the node's children grow from it and back in as they wither, so it
        // never appears or vanishes at once; a branch that ends here keeps its dot while it is grown.
        const next = Math.min(1, Math.max(0, reach - (node.depth + 1) - LAG / 2));
        const shown = grown[i] * (node.leaf ? 1 : 1 - next * next * (3 - 2 * next));
        if (shown > 0.01) {
          ctx.fillStyle = `rgba(${ink.tip.join(",")},${((lo + (hi - lo) * near) * shown).toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(b[0], b[1], (0.8 + near * 1.4) * Math.sqrt(shown), 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }

  function tick(now) {
    frame = requestAnimationFrame(tick);
    if (now - last < 1000 / FPS || document.hidden) return;
    last = now;
    draw(now);
  }

  function resize() {
    scale = Math.min(window.devicePixelRatio || 1, 1.5);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    // Resizing a canvas clears it, so draw again at once rather than leave it blank until the next frame, which
    // flickered while a window was being resized.
    draw(performance.now());
  }

  function start() {
    if (canvas) return;
    seed = Math.floor(Math.random() * 2 ** 31);
    roots = sow();
    canvas = document.createElement("canvas");
    canvas.className = "teabot-backdrop";
    canvas.setAttribute("aria-hidden", "true");
    document.body.prepend(canvas);
    ctx = canvas.getContext("2d");
    resize();
    window.addEventListener("resize", resize);
    if (reduced.matches) draw(performance.now());
    else frame = requestAnimationFrame(tick);
  }

  function stop() {
    if (!canvas) return;
    cancelAnimationFrame(frame);
    window.removeEventListener("resize", resize);
    canvas.remove();
    canvas = null;
  }

  function page() {
    if (document.querySelector(".teabot-paths")) start();
    else stop();
  }

  // The theme loads pages without a full reload and announces each through document$.
  if (window.document$) window.document$.subscribe(page);
  else document.addEventListener("DOMContentLoaded", page);
  // A still frame follows a change of scheme; the animation picks it up by itself.
  new MutationObserver(() => {
    if (canvas && reduced.matches) draw(performance.now());
  }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
})();
