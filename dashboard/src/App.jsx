import { useCallback, useEffect, useMemo, useState } from "react";
import { BucketGauge } from "./components/BucketGauge.jsx";
import { KpiStrip } from "./components/KpiStrip.jsx";
import { LoginGate } from "./components/LoginGate.jsx";
import { Panel } from "./components/Panel.jsx";
import { RuleEditor } from "./components/RuleEditor.jsx";
import { StatusIndicator } from "./components/StatusIndicator.jsx";
import { BlockedList, ConsumersTable, RoutesTable } from "./components/Tables.jsx";
import { TrafficChart } from "./components/TrafficChart.jsx";
import { useFeed } from "./hooks/useFeed.js";
import { useRules } from "./hooks/useRules.js";
import { useSession } from "./hooks/useSession.js";
import { serverNow } from "./lib/series.js";

const MAX_CHANGES = 6;

function Dashboard({ username, onSignOut, onExpired }) {
  const feed = useFeed(true, { onUnauthorized: onExpired });
  const rules = useRules(true, { onUnauthorized: onExpired });
  const [windowSeconds, setWindowSeconds] = useState(60);
  const [bucketKey, setBucketKey] = useState(null);
  const [scope, setScope] = useState(null);
  const [changes, setChanges] = useState([]);

  const { snapshot, history, receivedAt, status, backendError } = feed;
  const loading = snapshot == null;
  const last = history.length ? history[history.length - 1] : null;

  // Forget chart markers that have scrolled out of the buffered history.
  const oldest = history.length ? history[0].ts : null;
  const visibleChanges = useMemo(
    () => (oldest == null ? changes : changes.filter((c) => c.liveAt >= oldest)),
    [changes, oldest],
  );

  const serverTime = useCallback(() => serverNow(snapshot, receivedAt), [snapshot, receivedAt]);
  const onChanged = useCallback((change) => {
    setChanges((all) => [change, ...all].slice(0, MAX_CHANGES));
  }, []);

  useEffect(() => {
    document.title = `TOKENGUARD · ${status.state.toUpperCase()}`;
  }, [status.state]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="bar-left">
          <span className="brand">TOKENGUARD</span>
          <span className="bar-meta">RULES v{rules.data ? rules.data.version : "—"}</span>
        </div>
        <StatusIndicator status={status} receivedAt={receivedAt} backendError={backendError} onRetry={feed.retryNow} />
        <div className="bar-right">
          <span className="bar-meta">{username}</span>
          <button type="button" className="btn btn-small" onClick={onSignOut}>
            SIGN OUT
          </button>
        </div>
      </header>

      <main className="layout">
        <KpiStrip summary={snapshot?.summary} last={last} />

        <div className="col-main">
          <Panel title="TRAFFIC · REQUESTS PER SECOND" meta={snapshot ? `${snapshot.summary.seconds}s window` : null} className="panel-chart">
            {loading ? (
              <div className="state" role="status">
                <span className="state-mark">…</span> AWAITING FIRST FRAME
              </div>
            ) : (
              <TrafficChart history={history} windowSeconds={windowSeconds} onWindowChange={setWindowSeconds} markers={visibleChanges} />
            )}
          </Panel>

          <div className="row-2">
            <Panel title="TOP CONSUMERS · TOKENS" meta="last 2 min">
              <ConsumersTable rows={snapshot?.consumers} loading={loading} selectedKey={bucketKey} onSelect={setBucketKey} />
            </Panel>
            <Panel title="MOST BLOCKED" meta="last 2 min">
              <BlockedList rows={snapshot?.blocked_consumers} loading={loading} selectedKey={bucketKey} onSelect={setBucketKey} />
            </Panel>
          </div>

          <Panel title="RULES · TRAFFIC" meta="last 2 min">
            <RoutesTable rows={snapshot?.routes} loading={loading} />
          </Panel>
        </div>

        <div className="col-side">
          <Panel title="BUCKET LEVEL" meta="live · 1s">
            <BucketGauge bucketKey={bucketKey} onKeyChange={setBucketKey} onUnauthorized={onExpired} />
          </Panel>
          <Panel title="RULE EDITOR" meta={rules.data ? (rules.data.live_rules_enabled ? "live rules on" : "live rules OFF") : null}>
            <RuleEditor
              rules={rules}
              selectedScope={scope}
              onSelectScope={setScope}
              onChanged={onChanged}
              history={history}
              changes={changes}
              serverTime={serverTime}
            />
          </Panel>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const session = useSession();
  if (session.phase !== "staff") {
    return <LoginGate phase={session.phase} error={session.error} onLogin={session.login} onRetry={session.recheck} />;
  }
  return <Dashboard username={session.username} onSignOut={session.logout} onExpired={session.expire} />;
}
