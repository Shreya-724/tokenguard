// Reconnect delays: 0.5s, 1s, 2s, 4s, 8s, then 10s forever. Doubling, rigid
// (no jitter) and capped, so a dropped socket is retried quickly at first and
// never hammers the server once it is clearly down.
export const BACKOFF_BASE_MS = 500;
export const BACKOFF_MAX_MS = 10_000;

/** Delay before the next attempt, given how many attempts have failed in a row. */
export function backoffDelay(
  failures,
  base = BACKOFF_BASE_MS,
  max = BACKOFF_MAX_MS,
) {
  if (!Number.isInteger(failures) || failures < 0) {
    throw new RangeError(`failures must be a whole number >= 0, got ${failures}`);
  }
  return Math.min(max, base * 2 ** Math.min(failures, 30));
}
