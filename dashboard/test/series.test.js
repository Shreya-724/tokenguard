import assert from "node:assert/strict";
import { test } from "node:test";
import {
  beforeAfter,
  labelSide,
  mergeSeries,
  niceMax,
  serverNow,
  sliceWindow,
  summarize,
  timeTicks,
} from "../src/lib/series.js";

const pt = (ts, allowed = 0, blocked = 0, tokens = 0) => ({ ts, allowed, blocked, tokens });
const run = (from, to, f) => Array.from({ length: to - from + 1 }, (_, i) => f(from + i));

// ---- mergeSeries ----
test("merging into an empty history just sorts", () => {
  assert.deepEqual(mergeSeries([], [pt(3), pt(1), pt(2)]).map((p) => p.ts), [1, 2, 3]);
});

test("a newer point replaces the older one for the same second", () => {
  const merged = mergeSeries([pt(1, 5), pt(2, 1)], [pt(2, 4), pt(3, 9)]);
  assert.deepEqual(merged, [pt(1, 5), pt(2, 4), pt(3, 9)]);
});

test("overlapping snapshots do not duplicate seconds", () => {
  const a = run(100, 159, (ts) => pt(ts, 1));
  const b = run(101, 160, (ts) => pt(ts, 2));
  const merged = mergeSeries(a, b);
  assert.equal(merged.length, 61);
  assert.equal(merged[0].allowed, 1);
  assert.equal(merged[60].allowed, 2);
});

test("history is trimmed to maxSeconds behind the newest point", () => {
  const merged = mergeSeries(run(1, 1000, (ts) => pt(ts)), [], 600);
  assert.equal(merged.length, 600);
  assert.equal(merged[0].ts, 401);
  assert.equal(merged.at(-1).ts, 1000);
});

test("merging does not modify its inputs", () => {
  const history = [pt(1)];
  const incoming = [pt(2)];
  mergeSeries(history, incoming);
  assert.deepEqual(history, [pt(1)]);
  assert.deepEqual(incoming, [pt(2)]);
});

test("a gap while disconnected is filled by the next snapshot", () => {
  const before = run(100, 130, (ts) => pt(ts, 1));
  const afterReconnect = run(111, 170, (ts) => pt(ts, 2)); // the server sends the last 60s
  const merged = mergeSeries(before, afterReconnect);
  assert.deepEqual(merged.map((p) => p.ts), run(100, 170, (t) => t));
});

// ---- window and summary ----
test("sliceWindow keeps the last N seconds", () => {
  const h = run(1, 100, (ts) => pt(ts));
  assert.deepEqual(sliceWindow(h, 60).map((p) => p.ts), run(41, 100, (t) => t));
  assert.equal(sliceWindow(h, 1000).length, 100);
  assert.deepEqual(sliceWindow([], 60), []);
});

test("summarize adds up and computes the blocked ratio", () => {
  const s = summarize([pt(1, 3, 1, 10), pt(2, 5, 3, 20)]);
  assert.deepEqual(s, {
    seconds: 2, allowed: 8, blocked: 4, tokens: 30, requests: 12, blockedRatio: 1 / 3,
  });
});

test("no traffic gives a ratio of 0, not NaN", () => {
  assert.equal(summarize([pt(1), pt(2)]).blockedRatio, 0);
  assert.equal(summarize([]).blockedRatio, 0);
});

// ---- before / after a rule change ----
test("before and after are measured around the change, skipping the propagation gap", () => {
  // heavy blocking until t=1000 (the change), 5 s to go live, then calm
  const h = run(950, 1050, (ts) => (ts < 1005 ? pt(ts, 5, 5) : pt(ts, 10, 0)));
  const r = beforeAfter(h, 1000, 1005, 30);
  assert.equal(r.before.seconds, 30);
  assert.equal(r.before.blockedRatio, 0.5);
  assert.equal(r.after.seconds, 30);
  assert.equal(r.after.blockedRatio, 0);
  assert.equal(r.pending, false);
  assert.equal(r.complete, true);
});

test("the seconds between the change and going live belong to neither side", () => {
  const h = run(990, 1040, (ts) => pt(ts, 1, ts >= 1000 && ts < 1005 ? 100 : 0));
  const r = beforeAfter(h, 1000, 1005, 30);
  assert.equal(r.before.blocked, 0);
  assert.equal(r.after.blocked, 0);
});

test("a change that has not gone live yet is pending", () => {
  const h = run(950, 1002, (ts) => pt(ts, 1));
  const r = beforeAfter(h, 1000, 1005, 30);
  assert.equal(r.pending, true);
  assert.equal(r.after.seconds, 0);
  assert.equal(r.complete, false);
});

test("an after-window that is still filling up reports how much it has", () => {
  const h = run(950, 1015, (ts) => pt(ts, 1));
  const r = beforeAfter(h, 1000, 1005, 30);
  assert.equal(r.pending, false);
  assert.equal(r.after.seconds, 11); // 1005..1015
  assert.equal(r.complete, false);
});

test("a change made before the history starts has an empty 'before'", () => {
  const r = beforeAfter(run(1000, 1060, (ts) => pt(ts)), 900, 905, 30);
  assert.equal(r.before.seconds, 0);
});

test("an empty history is pending, not an error", () => {
  const r = beforeAfter([], 1000, 1005);
  assert.equal(r.pending, true);
  assert.equal(r.before.seconds, 0);
});

// ---- time ----
test("serverNow adds the age of the latest snapshot to its timestamp", () => {
  assert.equal(serverNow({ ts: 1000 }, 5_000, 7_500), 1002.5);
  assert.equal(serverNow({ ts: 1000 }, 5_000, 4_000), 1000); // never goes backwards
  assert.equal(serverNow(null, null, 3_000_000), 3000);
});

test("timeTicks gives round numbers inside the range", () => {
  const ticks = timeTicks(1003, 1063, 6);
  assert.deepEqual(ticks, [1010, 1020, 1030, 1040, 1050, 1060]);
  assert.ok(ticks.every((t) => t >= 1003 && t <= 1063));
});

test("timeTicks widens the step for long windows and handles empty ranges", () => {
  const ticks = timeTicks(0, 600, 6);
  assert.deepEqual(ticks, [0, 120, 240, 360, 480, 600]);
  assert.deepEqual(timeTicks(5, 5), []);
  assert.deepEqual(timeTicks(10, 5), []);
});

test("niceMax picks a stable, tidy axis maximum", () => {
  assert.equal(niceMax([]), 4);
  assert.equal(niceMax([pt(1, 3)]), 4);
  assert.equal(niceMax([pt(1, 7)]), 10);
  assert.equal(niceMax([pt(1, 11)]), 20);
  assert.equal(niceMax([pt(1, 23)]), 25);
  assert.equal(niceMax([pt(1, 51)]), 100);
  assert.equal(niceMax([pt(1, 2, 120)]), 200);
  assert.equal(niceMax([pt(1, 100)]), 100);
});

test("labelSide keeps a marker's label on the chart", () => {
  assert.equal(labelSide(110, 100, 200), "Left"); // near the left edge: text runs right
  assert.equal(labelSide(190, 100, 200), "Right"); // near the right edge: text runs left
  assert.equal(labelSide(150, 100, 200), "Left"); // exactly the middle
  assert.equal(labelSide(5, 10, 10), "Left"); // degenerate window
});
