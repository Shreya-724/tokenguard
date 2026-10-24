// Number and time formatting for the readouts. Everything here is tabular-safe:
// fixed decimals where the value moves, so digits do not jitter as data streams.

const PAD = (n) => String(n).padStart(2, "0");

/** HH:MM:SS for a unix-seconds timestamp (local time, or UTC with utc: true). */
export function fmtClock(ts, { utc = false } = {}) {
  if (ts == null || !Number.isFinite(ts)) return "--:--:--";
  const d = new Date(ts * 1000);
  return utc
    ? `${PAD(d.getUTCHours())}:${PAD(d.getUTCMinutes())}:${PAD(d.getUTCSeconds())}`
    : `${PAD(d.getHours())}:${PAD(d.getMinutes())}:${PAD(d.getSeconds())}`;
}

export function fmtInt(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

/** Up to `digits` decimals, trailing zeros dropped: 12.5, 100, 0.25. */
export function fmtNum(n, digits = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  return String(Number(n.toFixed(digits)));
}

export function fmtPct(ratio, digits = 1) {
  if (ratio == null || !Number.isFinite(ratio)) return "—";
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** 45 -> "45s", 125 -> "2m05s", 3700 -> "1h01m". Null or infinite -> "—". */
export function fmtDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${PAD(s % 60)}s`;
  return `${Math.floor(s / 3600)}h${PAD(Math.floor((s % 3600) / 60))}m`;
}

/** "3s ago", "just now" for a millisecond age. */
export function fmtAge(ms) {
  if (ms == null || !Number.isFinite(ms)) return "never";
  if (ms < 1500) return "just now";
  return `${fmtDuration(ms / 1000)} ago`;
}
