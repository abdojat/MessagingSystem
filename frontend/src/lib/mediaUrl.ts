import { getApiBaseUrl } from "@/services/api/runtime";

// Checks for explicit scheme; frontend components and services use it as a shared utility.
function hasExplicitScheme(value: string): boolean {
  return /^[a-z][a-z\d+\-.]*:/i.test(value);
}

const PROTECTED_UPLOAD_PATH_PATTERN =
  /^\/(?:v1\/)?uploads\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/content$/i;

// Resolves api media url; frontend components and services use it as a shared utility.
export function resolveApiMediaUrl(url?: string | null): string | undefined {
  const trimmed = url?.trim();
  // Return early when `!trimmed` because the remaining work is not applicable.
  if (!trimmed) {
    return undefined;
  }

  // Return early when `/^blob:/i.test(trimmed)` because the remaining work is not applicable.
  if (/^blob:/i.test(trimmed)) {
    return trimmed;
  }

  // Return early when `/^https?:\/\//i.test(trimmed)` because the remaining work is not applicable.
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }

  // Return early when `/^\/\//.test(trimmed) || hasExplicitScheme(trimmed)` because the remaining work is not applicable.
  if (/^\/\//.test(trimmed) || hasExplicitScheme(trimmed)) {
    return undefined;
  }

  const normalizedPath = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const apiBaseUrl = getApiBaseUrl();

  // Return early when `/^https?:\/\//i.test(apiBaseUrl)` because the remaining work is not applicable.
  if (/^https?:\/\//i.test(apiBaseUrl)) {
    return `${new URL(apiBaseUrl).origin}${normalizedPath}`;
  }

  return normalizedPath;
}

// Determines whether protected api media url; frontend components and services use it as a shared utility.
export function isProtectedApiMediaUrl(url?: string | null): boolean {
  const resolvedUrl = resolveApiMediaUrl(url);
  // Return early when `!resolvedUrl` because the remaining work is not applicable.
  if (!resolvedUrl) {
    return false;
  }

  // Return early when `resolvedUrl.startsWith("/")` because the remaining work is not applicable.
  if (resolvedUrl.startsWith("/")) {
    return PROTECTED_UPLOAD_PATH_PATTERN.test(resolvedUrl);
  }

  // Return early when `!/^https?:\/\//i.test(resolvedUrl)` because the remaining work is not applicable.
  if (!/^https?:\/\//i.test(resolvedUrl)) {
    return false;
  }

  // Attempt this operation and recover from expected failures in the catch block below.
  try {
    const parsed = new URL(resolvedUrl);
    const apiBaseUrl = getApiBaseUrl();
    // Choose the appropriate path based on whether `/^https?:\/\//i.test(apiBaseUrl)` is true.
    if (/^https?:\/\//i.test(apiBaseUrl)) {
      const apiOrigin = new URL(apiBaseUrl).origin;
      // Return early when `parsed.origin !== apiOrigin` because the remaining work is not applicable.
      if (parsed.origin !== apiOrigin) {
        return false;
      }
    // Otherwise, resolve relative media URLs against the browser origin.
    } else if (typeof window !== "undefined") {
      // Return early when `parsed.origin !== window.location.origin` because the remaining work is not applicable.
      if (parsed.origin !== window.location.origin) {
        return false;
      }
    // Handle the fallback path when the preceding condition is false.
    } else {
      return false;
    }
    return PROTECTED_UPLOAD_PATH_PATTERN.test(parsed.pathname);
  // Recover from the attempted operation by applying this error-handling path.
  } catch {
    return false;
  }
}
