// The live-feed connection as an explicit state machine, with no React in it.
//
//   connected     the socket is open
//   reconnecting  trying to connect (attempt 0) or waiting to retry (attempt > 0)
//   disconnected  not trying: never started, stopped, or refused for good
//                 (reason "unauthorized": sign in again, retrying cannot help)
//
// A socket that drops is retried with doubling delays up to a 10 s cap. A
// socket that stays open but goes silent (no frames, no pong) is declared dead
// after `deadAfterMs` and replaced. Everything time-related is injectable, so
// the tests drive it with a fake clock and a fake WebSocket.
import { backoffDelay } from "./backoff.js";

export const STATES = Object.freeze({
  CONNECTED: "connected",
  DISCONNECTED: "disconnected",
  RECONNECTING: "reconnecting",
});

export const INITIAL_STATUS = Object.freeze({
  state: STATES.DISCONNECTED,
  attempt: 0, // consecutive failures so far
  retryAt: null, // ms timestamp of the next attempt, while waiting
  reason: "idle",
  since: 0,
});

const OPEN = 1;

export class FeedConnection {
  #o;
  #ws = null;
  #running = false;
  #failures = 0;
  #gen = 0; // bumped whenever a socket is retired, so its late events are ignored
  #opened = false;
  #lastActivity = 0;
  #retryTimer = null;
  #beatTimer = null;
  #status = INITIAL_STATUS;

  constructor(options) {
    this.#o = {
      WebSocketImpl: globalThis.WebSocket,
      setTimer: (fn, ms) => globalThis.setTimeout(fn, ms),
      clearTimer: (id) => globalThis.clearTimeout(id),
      now: () => Date.now(),
      checkAuth: null, // async () => boolean; false means "sign in again"
      heartbeatMs: 5_000,
      deadAfterMs: 15_000,
      onStatus: () => {},
      onMessage: () => {},
      ...options,
    };
    if (!this.#o.url) throw new TypeError("url is required");
  }

  get status() {
    return this.#status;
  }

  start() {
    if (this.#running) return;
    this.#running = true;
    this.#failures = 0;
    this.#connect();
  }

  stop() {
    this.#running = false;
    this.#retire();
    this.#clearRetry();
    this.#set(STATES.DISCONNECTED, "stopped");
  }

  /** Try again right now (skips the wait). Also restarts a stopped connection. */
  retryNow() {
    if (!this.#running) {
      this.start();
      return;
    }
    if (this.#ws) return; // already trying, or connected
    this.#clearRetry();
    this.#connect();
  }

  // ---- internals ----
  #set(state, reason, retryAt = null) {
    const next = {
      state,
      attempt: this.#failures,
      retryAt,
      reason,
      since: this.#o.now(),
    };
    const prev = this.#status;
    if (
      prev.state === next.state &&
      prev.attempt === next.attempt &&
      prev.reason === next.reason &&
      prev.retryAt === next.retryAt
    ) {
      return;
    }
    this.#status = Object.freeze(next);
    this.#o.onStatus(this.#status);
  }

  #connect() {
    this.#opened = false;
    this.#set(STATES.RECONNECTING, "connecting");
    const gen = ++this.#gen;
    let ws;
    try {
      ws = new this.#o.WebSocketImpl(this.#o.url);
    } catch {
      this.#closed(gen, "closed"); // e.g. a malformed URL
      return;
    }
    this.#ws = ws;
    ws.onopen = () => {
      if (gen !== this.#gen) return;
      this.#opened = true;
      this.#lastActivity = this.#o.now();
      this.#set(STATES.CONNECTED, "open");
      this.#scheduleBeat(gen);
    };
    ws.onmessage = (event) => {
      if (gen !== this.#gen) return;
      this.#lastActivity = this.#o.now();
      if (this.#failures > 0) {
        this.#failures = 0; // it works: the next drop starts from the short delay
        this.#set(STATES.CONNECTED, "open");
      }
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return; // not JSON: ignore, but it still counted as activity
      }
      if (message && message.type === "pong") return;
      this.#o.onMessage(message);
    };
    ws.onerror = () => {}; // a close event always follows
    ws.onclose = () => this.#closed(gen, "closed");
  }

  /** Forget the current socket: its late events no longer reach us. */
  #retire() {
    const ws = this.#ws;
    this.#ws = null;
    this.#gen += 1;
    this.#clearBeat();
    if (ws) {
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
    }
  }

  #closed(gen, reason) {
    if (gen !== this.#gen) return;
    if (!this.#running) return;
    const wasOpen = this.#opened;
    this.#retire();
    const generation = this.#gen;
    const { checkAuth } = this.#o;
    if (wasOpen || !checkAuth) {
      this.#schedule(reason);
      return;
    }
    // Never got in. Channels refuses a visitor who is not signed in with a plain
    // HTTP 403, which looks exactly like a network failure to the browser. Ask
    // the REST API whether we are still signed in before retrying forever.
    this.#set(STATES.RECONNECTING, reason);
    Promise.resolve()
      .then(checkAuth)
      .then(
        (ok) => ok,
        () => true, // cannot tell (network down): keep retrying
      )
      .then((ok) => {
        if (generation !== this.#gen || !this.#running) return;
        if (ok === false) {
          this.#running = false;
          this.#set(STATES.DISCONNECTED, "unauthorized");
        } else {
          this.#schedule(reason);
        }
      });
  }

  #schedule(reason) {
    const delay = backoffDelay(this.#failures);
    this.#failures += 1;
    const retryAt = this.#o.now() + delay;
    this.#set(STATES.RECONNECTING, reason, retryAt);
    this.#clearRetry();
    this.#retryTimer = this.#o.setTimer(() => {
      this.#retryTimer = null;
      if (this.#running) this.#connect();
    }, delay);
  }

  #scheduleBeat(gen) {
    this.#clearBeat();
    this.#beatTimer = this.#o.setTimer(() => {
      this.#beatTimer = null;
      if (gen !== this.#gen || !this.#running || !this.#ws) return;
      if (this.#o.now() - this.#lastActivity > this.#o.deadAfterMs) {
        this.#closed(gen, "timeout"); // silent for too long: replace it
        return;
      }
      if (this.#ws.readyState === OPEN) {
        try {
          this.#ws.send(JSON.stringify({ type: "ping" }));
        } catch {
          /* the close handler will deal with it */
        }
      }
      this.#scheduleBeat(gen);
    }, this.#o.heartbeatMs);
  }

  #clearBeat() {
    if (this.#beatTimer !== null) this.#o.clearTimer(this.#beatTimer);
    this.#beatTimer = null;
  }

  #clearRetry() {
    if (this.#retryTimer !== null) this.#o.clearTimer(this.#retryTimer);
    this.#retryTimer = null;
  }
}
