import assert from "node:assert/strict";
import test from "node:test";

import { autoWatchKey } from "../src/lib/watch.js";

const rows = (...keys) => keys.map((key) => ({ key }));

test("autoWatchKey picks the top consumer when nothing is watched", () => {
  assert.equal(autoWatchKey(null, true, rows("a", "b")), "a");
});

test("autoWatchKey stays on its key while that key is still listed, even if it is not first", () => {
  assert.equal(autoWatchKey("b", true, rows("a", "b")), "b");
});

test("autoWatchKey moves on when its key falls off the list", () => {
  assert.equal(autoWatchKey("gone", true, rows("a", "b")), "a");
});

test("autoWatchKey leaves a key the user chose alone", () => {
  assert.equal(autoWatchKey("mine", false, rows("a", "b")), "mine");
  assert.equal(autoWatchKey(null, false, rows("a")), null);
});

test("autoWatchKey keeps the current key when there are no consumers yet", () => {
  assert.equal(autoWatchKey(null, true, []), null);
  assert.equal(autoWatchKey(null, true, undefined), null);
  assert.equal(autoWatchKey("a", true, []), "a");
});
