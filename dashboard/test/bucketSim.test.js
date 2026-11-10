import assert from "node:assert/strict";
import { test } from "node:test";
import { advance, createBucket, retryAfter, take } from "../src/lib/bucketSim.js";

test("starts full and refuses once empty", () => {
  const b = createBucket(3, 1);
  assert.deepEqual([take(b), take(b), take(b), take(b)], [true, true, true, false]);
  assert.equal(b.tokens, 0);
});

test("refills at the rate and never above capacity", () => {
  const b = createBucket(5, 2);
  for (let i = 0; i < 5; i++) take(b);
  advance(b, 1.5);
  assert.equal(b.tokens, 3);
  advance(b, 100);
  assert.equal(b.tokens, 5);
  advance(b, -4); // time never runs backwards
  assert.equal(b.tokens, 5);
});

test("a request must be able to pay its whole cost", () => {
  const b = createBucket(10, 1);
  assert.equal(take(b, 12), false);
  assert.equal(b.tokens, 10); // a refusal spends nothing
  assert.equal(take(b, 10), true);
});

test("retryAfter says how long until the cost is available", () => {
  const b = createBucket(4, 2);
  assert.equal(retryAfter(b), 0);
  for (let i = 0; i < 4; i++) take(b);
  assert.equal(retryAfter(b), 0.5);
  assert.equal(retryAfter(b, 3), 1.5);
});

test("a burst bigger than capacity is cut off, then recovers", () => {
  const b = createBucket(8, 2);
  const results = Array.from({ length: 12 }, () => take(b));
  assert.equal(results.filter(Boolean).length, 8);
  advance(b, 1);
  assert.equal(take(b) && take(b), true);
  assert.equal(take(b), false);
});

test("bad parameters are refused", () => {
  assert.throws(() => createBucket(0, 1), RangeError);
  assert.throws(() => createBucket(1, 0), RangeError);
});
