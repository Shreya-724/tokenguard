import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { FeedConnection, INITIAL_STATUS, STATES } from "../src/lib/connection.js";
import { FakeClock, FakeSocket, settle } from "./helpers.js";

let clock;
let statuses;
let messages;

beforeEach(() => {
  FakeSocket.reset();
  clock = new FakeClock();
  statuses = [];
  messages = [];
});

function make(extra = {}) {
  return new FeedConnection({
    url: "ws://test/ws/tokenguard/stats/",
    WebSocketImpl: FakeSocket,
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    now: () => clock.now,
    onStatus: (s) => statuses.push(s),
    onMessage: (m) => messages.push(m),
    ...extra,
  });
}

const states = () => statuses.map((s) => s.state);

// ---- the three states ----
test("it starts disconnected and does nothing until started", () => {
  const c = make();
  assert.equal(c.status, INITIAL_STATUS);
  assert.equal(c.status.state, STATES.DISCONNECTED);
  assert.equal(FakeSocket.instances.length, 0);
});

test("start: reconnecting (attempt 0) while connecting, connected once open", () => {
  const c = make();
  c.start();
  assert.equal(c.status.state, STATES.RECONNECTING);
  assert.equal(c.status.attempt, 0);
  assert.equal(c.status.reason, "connecting");
  assert.equal(FakeSocket.last.url, "ws://test/ws/tokenguard/stats/");
  FakeSocket.last.open();
  assert.equal(c.status.state, STATES.CONNECTED);
});

test("stop: disconnected, socket closed, nothing left to fire", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  const socket = FakeSocket.last;
  c.stop();
  assert.equal(c.status.state, STATES.DISCONNECTED);
  assert.equal(c.status.reason, "stopped");
  assert.ok(socket.closed);
  assert.equal(clock.pending, 0);
  clock.advance(60_000);
  assert.equal(FakeSocket.instances.length, 1); // no reconnect after stop
});

test("starting twice does not open two sockets", () => {
  const c = make();
  c.start();
  c.start();
  assert.equal(FakeSocket.instances.length, 1);
});

test("statuses are frozen and only reported when they change", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  FakeSocket.last.message({ type: "stats" }); // changes nothing
  FakeSocket.last.message({ type: "stats" });
  assert.deepEqual(states(), ["reconnecting", "connected"]);
  assert.ok(Object.isFrozen(c.status));
});

// ---- backoff ----
test("a dropped socket is retried after 0.5 s, then waits longer each time", () => {
  const c = make();
  c.start();
  const waits = [];
  for (let i = 0; i < 8; i++) {
    FakeSocket.last.drop(); // never opens: the attempt fails
    assert.equal(c.status.state, STATES.RECONNECTING);
    waits.push(c.status.retryAt - clock.now);
    assert.equal(c.status.attempt, i + 1);
    clock.advance(c.status.retryAt - clock.now);
  }
  assert.deepEqual(waits, [500, 1000, 2000, 4000, 8000, 10000, 10000, 10000]);
  assert.equal(FakeSocket.instances.length, 9);
});

test("nothing happens before the delay is up", () => {
  const c = make();
  c.start();
  FakeSocket.last.drop();
  clock.advance(499);
  assert.equal(FakeSocket.instances.length, 1);
  clock.advance(1);
  assert.equal(FakeSocket.instances.length, 2);
  assert.equal(c.status.reason, "connecting");
});

test("a socket that opens but never delivers does not reset the backoff", () => {
  const c = make();
  c.start();
  FakeSocket.last.drop();
  clock.advance(500);
  FakeSocket.last.open(); // opened, then dies without a single frame
  FakeSocket.last.drop();
  assert.equal(c.status.retryAt - clock.now, 1000);
});

test("the first frame proves it works and resets the backoff", () => {
  const c = make();
  c.start();
  FakeSocket.last.drop();
  clock.advance(500);
  FakeSocket.last.drop();
  clock.advance(1000);
  FakeSocket.last.open();
  assert.equal(c.status.attempt, 2);
  FakeSocket.last.message({ type: "stats" });
  assert.equal(c.status.attempt, 0);
  FakeSocket.last.drop();
  assert.equal(c.status.retryAt - clock.now, 500);
});

test("retryNow skips the wait", () => {
  const c = make();
  c.start();
  FakeSocket.last.drop();
  c.retryNow();
  assert.equal(FakeSocket.instances.length, 2);
  assert.equal(clock.pending, 0);
  assert.equal(c.status.reason, "connecting");
});

test("retryNow does nothing while connected", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  c.retryNow();
  assert.equal(FakeSocket.instances.length, 1);
});

test("a WebSocket constructor that throws is treated as a failed attempt", () => {
  class Throws {
    constructor() {
      throw new SyntaxError("bad url");
    }
  }
  const c = make({ WebSocketImpl: Throws });
  c.start();
  assert.equal(c.status.state, STATES.RECONNECTING);
  assert.equal(c.status.retryAt - clock.now, 500);
});

