// Checks on the finished site that keep its promises true: the colours are
// readable, the spacing comes from one scale, and the home page does what the
// privacy page says it does.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const styles = read("src/styles.css");
const home = read("src/home.css");

// ---- colour tokens, evaluated the way the browser does (srgb color-mix) ----

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function tokens() {
  const table = {};
  for (const [, name, value] of styles.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) table[name] = value.trim();
  const resolve = (value) => {
    value = value.trim();
    if (value.startsWith("#")) return hex(value);
    const ref = value.match(/^var\(--([a-z0-9-]+)\)$/);
    if (ref) return resolve(table[ref[1]]);
    const m = value.match(/^color-mix\(in srgb,\s*(.+?)\s+(\d+)%,\s*(.+)\)$/);
    if (m) {
      const a = resolve(m[1]);
      const b = resolve(m[3]);
      const t = Number(m[2]) / 100;
      return a.map((x, i) => x * t + b[i] * (1 - t));
    }
    throw new Error(`cannot evaluate ${value}`);
  };
  return (name) => resolve(`var(--${name})`);
}
const luminance = (rgb) => {
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

test("every text colour is readable on every surface it sits on (WCAG AA, 4.5:1)", () => {
  const colour = tokens();
  const surfaces = ["bg", "bg-2"];
  for (const text of ["text", "dim", "faint", "coral", "allowed", "warn"]) {
    for (const surface of surfaces) {
      const r = ratio(colour(text), colour(surface));
      assert.ok(r >= 4.5, `${text} on ${surface} is ${r.toFixed(2)}:1`);
    }
  }
});

test("the home page pairs are readable too", () => {
  const colour = tokens();
  const navy = colour("navy");
  const cream = colour("cream");
  const mix = (a, b, t) => a.map((x, i) => x * t + b[i] * (1 - t));
  const pairs = {
    "cream on navy": [cream, navy],
    "soft text on navy": [mix(cream, navy, 0.8), navy],
    "soft text on the scene panel": [mix(cream, navy, 0.8), mix(cream, navy, 0.05)],
    "scene captions": [mix(cream, navy, 0.62), mix(cream, navy, 0.05)],
    "navy on cream": [navy, cream],
    "soft text on cream": [mix(navy, cream, 0.82), cream],
    "navy on coral (buttons)": [navy, colour("coral")],
    "coral on the scene panel (429 count)": [colour("coral"), mix(cream, navy, 0.05)],
  };
  for (const [name, [fg, bg]] of Object.entries(pairs)) {
    assert.ok(ratio(fg, bg) >= 4.5, `${name} is ${ratio(fg, bg).toFixed(2)}:1`);
  }
});

// ---- spacing: one scale ----

test("home page margins, paddings and gaps all come from one scale", () => {
  const scale = new Set([0, 4, 8, 12, 16, 24, 32, 48, 64, 96]);
  const bad = [];
  for (const line of home.split("\n")) {
    if (!/^\s*(margin|padding|gap)[a-z-]*:/.test(line)) continue;
    for (const [, px] of line.matchAll(/(\d+)px/g)) {
      if (!scale.has(Number(px))) bad.push(line.trim());
    }
  }
  assert.deepEqual(bad, []);
});

// ---- what the privacy page says, held to the code ----

const sources = (dir) =>
  readdirSync(new URL(`../src/${dir}`, import.meta.url)).map((f) => [`${dir}/${f}`, read(`src/${dir}/${f}`)]);

test("the home page makes no requests and stores nothing in the browser", () => {
  const files = [...sources("home"), ["lib/scene.js", read("src/lib/scene.js")], ["lib/bucketSim.js", read("src/lib/bucketSim.js")]];
  const forbidden = /\b(fetch|XMLHttpRequest|sendBeacon|WebSocket|localStorage|sessionStorage|indexedDB|document\.cookie)\b/;
  for (const [name, text] of files) {
    assert.ok(!forbidden.test(text), `${name} uses a network or storage API`);
  }
});

test("the page loads nothing from another site", () => {
  const html = read("index.html");
  assert.ok(!/<(script|link|img|iframe)[^>]+(src|href)="https?:\/\//i.test(html));
  for (const css of [styles, home]) {
    assert.ok(!/@import\s+url\(\s*['"]?https?:/i.test(css));
    assert.ok(!/url\(\s*['"]?https?:/i.test(css));
  }
});

// ---- the patterns the design avoids ----

test("no gradients as decoration, glass effects, shadows or looping animation", () => {
  for (const css of [styles, home]) {
    assert.ok(!/backdrop-filter|filter:\s*blur|box-shadow|text-shadow|@keyframes|animation:/.test(css));
  }
  assert.ok(!/gradient/.test(home), "the home page has no gradients");
  assert.ok(!/background-clip:\s*text/.test(styles + home), "no gradient headline text");
});

test("every route and the copy buttons have specific labels", () => {
  const text = read("src/home/Home.jsx");
  for (const vague of [">Click here<", ">Learn more<", ">Submit<", ">Get started<"]) {
    assert.ok(!text.includes(vague), vague);
  }
  assert.ok(text.includes("Copy command") && text.includes("Copy code"));
});
