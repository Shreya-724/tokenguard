import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";

// phase: "checking" | "anonymous" | "staff" | "error"
const CHECKING = { phase: "checking", username: null, error: null };

export function useSession() {
  const [state, setState] = useState(CHECKING);

  const check = useCallback(async () => {
    setState(CHECKING);
    try {
      const who = await api.session();
      setState(
        who.staff
          ? { phase: "staff", username: who.username, error: null }
          : { phase: "anonymous", username: null, error: null },
      );
    } catch (error) {
      setState({ phase: "error", username: null, error: error.message });
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  const login = useCallback(async (username, password) => {
    const who = await api.login(username, password); // throws ApiError on a bad login
    setState({ phase: "staff", username: who.username, error: null });
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setState({ phase: "anonymous", username: null, error: null });
    }
  }, []);

  /** The server said 401/403 mid-session: show the sign-in form. */
  const expire = useCallback(() => {
    setState({ phase: "anonymous", username: null, error: null });
  }, []);

  return { ...state, login, logout, expire, recheck: check };
}
