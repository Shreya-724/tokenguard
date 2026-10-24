import { useCallback, useEffect, useRef, useState } from "react";
import { api, feedUrl } from "../lib/api.js";
import { FeedConnection, INITIAL_STATUS } from "../lib/connection.js";
import { mergeSeries } from "../lib/series.js";

const HISTORY_SECONDS = 600; // ten minutes kept in the browser

/**
 * The live feed: connection status plus the latest snapshot and a rolling
 * history built from every snapshot (so the chart survives reconnects).
 */
export function useFeed(enabled, { onUnauthorized } = {}) {
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [snapshot, setSnapshot] = useState(null);
  const [history, setHistory] = useState([]);
  const [receivedAt, setReceivedAt] = useState(null);
  const [backendError, setBackendError] = useState(null);
  const unauthorized = useRef(onUnauthorized);
  const connectionRef = useRef(null);

  useEffect(() => {
    unauthorized.current = onUnauthorized;
  });

  useEffect(() => {
    if (!enabled) return undefined;
    const connection = new FeedConnection({
      url: feedUrl(),
      checkAuth: async () => (await api.session()).staff === true,
      onStatus: (next) => {
        setStatus(next);
        if (next.reason === "unauthorized") unauthorized.current?.();
      },
      onMessage: (message) => {
        if (message.type === "stats") {
          setSnapshot(message);
          setHistory((h) => mergeSeries(h, message.series, HISTORY_SECONDS));
          setReceivedAt(Date.now());
          setBackendError(null);
        } else if (message.type === "error") {
          setBackendError(message.error);
        }
      },
    });
    connectionRef.current = connection;
    connection.start();
    return () => {
      connection.stop();
      connectionRef.current = null;
    };
  }, [enabled]);

  const retryNow = useCallback(() => connectionRef.current?.retryNow(), []);

  return { status, snapshot, history, receivedAt, backendError, retryNow };
}
