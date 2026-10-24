import { useEffect, useState } from "react";
import { fmtNum, fmtPct } from "../lib/format.js";
import { ALGORITHMS, describeChange, formFromRule, isChange, parseRuleForm } from "../lib/rules.js";
import { beforeAfter } from "../lib/series.js";
import { Empty, ErrorBox, Loading } from "./States.jsx";

function Values({ label, v, muted }) {
  const show = (x, f = (y) => y) => (x == null ? "—" : f(x));
  return (
    <tr className={muted ? "dim" : ""}>
      <th scope="row">{label}</th>
      <td className="num">{show(v?.capacity, (x) => fmtNum(x, 3))}</td>
      <td className="num">{show(v?.refill_rate, (x) => fmtNum(x, 3))}</td>
      <td>{show(v?.algorithm)}</td>
    </tr>
  );
}

function BeforeAfter({ change, history }) {
  const r = beforeAfter(history, change.ts, change.liveAt, 30);
  const cell = (side) => (side.requests === 0 ? "no traffic" : fmtPct(side.blockedRatio));
  return (
    <li className="change">
      <div className="change-head">
        <span className="dim">{change.scope}</span> {change.label}
      </div>
      <div className="change-body">
        <span>
          BEFORE <b className={r.before.blockedRatio > 0 ? "hot" : ""}>{cell(r.before)}</b> blocked
        </span>
        <span>
          AFTER{" "}
          {r.pending ? (
            <b className="dim">pending…</b>
          ) : (
            <b className={r.after.blockedRatio > 0 ? "hot" : ""}>{cell(r.after)}</b>
          )}
          {!r.pending && !r.complete && <span className="dim"> ({r.after.seconds}/{r.span}s)</span>}
        </span>
      </div>
    </li>
  );
}

/**
 * Pick a rule, edit it, apply it live. Every change adds a marker to the chart
 * and a BEFORE/AFTER readout (blocked share 30 s before vs 30 s after it goes live).
 */
export function RuleEditor({ rules, selectedScope, onSelectScope, onChanged, history, changes, serverTime }) {
  const list = rules.data?.rules ?? [];
  const rule = list.find((r) => r.scope === selectedScope) ?? list[0];
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);

  // Reset the form when the rule being edited (or its live values) changes.
  const effectiveKey = rule ? JSON.stringify([rule.scope, rule.effective]) : "";
  useEffect(() => {
    if (rule) setForm(formFromRule(rule));
    setErrors({});
    setFailure(null);
  }, [effectiveKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (rules.loading && !rules.data) return <Loading label="LOADING RULES" />;
  if (rules.error && !rules.data) return <ErrorBox message={rules.error} onRetry={rules.reload} />;
  if (!rule || !form) return <Empty label="NO RULES" />;

  const set = (name) => (event) => setForm((f) => ({ ...f, [name]: event.target.value }));
  const ttl = rules.data.ttl;
  const live = rules.data.live_rules_enabled;

  const run = async (action, label) => {
    setBusy(true);
    setFailure(null);
    try {
      await action();
      const ts = Math.floor(serverTime());
      onChanged({ id: `${ts}-${rule.scope}-${label}`, scope: rule.scope, ts, liveAt: ts + (ttl || 0), label });
    } catch (err) {
      setFailure(err.message);
    } finally {
      setBusy(false);
    }
  };

  const apply = (event) => {
    event.preventDefault();
    const result = parseRuleForm(form, rule);
    setErrors(result.errors);
    if (!result.ok) return;
    if (!isChange(rule.effective, result.body)) {
      setFailure("Nothing to apply: these are already the live values.");
      return;
    }
    run(() => rules.save(rule.scope, result.body), describeChange(rule.effective, result.body));
  };

  return (
    <div className="editor">
      {!live && (
        <div className="note warn" role="alert">
          LIVE_RULES IS OFF: changes are stored but servers ignore them.
        </div>
      )}
      <label className="sr-only" htmlFor="rule-scope">
        Rule
      </label>
      <select id="rule-scope" className="input" value={rule.scope} onChange={(e) => onSelectScope(e.target.value)}>
        {list.map((r) => (
          <option key={r.scope} value={r.scope}>
            {r.scope}
            {r.override ? "  [overridden]" : ""}
          </option>
        ))}
      </select>

      <table className="table compact">
        <thead>
          <tr>
            <th />
            <th className="num">CAPACITY</th>
            <th className="num">REFILL/S</th>
            <th>ALGORITHM</th>
          </tr>
        </thead>
        <tbody>
          <Values label="CONFIGURED" v={rule.configured} muted />
          <Values label="OVERRIDE" v={rule.override} muted />
          <Values label="EFFECTIVE" v={rule.effective} />
        </tbody>
      </table>

      <form onSubmit={apply} noValidate>
        <div className="fields">
          <div>
            <label htmlFor="f-cap">CAPACITY</label>
            <input id="f-cap" className={`input${errors.capacity ? " is-bad" : ""}`} inputMode="decimal" value={form.capacity} onChange={set("capacity")} aria-invalid={Boolean(errors.capacity)} />
            {errors.capacity && <div className="field-error">{errors.capacity}</div>}
          </div>
          <div>
            <label htmlFor="f-rate">REFILL / S</label>
            <input id="f-rate" className={`input${errors.refill_rate ? " is-bad" : ""}`} inputMode="decimal" value={form.refill_rate} onChange={set("refill_rate")} aria-invalid={Boolean(errors.refill_rate)} />
            {errors.refill_rate && <div className="field-error">{errors.refill_rate}</div>}
          </div>
          <div className="wide">
            <label htmlFor="f-algo">ALGORITHM</label>
            <select id="f-algo" className={`input${errors.algorithm ? " is-bad" : ""}`} value={form.algorithm} onChange={set("algorithm")}>
              {ALGORITHMS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            {errors.algorithm && <div className="field-error">{errors.algorithm}</div>}
          </div>
        </div>
        {failure && <ErrorBox message={failure} />}
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "APPLYING…" : "APPLY LIVE"}
          </button>
          <button type="button" className="btn" disabled={busy || !rule.override} onClick={() => run(() => rules.reset(rule.scope), "reset to settings")}>
            RESET
          </button>
        </div>
        <p className="hint dim">Servers pick a change up within {fmtNum(ttl, 1)}s (LIVE_RULES_TTL). Rules version {rules.data.version}.</p>
      </form>

      <h3 className="subhead">CHANGES · BEFORE / AFTER</h3>
      {changes.length === 0 ? (
        <Empty label="NO CHANGES THIS SESSION" />
      ) : (
        <ul className="changes">
          {changes.map((c) => (
            <BeforeAfter key={c.id} change={c} history={history} />
          ))}
        </ul>
      )}
    </div>
  );
}
