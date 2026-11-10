// The animation on the home page: requests travel from the left toward an API on
// the right and pass a gate. The gate is a real token bucket (see bucketSim.js).
// A request that finds a token goes through, and the token falls out of the bucket.
// A request that finds none is turned back with a 429.
//
// Plain canvas code with no React in it, so it can be tested in any browser.
// With reduced motion there is no animation loop: sending requests settles
// them instantly and the picture just updates.

import { advance, createBucket, take } from "./bucketSim.js";

export const RULE = { capacity: 8, refillPerSecond: 2 };

const W = 720;
const H = 380;
const LANE_Y = 290;
const GATE_X = 360;
const START_X = 56;
const SERVER = { x: 618, y: 248, w: 84, h: 84 };
const SPEED = 250; // px per second
const BURST = 12;
const BURST_GAP = 0.09; // seconds between requests in a burst
const COLORS = {
  navy: "#14213D",
  cream: "#F4EDE0",
  coral: "#FF6B5B",
};
const SLOT_COLUMNS = 4;
const SLOT = { left: 288, top: 78, dx: 48, dy: 52, r: 15 };

const slotCenter = (i) => ({
  x: SLOT.left + (i % SLOT_COLUMNS) * SLOT.dx,
  y: SLOT.top + Math.floor(i / SLOT_COLUMNS) * SLOT.dy,
});

const ease = (t) => t * t; // accelerating, like something falling

function mix(a, b, t) {
  const p = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const [r1, g1, b1] = p(a);
  const [r2, g2, b2] = p(b);
  const c = (x, y) => Math.round(x + (y - x) * t);
  return `rgb(${c(r1, r2)}, ${c(g1, g2)}, ${c(b1, b2)})`;
}

/**
 * @param canvas      the <canvas> to draw on
 * @param options     { animate: boolean, onStats(stats), fontFamily }
 * @returns           { send(n), destroy() }
 */
