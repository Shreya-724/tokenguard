import { fmtInt, fmtPct } from "../lib/format.js";
import { Empty, Loading } from "./States.jsx";

function KeyLabel({ scope, identity }) {
  return (
    <span className="keylabel">
      <span className="dim">{scope}:</span>
      {identity}
    </span>
  );
}

/** Heaviest consumers by tokens. Click a row to watch that key's bucket. */
export function ConsumersTable({ rows, loading, selectedKey, onSelect }) {
  if (loading) return <Loading label="AWAITING FIRST FRAME" />;
  if (!rows || rows.length === 0) return <Empty label="NO TRAFFIC IN WINDOW" />;
  const top = Math.max(...rows.map((r) => r.tokens), 1);
  return (
    <table className="table">
      <thead>
        <tr>
          <th className="num">#</th>
          <th>KEY</th>
          <th className="num">TOKENS</th>
          <th className="num">BLOCKED</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.key} className={r.key === selectedKey ? "is-selected" : ""}>
            <td className="num dim">{i + 1}</td>
            <td>
              <button
                type="button"
                className="linkish"
                onClick={() => onSelect(r.key)}
                aria-pressed={r.key === selectedKey}
                title="Watch this bucket"
              >
                <KeyLabel scope={r.scope} identity={r.identity} />
              </button>
              <div className="bar" aria-hidden="true">
                <div className="bar-fill" style={{ width: `${(r.tokens / top) * 100}%` }} />
              </div>
            </td>
            <td className="num">{fmtInt(r.tokens)}</td>
            <td className={`num${r.blocked > 0 ? " hot" : " dim"}`}>{fmtInt(r.blocked)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Who is being turned away. The server counts blocked requests per consumer,
 * not one log line per request, so this is a ranking, not an event list.
 */
export function BlockedList({ rows, loading, selectedKey, onSelect }) {
  if (loading) return <Loading label="AWAITING FIRST FRAME" />;
  if (!rows || rows.length === 0) return <Empty label="NOTHING BLOCKED" />;
  return (
    <table className="table">
      <thead>
        <tr>
          <th>KEY</th>
          <th className="num">BLOCKED</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className={r.key === selectedKey ? "is-selected" : ""}>
            <td>
              <button type="button" className="linkish" onClick={() => onSelect(r.key)} title="Watch this bucket">
                <KeyLabel scope={r.scope} identity={r.identity} />
              </button>
            </td>
            <td className="num hot">{fmtInt(r.blocked)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RoutesTable({ rows, loading }) {
  if (loading) return <Loading label="AWAITING FIRST FRAME" />;
  if (!rows || rows.length === 0) return <Empty label="NO RULES HIT YET" />;
  return (
    <table className="table">
      <thead>
        <tr>
          <th>RULE</th>
          <th className="num">REQ</th>
          <th className="num">BLOCKED</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.scope}>
            <td className="keylabel">{r.scope}</td>
            <td className="num">{fmtInt(r.requests)}</td>
            <td className={`num${r.blocked > 0 ? " hot" : " dim"}`}>
              {fmtPct(r.blocked_ratio, 0)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
