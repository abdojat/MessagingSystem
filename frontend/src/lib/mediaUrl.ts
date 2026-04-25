import { getApiBaseUrl } from "@/services/api/runtime";

function hasExplicitScheme(value: string): boolean {
  return /^[a-z][a-z\d+\-.]*:/i.test(value);
}

export function resolveApiMediaUrl(url?: string | null): string | undefined {
  const trimmed = url?.trim();
  if (!trimmed) {
    return undefined;
  }

  // Keep absolute/protocol-relative/data/blob links untouched.
  if (
    /^(https?:)?\/\//i.test(trimmed) ||
    hasExplicitScheme(trimmed) ||
    trimmed.startsWith("data:") ||
    trimmed.startsWith("blob:")
  ) {
    return trimmed;
  }

  const normalizedPath = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const apiBaseUrl = getApiBaseUrl();

  if (/^https?:\/\//i.test(apiBaseUrl)) {
    return `${new URL(apiBaseUrl).origin}${normalizedPath}`;
  }

  return normalizedPath;
}
