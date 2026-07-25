import { getApiBaseUrl } from "@/services/api/runtime";

function hasExplicitScheme(value: string): boolean {
  return /^[a-z][a-z\d+\-.]*:/i.test(value);
}

const PROTECTED_UPLOAD_PATH_PATTERN =
  /^\/(?:v1\/)?uploads\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/content$/i;

export function resolveApiMediaUrl(url?: string | null): string | undefined {
  const trimmed = url?.trim();
  if (!trimmed) {
    return undefined;
  }

  if (/^blob:/i.test(trimmed)) {
    return trimmed;
  }

  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }

  if (/^\/\//.test(trimmed) || hasExplicitScheme(trimmed)) {
    return undefined;
  }

  const normalizedPath = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const apiBaseUrl = getApiBaseUrl();

  if (/^https?:\/\//i.test(apiBaseUrl)) {
    return `${new URL(apiBaseUrl).origin}${normalizedPath}`;
  }

  return normalizedPath;
}

export function isProtectedApiMediaUrl(url?: string | null): boolean {
  const resolvedUrl = resolveApiMediaUrl(url);
  if (!resolvedUrl) {
    return false;
  }

  if (resolvedUrl.startsWith("/")) {
    return PROTECTED_UPLOAD_PATH_PATTERN.test(resolvedUrl);
  }

  if (!/^https?:\/\//i.test(resolvedUrl)) {
    return false;
  }

  try {
    const parsed = new URL(resolvedUrl);
    const apiBaseUrl = getApiBaseUrl();
    if (/^https?:\/\//i.test(apiBaseUrl)) {
      const apiOrigin = new URL(apiBaseUrl).origin;
      if (parsed.origin !== apiOrigin) {
        return false;
      }
    } else if (typeof window !== "undefined") {
      if (parsed.origin !== window.location.origin) {
        return false;
      }
    } else {
      return false;
    }
    return PROTECTED_UPLOAD_PATH_PATTERN.test(parsed.pathname);
  } catch {
    return false;
  }
}
