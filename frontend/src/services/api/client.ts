import { useAuthStore } from "@/store/authStore";
import { getApiBaseUrl } from "@/services/api/runtime";

class ApiError extends Error {
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

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

// Responds to refreshed; hooks and components use it to communicate with the backend API.
function onRefreshed(token: string) {
  refreshSubscribers.forEach((callback) => callback(token));
  refreshSubscribers = [];
}

// Adds refresh subscriber; hooks and components use it to communicate with the backend API.
function addRefreshSubscriber(callback: (token: string) => void) {
  refreshSubscribers.push(callback);
}

// Sends authenticated requests and coordinates token refresh; hooks and components use it to communicate with the backend API.
export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  const token = useAuthStore.getState().accessToken;
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  // Run this conditional step only when `token` is true.
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers });

  // Run this conditional step only when `response.status === 401` is true.
  if (response.status === 401) {
    const refreshToken = localStorage.getItem("chat_refresh_token");

    // Run this conditional step only when `!refreshToken` is true.
    if (!refreshToken) {
      useAuthStore.getState().clearAuth();
      throw new ApiError(401, { message: "Unauthorized" });
    }

    // Run this conditional step only when `!isRefreshing` is true.
    if (!isRefreshing) {
      isRefreshing = true;
      // Attempt this operation and recover from expected failures in the catch block below.
      try {
        const refreshRes = await fetch(`${baseUrl}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        // Reject this path when `!refreshRes.ok` to prevent invalid state from progressing.
        if (!refreshRes.ok) {
          throw new Error("Refresh failed");
        }

        const data = await refreshRes.json();
        const user = useAuthStore.getState().user;
        // Reject this path when `!user` to prevent invalid state from progressing.
        if (!user) {
          throw new Error("Missing user while refreshing session");
        }
        useAuthStore.getState().setAuth(user, data.access_token, data.refresh_token);
        isRefreshing = false;
        onRefreshed(data.access_token);
      // Recover from the attempted operation by applying this error-handling path.
      } catch (_error) {
        isRefreshing = false;
        useAuthStore.getState().clearAuth();
        throw new ApiError(401, { message: "Session expired" });
      }
    }

    return new Promise((resolve, reject) => {
      addRefreshSubscriber((newToken) => {
        const newHeaders = new Headers(headers);
        newHeaders.set("Authorization", `Bearer ${newToken}`);
        fetch(url, { ...options, headers: newHeaders })
          .then(async (res) => {
            // Run this conditional step only when `!res.ok` is true.
            if (!res.ok) {
              let data: unknown;
              // Attempt this operation and recover from expected failures in the catch block below.
              try {
                data = await res.json();
              // Recover from the attempted operation by applying this error-handling path.
              } catch {
                data = { message: res.statusText };
              }
              throw new ApiError(res.status, data);
            }
            // Return early when `res.status === 204` because the remaining work is not applicable.
            if (res.status === 204) {
              return {} as T;
            }
            return res.json() as Promise<T>;
          })
          .then(resolve)
          .catch(reject);
      });
    });
  }

  // Run this conditional step only when `!response.ok` is true.
  if (!response.ok) {
    let data: unknown;
    // Attempt this operation and recover from expected failures in the catch block below.
    try {
      data = await response.json();
    // Recover from the attempted operation by applying this error-handling path.
    } catch {
      data = { message: response.statusText };
    }
    throw new ApiError(response.status, data);
  }

  // Return early when `response.status === 204` because the remaining work is not applicable.
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

