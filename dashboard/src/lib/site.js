// True in the static website build (GitHub Pages), which is built with
// VITE_SITE_ONLY=1. That build has the home, privacy and terms pages only: there is
// no Django behind it, so the dashboard would have nothing to sign in to.
export const SITE_ONLY = import.meta.env?.VITE_SITE_ONLY === "1";
