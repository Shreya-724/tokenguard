import assert from "node:assert/strict";
import { test } from "node:test";
import { BACKOFF_MAX_MS, backoffDelay } from "../src/lib/backoff.js";

test("delays double from 0.5 s and stop at the 10 s cap", () => {
  const delays = [0, 1, 2, 3, 4, 5, 6, 7].map((n) => backoffDelay(n));
  assert.deepEqual(delays, [500, 1000, 2000, 4000, 8000, 10000, 10000, 10000]);
});

test("the cap holds however many attempts have failed", () => {
  assert.equal(backoffDelay(50), BACKOFF_MAX_MS);
  assert.equal(backoffDelay(10_000), BACKOFF_MAX_MS);
});

test("there is no jitter: the same input always gives the same delay", () => {
  assert.equal(backoffDelay(3), backoffDelay(3));
});

test("base and cap can be overridden", () => {
  assert.equal(backoffDelay(2, 100, 1000), 400);
  assert.equal(backoffDelay(9, 100, 1000), 1000);
});

test("nonsense input is rejected", () => {
  for (const bad of [-1, 1.5, NaN, "2", undefined]) {
    assert.throws(() => backoffDelay(bad), RangeError);
  }
});
