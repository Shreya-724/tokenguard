// Loading, empty and error states: one quiet line each, in the same type as data.

export function Loading({ label = "AWAITING DATA" }) {
  return (
    <div className="state" role="status">
      <span className="state-mark">…</span> {label}
    </div>
  );
}

export function Empty({ label }) {
  return <div className="state state-empty">{label}</div>;
}

export function ErrorBox({ message, onRetry }) {
  return (
    <div className="state state-error" role="alert">
      <span className="state-mark">!</span> {message}
      {onRetry && (
        <button type="button" className="btn btn-small" onClick={onRetry}>
          RETRY
        </button>
      )}
    </div>
  );
}
