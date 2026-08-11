import { useAuthStore } from "@/store/authStore";
import { getApiBaseUrl } from "@/services/api/runtime";
import {
  browserRefreshRequest,
  type BrowserAccessTokenResponse,
} from "@/services/auth/browser-session";

export class ApiError extends Error {
  constructor(
    public status: number,
    public data: unknown,
  ) {
    const message =
      data && typeof data === "object" && "message" in data
        ? String((data as { message: unknown }).message)
        : `API Error: ${status}`;
    super(message);
  }
}

// A shared refresh promise prevents parallel 401 responses from rotating the
// same refresh token multiple times.
let refreshPromise: Promise<string> | null = null;

async function readApiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = { message: response.statusText };
    }
    throw new ApiError(response.status, data);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

export async function refreshAccessToken(baseUrl: string): Promise<string> {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const refreshRes = await browserRefreshRequest(baseUrl);

      if (!refreshRes.ok) {
        throw new Error("Refresh failed");
      }

      const data = (await refreshRes.json()) as BrowserAccessTokenResponse;
      useAuthStore.getState().setAccessToken(data.access_token);
      return data.access_token;
    } catch (_error) {
      useAuthStore.getState().clearAuth();
      throw new ApiError(401, { message: "Session expired" });
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  const token = useAuthStore.getState().accessToken;
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers, credentials: "include" });

  if (response.status === 401 && token) {
    // A 401 usually means the short-lived access token expired. Refresh once,
    // then replay only this request with the new bearer token.
    const newToken = await refreshAccessToken(baseUrl);
    const retryHeaders = new Headers(headers);
    retryHeaders.set("Authorization", `Bearer ${newToken}`);
    const retryResponse = await fetch(url, { ...options, headers: retryHeaders, credentials: "include" });
    return readApiResponse<T>(retryResponse);
  }

  return readApiResponse<T>(response);
}
