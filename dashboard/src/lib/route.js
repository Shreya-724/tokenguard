// Pages, chosen by the part of the address after "#": "#/" is the home page,
// "#/dashboard" the dashboard, "#/privacy" and "#/terms" the two policy pages.
// A hash needs no server setup (nginx, Vite and Django all just serve index.html),
// and anything unknown falls back to home, so in-page anchors such as "#install"
// keep working.

export const HOME = "home";
export const DASHBOARD = "dashboard";
export const PRIVACY = "privacy";
export const TERMS = "terms";

const PAGES = new Set([DASHBOARD, PRIVACY, TERMS]);

export function parseRoute(hash) {
  const path = String(hash ?? "")
    .replace(/^#\/?/, "")
    .split(/[?#]/)[0]
    .replace(/\/+$/, "");
  return PAGES.has(path) ? path : HOME;
}

export function routeHref(route) {
  return PAGES.has(route) ? `#/${route}` : "#/";
}
