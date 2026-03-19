const API_VERSION_PREFIX = "/v1";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function ensureApiPrefix(pathname: string): string {
  const normalizedPath = trimTrailingSlash(pathname || "");
  if (!normalizedPath || normalizedPath === "/") {
    return API_VERSION_PREFIX;
  }
  return normalizedPath.endsWith(API_VERSION_PREFIX)
    ? normalizedPath
    : `${normalizedPath}${API_VERSION_PREFIX}`;
}

export function getApiBaseUrl(): string {
  const configuredBase = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL || "");

  if (!configuredBase) {
    return API_VERSION_PREFIX;
  }

  if (/^https?:\/\//i.test(configuredBase)) {
    const url = new URL(configuredBase);
    url.pathname = ensureApiPrefix(url.pathname);
    return trimTrailingSlash(url.toString());
  }

  return ensureApiPrefix(configuredBase.startsWith("/") ? configuredBase : `/${configuredBase}`);
}

export function getWsUrl(accessToken: string): string {
  const apiBaseUrl = getApiBaseUrl();
  const wsBaseUrl = /^https?:\/\//i.test(apiBaseUrl)
    ? apiBaseUrl.replace(/^http/i, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${apiBaseUrl}`;
  const wsUrl = new URL(`${trimTrailingSlash(wsBaseUrl)}/ws`);
  wsUrl.searchParams.set("token", accessToken);
  return wsUrl.toString();
}
