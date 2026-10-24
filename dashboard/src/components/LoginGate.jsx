import { useState } from "react";
import { ErrorBox, Loading } from "./States.jsx";

export function LoginGate({ phase, error, onLogin, onRetry }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);

  if (phase === "checking") {
    return (
      <div className="gate">
        <Loading label="CHECKING SESSION" />
      </div>
    );
  }
  if (phase === "error") {
    return (
      <div className="gate">
        <ErrorBox message={`Cannot reach the server: ${error}`} onRetry={onRetry} />
      </div>
    );
  }

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await onLogin(username.trim(), password);
    } catch (err) {
      setFailure(err.message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gate">
      <form className="login" onSubmit={submit}>
        <h1 className="brand">TOKENGUARD</h1>
        <p className="dim">STAFF SIGN-IN</p>
        <label htmlFor="user">USERNAME</label>
        <input id="user" className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
        <label htmlFor="pass">PASSWORD</label>
        <input id="pass" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        {failure && <ErrorBox message={failure} />}
        <button type="submit" className="btn btn-primary" disabled={busy || !username || !password}>
          {busy ? "SIGNING IN…" : "SIGN IN"}
        </button>
      </form>
    </div>
  );
}