export function createScene(canvas, { animate = true, onStats = () => {}, fontFamily = "sans-serif" } = {}) {
  const ctx = canvas.getContext("2d");
  const bucket = createBucket(RULE.capacity, RULE.refillPerSecond);
  const stats = { allowed: 0, blocked: 0, tokens: bucket.tokens };

  let requests = []; // { x, state, alpha }
  let falling = []; // tokens leaving the bucket { slot, t }
  let labels = []; // "429" floating up { t }
  let queue = 0; // requests waiting to be launched
  let sinceLaunch = 0;
  let nextBurstIn = 2.2; // the first burst comes quickly, so the page is alive on arrival
  let trickleIn = 0.6;
  let serverFlash = 0;
  let gateFlash = 0;
  let labelCooldown = 0;
  let last = null;
  let frame = null;
  let destroyed = false;
  let scale = 1;
  let reported = 0;

  const publish = () => {
    stats.tokens = bucket.tokens;
    onStats({ ...stats });
  };

  function decide(request) {
    if (take(bucket, 1)) {
      stats.allowed += 1;
      falling.push({ slot: Math.min(RULE.capacity - 1, Math.floor(bucket.tokens + 1e-9)), t: 0 });
      request.state = "through";
    } else {
      stats.blocked += 1;
      request.state = "blocked";
      request.bounced = 0;
      if (labelCooldown <= 0) {
        labels.push({ t: 0 });
        labelCooldown = 0.35;
      }
      gateFlash = 0.35;
    }
    publish();
  }

  function step(dt) {
    advance(bucket, dt);

    // Launch requests: queued ones at a steady gap, plus a slow background trickle
    // and a burst now and then, so the bucket sometimes runs dry.
    nextBurstIn -= dt;
    trickleIn -= dt;
    if (nextBurstIn <= 0) {
      queue += BURST;
      nextBurstIn = 5 + Math.random() * 2;
    }
    if (trickleIn <= 0) {
      queue += 1;
      trickleIn = 0.7 + Math.random() * 0.6;
    }
    sinceLaunch += dt;
    while (queue > 0 && sinceLaunch >= BURST_GAP) {
      requests.push({ x: START_X, state: "approach", alpha: 1 });
      queue -= 1;
      sinceLaunch -= BURST_GAP;
    }
    if (queue === 0) sinceLaunch = Math.min(sinceLaunch, BURST_GAP);

    for (const r of requests) {
      if (r.state === "approach") {
        r.x += SPEED * dt;
        if (r.x >= GATE_X - 14) decide(r);
      } else if (r.state === "through") {
        r.x += SPEED * dt;
        if (r.x >= SERVER.x - 4) {
          r.state = "done";
          serverFlash = 0.3;
        }
      } else if (r.state === "blocked") {
        // Turned back: up and away from the lane, so it can be told apart from
        // the requests still on their way in.
        r.x -= SPEED * 0.55 * dt;
        r.bounced += SPEED * 0.55 * dt;
        r.alpha = Math.max(0, 1 - r.bounced / 90);
        if (r.alpha === 0) r.state = "done";
      }
    }
    requests = requests.filter((r) => r.state !== "done");
    for (const f of falling) f.t += dt / 0.3;
    falling = falling.filter((f) => f.t < 1);
    for (const l of labels) l.t += dt / 0.9;
    labels = labels.filter((l) => l.t < 1);
    serverFlash = Math.max(0, serverFlash - dt);
    gateFlash = Math.max(0, gateFlash - dt);
    labelCooldown = Math.max(0, labelCooldown - dt);

    reported += dt;
    if (reported >= 0.25) {
      reported = 0;
      publish();
    }
  }

  function text(str, x, y, { size = 13, color = COLORS.cream, alpha = 1, weight = 500, align = "center" } = {}) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.font = `${weight} ${size}px ${fontFamily}`;
    ctx.textAlign = align;
    ctx.textBaseline = "middle";
    ctx.fillText(str, x, y);
    ctx.globalAlpha = 1;
  }

  function disc(x, y, r, fill, alpha = 1) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function draw() {
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, W, H);

    // The bucket: a frame, and one slot per token it can hold.
    ctx.lineWidth = 2;
    ctx.strokeStyle = mix(COLORS.navy, COLORS.cream, 0.42);
    roundRect(252, 40, 216, 124, 16);
    ctx.stroke();
    const whole = Math.floor(bucket.tokens + 1e-9);
    const part = bucket.tokens - whole;
    for (let i = 0; i < RULE.capacity; i++) {
      const { x, y } = slotCenter(i);
      if (i < whole) {
        disc(x, y, SLOT.r, COLORS.cream);
        ctx.strokeStyle = COLORS.navy;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, SLOT.r - 5, 0, Math.PI * 2);
        ctx.stroke();
      } else {
        ctx.setLineDash([3, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = mix(COLORS.navy, COLORS.cream, 0.3);
        ctx.beginPath();
        ctx.arc(x, y, SLOT.r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        if (i === whole && part > 0.02) disc(x, y, SLOT.r * part, COLORS.cream, 0.75);
      }
    }
    text("tokens", 360, 183, { size: 12.5, alpha: 0.6 });

    // Tokens spent by an allowed request fall to the gate and fade out.
    for (const f of falling) {
      const from = slotCenter(f.slot);
      const e = ease(f.t);
      disc(from.x + (GATE_X - from.x) * e, from.y + (LANE_Y - 18 - from.y) * e, SLOT.r * (1 - 0.4 * e), COLORS.cream, 1 - f.t);
    }

    // The lane, the gate and the two ends.
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = mix(COLORS.navy, COLORS.cream, 0.18);
    ctx.setLineDash([2, 7]);
    ctx.beginPath();
    ctx.moveTo(START_X - 20, LANE_Y);
    ctx.lineTo(SERVER.x, LANE_Y);
    ctx.stroke();
    ctx.setLineDash([]);

    const gate = gateFlash > 0 ? COLORS.coral : mix(COLORS.navy, COLORS.cream, 0.7);
    ctx.fillStyle = gate;
    ctx.fillRect(GATE_X - 9, LANE_Y - 48, 4, 38);
    ctx.fillRect(GATE_X + 5, LANE_Y - 48, 4, 38);
    ctx.fillRect(GATE_X - 9, LANE_Y + 10, 4, 38);
    ctx.fillRect(GATE_X + 5, LANE_Y + 10, 4, 38);
    text("limiter", GATE_X, LANE_Y + 72, { size: 12.5, alpha: 0.6 });
    text("clients", START_X, LANE_Y + 72, { size: 12.5, alpha: 0.6 });

    const glow = serverFlash / 0.3;
    ctx.lineWidth = 2;
    ctx.strokeStyle = mix(COLORS.navy, COLORS.cream, 0.5 + 0.5 * glow);
    ctx.fillStyle = mix(COLORS.navy, COLORS.cream, 0.08 + 0.16 * glow);
    roundRect(SERVER.x, SERVER.y, SERVER.w, SERVER.h, 12);
    ctx.fill();
    ctx.stroke();
    text("your API", SERVER.x + SERVER.w / 2, SERVER.y + SERVER.h / 2, { size: 14, weight: 600 });

    // Requests. A refused one turns coral and is sent back.
    for (const r of requests) {
      if (r.state === "blocked") {
        const lift = 52 * (1 - (1 - Math.min(1, r.bounced / 90)) ** 2);
        disc(r.x, LANE_Y - lift, 9, COLORS.coral, r.alpha);
      } else {
        disc(r.x, LANE_Y, 8, COLORS.cream, r.alpha);
      }
    }
    for (const l of labels) {
      text("429", GATE_X - 44, LANE_Y - 62 - 22 * l.t, { size: 18, weight: 700, color: COLORS.coral, alpha: 1 - l.t * l.t });
    }
  }

  function resize() {
    const width = canvas.clientWidth || W;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(width * (H / W) * dpr);
    scale = canvas.width / W;
    draw();
  }

  function tick(now) {
    if (destroyed) return;
    const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
    last = now;
    step(dt);
    draw();
    frame = requestAnimationFrame(tick);
  }

  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  observer?.observe(canvas);
  resize();
  publish();
  if (animate) frame = requestAnimationFrame(tick);

  return {
    /** Send n requests now. */
    send(n = BURST) {
      if (animate) {
        queue += n;
        return;
      }
      // No animation: settle them at once and redraw.
      for (let i = 0; i < n; i++) {
        if (take(bucket, 1)) stats.allowed += 1;
        else stats.blocked += 1;
      }
      publish();
      draw();
    },
    destroy() {
      destroyed = true;
      if (frame != null) cancelAnimationFrame(frame);
      observer?.disconnect();
    },
    // for tests and screenshots
    _debug: { bucket, stats },
  };
}
