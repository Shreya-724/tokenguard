import assert from "node:assert/strict";
import { test } from "node:test";
import { DASHBOARD, HOME, PRIVACY, TERMS, parseRoute, routeHref } from "../src/lib/route.js";

test("each page has its own address", () => {
  assert.equal(parseRoute("#/dashboard"), DASHBOARD);
  assert.equal(parseRoute("#dashboard"), DASHBOARD);
  assert.equal(parseRoute("#/dashboard/"), DASHBOARD);
  assert.equal(parseRoute("#/dashboard?x=1"), DASHBOARD);
  assert.equal(parseRoute("#/privacy"), PRIVACY);
  assert.equal(parseRoute("#/terms"), TERMS);
});

test("everything else is the home page, including in-page anchors", () => {
  for (const hash of ["", "#", "#/", "#install", "#main", "#/nonsense", undefined, null, "#/dashboards", "#/privacy-x"]) {
    assert.equal(parseRoute(hash), HOME, String(hash));
  }
});

test("links round-trip", () => {
  for (const page of [HOME, DASHBOARD, PRIVACY, TERMS]) {
    assert.equal(parseRoute(routeHref(page)), page, page);
  }
});

test("the website build has no dashboard page", () => {
  assert.equal(parseRoute("#/dashboard", true), HOME);
  assert.equal(parseRoute("#/dashboard/", true), HOME);
  assert.equal(parseRoute("#/privacy", true), PRIVACY);
  assert.equal(parseRoute("#/terms", true), TERMS);
  assert.equal(parseRoute("#install", true), HOME);
});

test("the full build keeps the dashboard page", () => {
  assert.equal(parseRoute("#/dashboard", false), DASHBOARD);
  assert.equal(parseRoute("#/dashboard"), DASHBOARD);
});
