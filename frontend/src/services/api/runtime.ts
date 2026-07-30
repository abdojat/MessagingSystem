const API_VERSION_PREFIX = "/v1";

// Trims trailing slash; hooks and components use it to communicate with the backend API.
function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

// Ensures api prefix; hooks and components use it to communicate with the backend API.
function ensureApiPrefix(pathname: string): string {
  const normalizedPath = trimTrailingSlash(pathname || "");
  // Return early when `!normalizedPath || normalizedPath === "/"` because the remaining work is not applicable.
  if (!normalizedPath || normalizedPath === "/") {
    return API_VERSION_PREFIX;
  }
  return normalizedPath.endsWith(API_VERSION_PREFIX)
    ? normalizedPath
    : `${normalizedPath}${API_VERSION_PREFIX}`;
}

// Retrieves api base url; hooks and components use it to communicate with the backend API.
export function getApiBaseUrl(): string {
  const configuredBase = trimTrailingSlash(process.env.NEXT_PUBLIC_API_BASE_URL || "");

  // Return early when `!configuredBase` because the remaining work is not applicable.
  if (!configuredBase) {
    return API_VERSION_PREFIX;
  }

  // Run this conditional step only when `/^https?:\/\//i.test(configuredBase)` is true.
  if (/^https?:\/\//i.test(configuredBase)) {
    const url = new URL(configuredBase);
    url.pathname = ensureApiPrefix(url.pathname);
    return trimTrailingSlash(url.toString());
  }

  return ensureApiPrefix(
    configuredBase.startsWith("/") ? configuredBase : `/${configuredBase}`,
  );
}

// Retrieves ws url; hooks and components use it to communicate with the backend API.
export function getWsUrl(accessToken: string): string {
  const apiBaseUrl = getApiBaseUrl();
  const wsBaseUrl = /^https?:\/\//i.test(apiBaseUrl)
    ? apiBaseUrl.replace(/^http/i, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${apiBaseUrl}`;
  const wsUrl = new URL(`${trimTrailingSlash(wsBaseUrl)}/ws`);
  wsUrl.searchParams.set("token", accessToken);
  return wsUrl.toString();
}

