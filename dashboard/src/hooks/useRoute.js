import { useEffect, useState } from "react";
import { parseRoute } from "../lib/route.js";
import { SITE_ONLY } from "../lib/site.js";

/** The current page, kept in step with the address bar and the back button. */
export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash, SITE_ONLY));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash, SITE_ONLY));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
