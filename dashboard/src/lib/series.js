// Pure helpers for the chart and the before/after readout. A "point" is
// { ts, allowed, blocked, tokens } with ts in unix seconds (server time).

/**
 * Merge a fresh series into the history, one point per second. A newer point
 * replaces an older one for the same second (the latest second is still filling
 * up), and anything more than `maxSeconds` older than the newest is dropped.
 */
export function mergeSeries(history, incoming, maxSeconds = 600) {
  const byTs = new Map();
  for (const p of history) byTs.set(p.ts, p);
  for (const p of incoming) byTs.set(p.ts, p);
  const merged = [...byTs.values()].sort((a, b) => a.ts - b.ts);
  if (merged.length === 0) return merged;
  const cutoff = merged[merged.length - 1].ts - maxSeconds + 1;
  return merged.filter((p) => p.ts >= cutoff);
}

/** The last `seconds` seconds of the history. */
export function sliceWindow(history, seconds) {
  if (history.length === 0) return history;
  const cutoff = history[history.length - 1].ts - seconds + 1;
  return history.filter((p) => p.ts >= cutoff);
}

/** Totals over some points. blockedRatio is blocked / requests (0 if none). */
export function summarize(points) {
  let allowed = 0;
  let blocked = 0;
  let tokens = 0;
  for (const p of points) {
    allowed += p.allowed;
    blocked += p.blocked;
    tokens += p.tokens;
  }
  const requests = allowed + blocked;
  return {
    seconds: points.length,
    allowed,
    blocked,
    tokens,
    requests,
    blockedRatio: requests ? blocked / requests : 0,
  };
}

/**
 * Compare traffic before and after a rule change.
 *
 * `changedAt` is when the change was made; `liveAt` is when servers started
 * using it (changedAt + the live-rules cache time). The gap between them is
 * left out of both sides, because during it some servers still run the old rule.
 * Each side looks at up to `span` seconds. `after.seconds` is how much of that
 * has happened yet, so a caller can say "still collecting".
 */
export function beforeAfter(history, changedAt, liveAt, span = 30) {
  const last = history.length ? history[history.length - 1].ts : -Infinity;
  const before = history.filter((p) => p.ts >= changedAt - span && p.ts < changedAt);
  const after = history.filter((p) => p.ts >= liveAt && p.ts < liveAt + span);
  return {
    before: summarize(before),
    after: summarize(after),
    pending: last < liveAt, // the change has not gone live yet
    complete: last >= liveAt + span - 1,
    span,
  };
}

/** Server time now, estimated from the latest snapshot and how long ago it came. */
export function serverNow(snapshot, receivedAt, now = Date.now()) {
  if (!snapshot || receivedAt == null) return Math.floor(now / 1000);
  return snapshot.ts + Math.max(0, (now - receivedAt) / 1000);
}

/** Round-number x-axis ticks (unix seconds) between min and max, about `target`. */
export function timeTicks(min, max, target = 6) {
  if (!(max > min)) return [];
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const wanted = (max - min) / target;
  const step = steps.find((s) => s >= wanted) ?? steps[steps.length - 1];
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) ticks.push(t);
  return ticks;
}

/** Largest y value, rounded up to a tidy number, for a stable axis. */
export function niceMax(points, keys = ["allowed", "blocked"]) {
  let top = 0;
  for (const p of points) for (const k of keys) top = Math.max(top, p[k] ?? 0);
  if (top <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(top));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (m * magnitude >= top) return m * magnitude;
  }
  return 10 * magnitude;
}

/**
 * Which side of a marker line its label goes on: toward the middle of the chart,
 * so a marker near the right edge does not push its text off the plot.
 */
export function labelSide(x, first, last) {
  return last > first && (x - first) / (last - first) > 0.5 ? "Right" : "Left";
}

/**
 * Give each rule-change marker label a row, so labels that would run into each
 * other are stacked instead of overprinted. Markers are placed in time order; a
 * marker takes the first row where its label does not overlap the label of an
 * earlier marker on that row. A label is about `charPx` pixels per character
 * wide and runs away from its line, toward the middle of the chart (see
 * labelSide). `plotPx` is the plot's width in pixels; a smaller guess only makes
 * the spacing more careful. Returns { [id]: row }, rows counted from 0 and
 * capped at `maxRows - 1` (past that, labels share the last row).
 *
 * @param {{id: string, ts: number, label: string}[]} markers
 */
export function markerRows(markers, first, last, { plotPx = 520, charPx = 6.5, gapPx = 10, maxRows = 3 } = {}) {
  const rows = {};
  if (!(last > first)) {
    for (const m of markers) rows[m.id] = 0;
    return rows;
  }
  const secondsPerPx = (last - first) / plotPx;
  const placed = []; // { row, from, to } in seconds
  for (const m of [...markers].sort((a, b) => a.ts - b.ts)) {
    const width = (String(m.label ?? "").length * charPx + gapPx) * secondsPerPx;
    const toLeft = labelSide(m.ts, first, last) === "Right"; // "Right" means the text runs left
    const from = toLeft ? m.ts - width : m.ts;
    const to = toLeft ? m.ts : m.ts + width;
    let row = 0;
    while (row < maxRows - 1 && placed.some((p) => p.row === row && from < p.to && to > p.from)) row += 1;
    placed.push({ row, from, to });
    rows[m.id] = row;
  }
  return rows;
}

/**
 * Where to draw a marker label: x, y and text anchor, from the marker line's
 * viewBox ({ x, y }), the side the text runs to and the row. Rows are 12px apart.
 */
export function markerLabelPlacement(viewBox, side, row = 0) {
  const toLeft = side === "Right";
  return { x: viewBox.x + (toLeft ? -4 : 4), y: viewBox.y + 11 + row * 12, anchor: toLeft ? "end" : "start" };
}
