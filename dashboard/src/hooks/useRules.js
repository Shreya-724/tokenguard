import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

/** The rule list, with save and reset. Errors from changes are thrown to the caller. */
export function useRules(enabled, { onUnauthorized } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const unauthorized = useRef(onUnauthorized);

  useEffect(() => {
    unauthorized.current = onUnauthorized;
  });

  const guard = useCallback((err) => {
    if (err.unauthorized) unauthorized.current?.();
    return err;
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.rules());
      setError(null);
    } catch (err) {
      setError(guard(err).message);
    } finally {
      setLoading(false);
    }
  }, [guard]);

  useEffect(() => {
    if (enabled) reload();
  }, [enabled, reload]);

  const change = useCallback(
    async (call) => {
      try {
        await call();
      } catch (err) {
        throw guard(err);
      }
      await reload();
    },
    [guard, reload],
  );

  const save = useCallback((scope, body) => change(() => api.putRule(scope, body)), [change]);
  const reset = useCallback((scope) => change(() => api.resetRule(scope)), [change]);

  return { data, error, loading, reload, save, reset };
}
