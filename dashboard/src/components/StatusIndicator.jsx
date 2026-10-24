import { useNow } from "../hooks/useNow.js";
import { STATES } from "../lib/connection.js";
import { fmtAge, fmtDuration } from "../lib/format.js";

const STALE_AFTER_MS = 3500; // the feed pushes once a second

/**
 * One square LED and one line of text. The text carries the meaning, the LED
 * only repeats it, so it reads without colour.
 */
export function describeStatus(status, receivedAt, now, backendError) {
  if (status.state === STATES.CONNECTED) {
    const age = receivedAt == null ? null : now - receivedAt;
    if (backendError) return { led: "warn", label: "BACKEND ERROR", detail: backendError };
    if (age == null) return { led: "warn", label: "CONNECTED", detail: "waiting for first frame" };
    if (age > STALE_AFTER_MS) {
      return { led: "warn", label: "STALE", detail: `no data ${fmtAge(age)} · is tokenguard_feed running?` };
    }
    return { led: "ok", label: "CONNECTED", detail: `frame ${fmtAge(age)}` };
  }
  if (status.state === STATES.RECONNECTING) {
    if (status.attempt === 0) return { led: "warn", label: "CONNECTING", detail: "" };
    const wait = status.retryAt == null ? null : Math.max(0, (status.retryAt - now) / 1000);
    return {
      led: "warn",
      label: `RECONNECTING #${status.attempt}`,
      detail: wait == null ? "trying now" : `next try in ${fmtDuration(Math.ceil(wait))}`,
    };
  }
  if (status.reason === "unauthorized") {
    return { led: "bad", label: "DISCONNECTED", detail: "signed out" };
  }
  return { led: "bad", label: "DISCONNECTED", detail: status.reason === "idle" ? "" : status.reason };
}

export function StatusIndicator({ status, receivedAt, backendError, onRetry }) {
  const now = useNow(500);
  const view = describeStatus(status, receivedAt, now, backendError);
  const canRetry = status.state === STATES.RECONNECTING && status.attempt > 0;
  return (
    <div className="status" role="status" aria-live="polite" data-state={status.state}>
      <span className={`led led-${view.led}`} aria-hidden="true" />
      <span className="status-label">{view.label}</span>
      {view.detail ? <span className="status-detail">{view.detail}</span> : null}
      {canRetry && (
        <button type="button" className="btn btn-small" onClick={onRetry}>
          RETRY NOW
        </button>
      )}
    </div>
  );
}
