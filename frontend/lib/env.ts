const rawApiBase = process.env.NEXT_PUBLIC_API_BASE_URL;

function normalizeApiBase(input: string) {
  const fallback = "http://localhost:8000";
  const trimmed = input.trim().replace(/\/+$/, "");
  const candidate = trimmed || fallback;

  try {
    const url = new URL(candidate);
    const normalizedPath = url.pathname.replace(/\/+$/, "");
    const hasVersionedPath = normalizedPath === "/v1";
    const basePath = hasVersionedPath ? "" : normalizedPath;
    const origin = `${url.protocol}//${url.host}`;

    return {
      apiBaseUrl: `${origin}${basePath}`,
      apiV1BaseUrl: `${origin}${basePath}/v1`,
    };
  } catch {
    return {
      apiBaseUrl: candidate.endsWith("/v1") ? candidate.slice(0, -3) : candidate,
      apiV1BaseUrl: candidate.endsWith("/v1") ? candidate : `${candidate}/v1`,
    };
  }
}

const normalized = normalizeApiBase(rawApiBase || "http://localhost:8000");

export const API_BASE_URL = normalized.apiBaseUrl;
export const API_V1_BASE_URL = normalized.apiV1BaseUrl;

export function resolveApiUrl(pathOrUrl: string | null | undefined): string | null {
  if (!pathOrUrl) return null;
  const value = pathOrUrl.trim();
  if (!value) return null;

  if (/^(https?:|data:|blob:)/i.test(value)) {
    return value;
  }

  try {
    return new URL(value, API_BASE_URL).toString();
  } catch {
    return value;
  }
}

export function toWebSocketUrl(httpBase: string) {
  const normalized = httpBase.replace(/\/+$/, "");
  if (normalized.startsWith("https://")) {
    return normalized.replace("https://", "wss://") + "/v1/ws";
  }
  if (normalized.startsWith("http://")) {
    return normalized.replace("http://", "ws://") + "/v1/ws";
  }
  throw new Error("NEXT_PUBLIC_API_BASE_URL must start with http:// or https://");
}
