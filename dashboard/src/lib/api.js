// REST calls to the tokenguard staff API. Same-origin (the dev server proxies
// to Django), session cookie for auth, CSRF token from its cookie on changes.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status; // 0 means the request never got an answer
  }
  get unauthorized() {
    return this.status === 401 || this.status === 403;
  }
}

export function getCookie(name, cookieString = globalThis.document?.cookie ?? "") {
  for (const part of cookieString.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

/** encodeURIComponent, but keep ":" readable: keys look like scope:identity. */
export function encodePath(value) {
  return encodeURIComponent(value).replace(/%3A/gi, ":");
}

export async function request(path, { method = "GET", body, fetchImpl, cookie } = {}) {
  const doFetch = fetchImpl ?? globalThis.fetch.bind(globalThis);
  const headers = { Accept: "application/json" };
  const init = { method, headers, credentials: "same-origin" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (method !== "GET") {
    const token = getCookie("csrftoken", cookie);
    if (token) headers["X-CSRFToken"] = token;
  }
  let response;
  try {
    response = await doFetch(path, init);
  } catch {
    throw new ApiError(0, "cannot reach the server");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* an empty or non-JSON body */
  }
  if (!response.ok) {
    const message =
      (data && (data.error || data.detail)) || `HTTP ${response.status}`;
    throw new ApiError(response.status, String(message));
  }
  return data;
}

const BASE = "/tokenguard";

export const api = {
  session: () => request(`${BASE}/session/`),
  login: (username, password) =>
    request(`${BASE}/login/`, { method: "POST", body: { username, password } }),
  logout: () => request(`${BASE}/logout/`, { method: "POST", body: {} }),
  rules: () => request(`${BASE}/rules/`),
  putRule: (scope, body) =>
    request(`${BASE}/rules/${encodePath(scope)}/`, { method: "PUT", body }),
  resetRule: (scope) =>
    request(`${BASE}/rules/${encodePath(scope)}/`, { method: "DELETE" }),
  bucket: (key) => request(`${BASE}/buckets/${encodePath(key)}/`),
};

/** ws://host/ws/tokenguard/stats/ (wss on https), from the page's location. */
export function feedUrl(location = globalThis.location) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/tokenguard/stats/`;
}
