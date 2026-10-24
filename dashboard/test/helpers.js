// Test doubles: a WebSocket you can drive by hand, and a clock you can wind.

export class FakeSocket {
  static instances = [];
  static reset() {
    FakeSocket.instances = [];
  }
  static get last() {
    return FakeSocket.instances[FakeSocket.instances.length - 1];
  }
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.closed = false;
    FakeSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  // -- the server's side of the conversation --
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(object) {
    this.onmessage?.({ data: JSON.stringify(object) });
  }
  raw(text) {
    this.onmessage?.({ data: text });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

export class FakeClock {
  constructor(start = 1_000_000) {
    this.now = start;
    this.timers = new Map();
    this.nextId = 1;
  }
  setTimer = (fn, ms) => {
    const id = this.nextId++;
    this.timers.set(id, { at: this.now + ms, fn });
    return id;
  };
  clearTimer = (id) => {
    this.timers.delete(id);
  };
  get pending() {
    return this.timers.size;
  }
  advance(ms) {
    const target = this.now + ms;
    for (;;) {
      let nextId = null;
      for (const [id, t] of this.timers) {
        if (t.at <= target && (nextId === null || t.at < this.timers.get(nextId).at)) {
          nextId = id;
        }
      }
      if (nextId === null) break;
      const { at, fn } = this.timers.get(nextId);
      this.timers.delete(nextId);
      this.now = Math.max(this.now, at);
      fn();
    }
    this.now = target;
  }
}

/** Let promise callbacks run (the connection's auth check is async). */
export const settle = () => new Promise((resolve) => setImmediate(resolve));
