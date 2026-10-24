import assert from "node:assert/strict";
import { test } from "node:test";
import { describeChange, formFromRule, isChange, parseRuleForm } from "../src/lib/rules.js";

const rule = {
  scope: "default",
  budget: false,
  effective: { capacity: 60, refill_rate: 1, algorithm: "token_bucket" },
};

test("the form starts from the effective values, as text", () => {
  assert.deepEqual(formFromRule(rule), {
    capacity: "60",
    refill_rate: "1",
    algorithm: "token_bucket",
  });
});

test("a valid form becomes numbers for the API", () => {
  const r = parseRuleForm({ capacity: " 100 ", refill_rate: "2.5", algorithm: "fixed_window" }, rule);
  assert.equal(r.ok, true);
  assert.deepEqual(r.body, { capacity: 100, refill_rate: 2.5, algorithm: "fixed_window" });
  assert.deepEqual(r.errors, {});
});

test("bad numbers are rejected with a message per field", () => {
  for (const bad of ["", "  ", "abc", "0", "-3", "Infinity", "NaN"]) {
    const r = parseRuleForm({ capacity: bad, refill_rate: "1", algorithm: "token_bucket" }, rule);
    assert.equal(r.ok, false, `capacity ${JSON.stringify(bad)}`);
    assert.ok(r.errors.capacity);
    assert.equal(r.body, null);
  }
});

test("every problem is reported at once", () => {
  const r = parseRuleForm({ capacity: "x", refill_rate: "", algorithm: "leaky" }, rule);
  assert.deepEqual(Object.keys(r.errors).sort(), ["algorithm", "capacity", "refill_rate"]);
});

test("a budgeted rule only takes the token bucket", () => {
  const budgeted = { ...rule, budget: true };
  const bad = parseRuleForm({ capacity: "5", refill_rate: "1", algorithm: "sliding_window" }, budgeted);
  assert.match(bad.errors.algorithm, /token_bucket/);
  assert.equal(parseRuleForm({ capacity: "5", refill_rate: "1", algorithm: "token_bucket" }, budgeted).ok, true);
});

test("a change is described by what differs", () => {
  const e = rule.effective;
  assert.equal(describeChange(e, { capacity: 100, refill_rate: 1, algorithm: "token_bucket" }), "capacity 60→100");
  assert.equal(
    describeChange(e, { capacity: 100, refill_rate: 5, algorithm: "sliding_window" }),
    "capacity 60→100 · refill/s 1→5 · token_bucket→sliding_window",
  );
  assert.equal(describeChange(e, { ...e }), "no change");
  assert.equal(isChange(e, { ...e }), false);
  assert.equal(isChange(e, { ...e, capacity: 61 }), true);
});
