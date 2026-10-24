import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

/** Poll one bucket once a second while `key` is set (never two requests at once). */
export function useBucket(key, { onUnauthorized, intervalMs = 1000 } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: false });
  const unauthorized = useRef(onUnauthorized);

  useEffect(() => {
    unauthorized.current = onUnauthorized;
  });

  useEffect(() => {
    if (!key) {
      setState({ data: null, error: null, loading: false });
      return undefined;
    }
    let cancelled = false;
    let timer = null;
    setState({ data: null, error: null, loading: true });

    const tick = async () => {
      try {
        const data = await api.bucket(key);
        if (!cancelled) setState({ data, error: null, loading: false });
      } catch (err) {
        if (cancelled) return;
        if (err.unauthorized) unauthorized.current?.();
        setState((s) => ({ data: err.status === 404 ? null : s.data, error: err.message, loading: false }));
      }
      if (!cancelled) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [key, intervalMs]);

  return state;
}