// ---- messages ----
test("frames reach onMessage; pongs and junk do not", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  FakeSocket.last.message({ type: "stats", n: 1 });
  FakeSocket.last.message({ type: "pong" });
  FakeSocket.last.raw("not json at all");
  FakeSocket.last.message({ type: "error", error: "Redis is unavailable" });
  assert.deepEqual(messages, [
    { type: "stats", n: 1 },
    { type: "error", error: "Redis is unavailable" },
  ]);
  assert.equal(c.status.state, STATES.CONNECTED);
});

// ---- heartbeat and dead connections ----
test("it pings every 5 seconds while connected", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  clock.advance(5_000);
  clock.advance(5_000);
  assert.deepEqual(FakeSocket.last.sent, [{ type: "ping" }, { type: "ping" }]);
  void c;
});

test("a socket that goes silent is declared dead and replaced", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  const dead = FakeSocket.last;
  clock.advance(20_000); // the 20 s mark checks the 15 s limit
  assert.equal(c.status.state, STATES.RECONNECTING);
  assert.equal(c.status.reason, "timeout");
  assert.ok(dead.closed);
  dead.message({ type: "stats" }); // late frames from the dead socket are ignored
  dead.open();
  assert.equal(c.status.state, STATES.RECONNECTING);
  assert.deepEqual(messages, []);
  clock.advance(500);
  assert.equal(FakeSocket.instances.length, 2);
});

test("frames keep the connection alive, even with no pongs", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  for (let i = 0; i < 120; i++) {
    clock.advance(1_000);
    FakeSocket.last.message({ type: "stats" });
  }
  assert.equal(c.status.state, STATES.CONNECTED);
  assert.equal(FakeSocket.instances.length, 1);
});

test("pongs alone also keep it alive (feed stopped, socket fine)", () => {
  const c = make();
  c.start();
  FakeSocket.last.open();
  for (let i = 0; i < 12; i++) {
    clock.advance(5_000);
    FakeSocket.last.message({ type: "pong" });
  }
  assert.equal(c.status.state, STATES.CONNECTED);
});

test("late events from a replaced socket cannot change the state", () => {
  const c = make();
  c.start();
  const first = FakeSocket.last;
  first.drop();
  clock.advance(500);
  const second = FakeSocket.last;
  second.open();
  first.onopen?.();
  first.onclose?.();
  assert.equal(c.status.state, STATES.CONNECTED);
  assert.equal(FakeSocket.instances.length, 2);
});

// ---- being signed out ----
test("refused at the door and no longer signed in: stop, do not retry forever", async () => {
  const c = make({ checkAuth: async () => false });
  c.start();
  FakeSocket.last.drop(); // never opened: Channels answered 403
  await settle();
  assert.equal(c.status.state, STATES.DISCONNECTED);
  assert.equal(c.status.reason, "unauthorized");
  clock.advance(60_000);
  assert.equal(FakeSocket.instances.length, 1);
});

test("refused but still signed in: it was the network, so retry", async () => {
  const c = make({ checkAuth: async () => true });
  c.start();
  FakeSocket.last.drop();
  await settle();
  assert.equal(c.status.state, STATES.RECONNECTING);
  assert.equal(c.status.retryAt - clock.now, 500);
  clock.advance(500);
  assert.equal(FakeSocket.instances.length, 2);
});

test("if the auth check itself fails, keep retrying", async () => {
  const c = make({
    checkAuth: async () => {
      throw new Error("offline");
    },
  });
  c.start();
  FakeSocket.last.drop();
  await settle();
  assert.equal(c.status.state, STATES.RECONNECTING);
  assert.equal(c.status.retryAt - clock.now, 500);
});

test("a drop after a good connection does not trigger an auth check", async () => {
  let asked = 0;
  const c = make({
    checkAuth: async () => {
      asked += 1;
      return false;
    },
  });
  c.start();
  FakeSocket.last.open();
  FakeSocket.last.drop();
  await settle();
  assert.equal(asked, 0);
  assert.equal(c.status.state, STATES.RECONNECTING);
});

test("stopping while the auth check is pending ignores its answer", async () => {
  const c = make({ checkAuth: async () => true });
  c.start();
  FakeSocket.last.drop();
  c.stop();
  await settle();
  assert.equal(c.status.reason, "stopped");
  clock.advance(60_000);
  assert.equal(FakeSocket.instances.length, 1);
});

test("after 'unauthorized' it can be started again (after signing in)", async () => {
  let signedIn = false;
  const c = make({ checkAuth: async () => signedIn });
  c.start();
  FakeSocket.last.drop();
  await settle();
  assert.equal(c.status.reason, "unauthorized");
  signedIn = true;
  c.start();
  assert.equal(FakeSocket.instances.length, 2);
  assert.equal(c.status.attempt, 0);
  FakeSocket.last.open();
  assert.equal(c.status.state, STATES.CONNECTED);
});

test("a url is required", () => {
  assert.throws(() => new FeedConnection({}), TypeError);
});
