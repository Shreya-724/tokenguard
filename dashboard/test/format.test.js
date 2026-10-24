import assert from "node:assert/strict";
import { test } from "node:test";
import { fmtAge, fmtClock, fmtDuration, fmtInt, fmtNum, fmtPct } from "../src/lib/format.js";

test("clock times are zero-padded", () => {
  assert.equal(fmtClock(0, { utc: true }), "00:00:00");
  assert.equal(fmtClock(3661, { utc: true }), "01:01:01");
  assert.equal(fmtClock(86399, { utc: true }), "23:59:59");
});

test("a missing time is a placeholder, not NaN", () => {
  assert.equal(fmtClock(null), "--:--:--");
  assert.equal(fmtClock(NaN), "--:--:--");
});

test("integers get thousands separators", () => {
  assert.equal(fmtInt(1234567), "1,234,567");
  assert.equal(fmtInt(0), "0");
  assert.equal(fmtInt(12.6), "13");
  assert.equal(fmtInt(null), "—");
});

test("numbers drop trailing zeros", () => {
  assert.equal(fmtNum(12.5), "12.5");
  assert.equal(fmtNum(100), "100");
  assert.equal(fmtNum(0.001), "0");
  assert.equal(fmtNum(0.001, 3), "0.001");
  assert.equal(fmtNum(Infinity), "—");
});

test("percentages", () => {
  assert.equal(fmtPct(0.4), "40.0%");
  assert.equal(fmtPct(1 / 3, 0), "33%");
  assert.equal(fmtPct(0), "0.0%");
  assert.equal(fmtPct(undefined), "—");
});

test("durations", () => {
  assert.equal(fmtDuration(0), "0s");
  assert.equal(fmtDuration(45.4), "45s");
  assert.equal(fmtDuration(125), "2m05s");
  assert.equal(fmtDuration(3700), "1h01m");
  assert.equal(fmtDuration(Infinity), "—");
  assert.equal(fmtDuration(-5), "0s");
});

test("ages", () => {
  assert.equal(fmtAge(200), "just now");
  assert.equal(fmtAge(4000), "4s ago");
  assert.equal(fmtAge(null), "never");
});
