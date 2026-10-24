import { fmtInt, fmtNum, fmtPct } from "../lib/format.js";

function Cell({ label, value, unit, hot }) {
  return (
    <div className={`kpi${hot ? " kpi-hot" : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit ? <span className="kpi-unit">{unit}</span> : null}
      </div>
    </div>
  );
}

/** One readout row, not a row of cards: label over value, hairline dividers. */
export function KpiStrip({ summary, last }) {
  const s = summary;
  return (
    <div className="kpis" role="group" aria-label="Summary">
      <Cell label="REQ/S · NOW" value={last ? fmtInt(last.allowed + last.blocked) : "—"} />
      <Cell label={`REQ/S · ${s ? s.seconds : "—"}S AVG`} value={s ? fmtNum(s.requests_per_second, 2) : "—"} />
      <Cell label="ALLOWED" value={s ? fmtInt(s.allowed) : "—"} />
      <Cell label="BLOCKED" value={s ? fmtInt(s.blocked) : "—"} hot={s && s.blocked > 0} />
      <Cell label="BLOCK RATE" value={s ? fmtPct(s.blocked_ratio) : "—"} hot={s && s.blocked_ratio > 0} />
      <Cell label="TOKENS" value={s ? fmtInt(s.tokens) : "—"} />
    </div>
  );
}
