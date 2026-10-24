import { useState } from "react";
import { useBucket } from "../hooks/useBucket.js";
import { fmtDuration, fmtNum } from "../lib/format.js";
import { Empty, ErrorBox, Loading } from "./States.jsx";

/** Green-ish while healthy, amber under half, red under a fifth. */
export function gaugeLevel(remaining, capacity) {
  if (!(capacity > 0)) return "ok";
  const fraction = remaining / capacity;
  if (fraction < 0.2) return "bad";
  if (fraction < 0.5) return "warn";
  return "ok";
}

export function BucketGauge({ bucketKey, onKeyChange, onUnauthorized }) {
  const [draft, setDraft] = useState("");
  const { data, error, loading } = useBucket(bucketKey, { onUnauthorized });

  const submit = (event) => {
    event.preventDefault();
    const key = draft.trim();
    if (key) onKeyChange(key);
  };

  const used = data ? Math.max(0, Math.min(data.capacity, data.used)) : 0;
  const level = data ? gaugeLevel(data.remaining, data.capacity) : "ok";
  const remaining = data ? Math.max(0, data.remaining) : 0;

  return (
    <div className="gauge-wrap">
      <form className="inline-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="bucket-key">
          Bucket key
        </label>
        <input
          id="bucket-key"
          className="input"
          placeholder="scope:identity   e.g. default:ip:127.0.0.1"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck={false}
          autoComplete="off"
        />
        <button type="submit" className="btn">
          WATCH
        </button>
      </form>

      {!bucketKey && <Empty label="CLICK A CONSUMER OR ENTER A KEY" />}
      {bucketKey && loading && !data && <Loading label="READING BUCKET" />}
      {bucketKey && error && <ErrorBox message={error} />}
      {bucketKey && data && (
        <div className="gauge-body">
          <div className="gauge-key" title={data.key}>
            <span className="dim">{data.scope}:</span>
            {data.identity}
          </div>
          <div
            className={`gauge gauge-${level}`}
            role="meter"
            aria-label="Bucket level"
            aria-valuemin={0}
            aria-valuemax={data.capacity}
            aria-valuenow={Math.round(remaining * 100) / 100}
          >
            <div className="gauge-fill" style={{ width: `${(remaining / data.capacity) * 100}%` }} />
          </div>
          <dl className="readout">
            <div>
              <dt>REMAINING</dt>
              <dd>
                {fmtNum(remaining, 1)}
                <span className="dim"> / {fmtNum(data.capacity, 1)}</span>
              </dd>
            </div>
            <div>
              <dt>USED</dt>
              <dd>{fmtNum(used, 1)}</dd>
            </div>
            <div>
              <dt>FULL IN</dt>
              <dd>{fmtDuration(data.reset_after)}</dd>
            </div>
            <div>
              <dt>ALGORITHM</dt>
              <dd>{data.algorithm}</dd>
            </div>
          </dl>
          {data.remaining < 0 && <div className="note hot">IN DEBT {fmtNum(-data.remaining, 1)} (a settled LLM overrun)</div>}
        </div>
      )}
    </div>
  );
}
