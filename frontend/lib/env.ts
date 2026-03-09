const rawApiBase = process.env.NEXT_PUBLIC_API_BASE_URL;

export const API_BASE_URL = (rawApiBase || "http://localhost:8000").replace(/\/+$/, "");
export const API_V1_BASE_URL = `${API_BASE_URL}/v1`;

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
