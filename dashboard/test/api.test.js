import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, encodePath, feedUrl, getCookie, request } from "../src/lib/api.js";

function fakeFetch(status, body, calls = []) {
  return async (url, init) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => {
        if (body === undefined) throw new SyntaxError("no body");
        return body;
      },
    };
  };
}

test("cookies are read by name, decoded, and missing ones are null", () => {
  const jar = "a=1; csrftoken=abc%20def; b=2";
  assert.equal(getCookie("csrftoken", jar), "abc def");
  assert.equal(getCookie("a", jar), "1");
  assert.equal(getCookie("nope", jar), null);
  assert.equal(getCookie("x", ""), null);
  assert.equal(getCookie("t", "t=a=b"), "a=b");
});

test("paths keep colons readable but encode everything else", () => {
  assert.equal(encodePath("default:ip:127.0.0.1"), "default:ip:127.0.0.1");
  assert.equal(encodePath("^/login/"), "%5E%2Flogin%2F");
  assert.equal(encodePath("a b?c#d"), "a%20b%3Fc%23d");
});

test("a GET sends the session cookie and no CSRF header", async () => {
  const calls = [];
  const data = await request("/x/", { fetchImpl: fakeFetch(200, { ok: 1 }, calls), cookie: "csrftoken=t" });
  assert.deepEqual(data, { ok: 1 });
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(calls[0].init.headers["X-CSRFToken"], undefined);
  assert.equal(calls[0].init.body, undefined);
});

test("changes send the CSRF token and a JSON body", async () => {
  const calls = [];
  await request("/x/", {
    method: "PUT",
    body: { capacity: 5 },
    fetchImpl: fakeFetch(200, {}, calls),
    cookie: "csrftoken=tok123",
  });
  const { init } = calls[0];
  assert.equal(init.method, "PUT");
  assert.equal(init.headers["X-CSRFToken"], "tok123");
  assert.equal(init.headers["Content-Type"], "application/json");
  assert.equal(init.body, '{"capacity":5}');
});

test("an error response becomes an ApiError with the server's message", async () => {
  await assert.rejects(
    request("/x/", { fetchImpl: fakeFetch(400, { error: "capacity must be positive" }) }),
    (e) => e instanceof ApiError && e.status === 400 && e.message === "capacity must be positive",
  );
});

test("DRF-style {detail} messages are used too, and a bare status as a last resort", async () => {
  await assert.rejects(
    request("/x/", { fetchImpl: fakeFetch(403, { detail: "Authentication credentials were not provided." }) }),
    (e) => e.message.startsWith("Authentication") && e.unauthorized === true,
  );
  await assert.rejects(request("/x/", { fetchImpl: fakeFetch(502, undefined) }), (e) => e.message === "HTTP 502");
});

test("401 and 403 mean 'sign in again'; other errors do not", async () => {
  for (const [status, expected] of [[401, true], [403, true], [404, false], [503, false]]) {
    await assert.rejects(request("/x/", { fetchImpl: fakeFetch(status, {}) }), (e) => e.unauthorized === expected);
  }
});

test("an unreachable server is an ApiError with status 0", async () => {
  const failing = async () => {
    throw new TypeError("Failed to fetch");
  };
  await assert.rejects(request("/x/", { fetchImpl: failing }), (e) => e.status === 0 && !e.unauthorized);
});

test("the feed URL follows the page: ws for http, wss for https", () => {
  assert.equal(feedUrl({ protocol: "http:", host: "localhost:5173" }), "ws://localhost:5173/ws/tokenguard/stats/");
  assert.equal(feedUrl({ protocol: "https:", host: "dash.example.com" }), "wss://dash.example.com/ws/tokenguard/stats/");
});
