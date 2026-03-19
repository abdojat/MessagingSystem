import { useAuthStore } from '../store/authStore';
import { getApiBaseUrl } from './runtimeConfig';

const getBaseUrl = () => {
  return getApiBaseUrl();
};

class ApiError extends Error {
  constructor(public status: number, public data: any) {
    super(data.message || `API Error: ${status}`);
  }
}

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onRefreshed(token: string) {
  refreshSubscribers.map(cb => cb(token));
  refreshSubscribers = [];
}

function addRefreshSubscriber(cb: (token: string) => void) {
  refreshSubscribers.push(cb);
}

export async function apiClient<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getBaseUrl();
  const url = `${baseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  
  const token = useAuthStore.getState().accessToken;
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    const refreshToken = localStorage.getItem('chat_refresh_token');
    
    if (!refreshToken) {
      useAuthStore.getState().clearAuth();
      throw new ApiError(401, { message: 'Unauthorized' });
    }

    if (!isRefreshing) {
      isRefreshing = true;
      try {
        const refreshRes = await fetch(`${baseUrl}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken })
        });
        
        if (!refreshRes.ok) throw new Error('Refresh failed');
        
        const data = await refreshRes.json();
        useAuthStore.getState().setAuth(useAuthStore.getState().user!, data.access_token, data.refresh_token);
        isRefreshing = false;
        onRefreshed(data.access_token);
      } catch (err) {
        isRefreshing = false;
        useAuthStore.getState().clearAuth();
        throw new ApiError(401, { message: 'Session expired' });
      }
    }

    // Wait for refresh to complete then retry
    return new Promise((resolve, reject) => {
        addRefreshSubscriber((newToken) => {
          const newHeaders = new Headers(headers);
          newHeaders.set('Authorization', `Bearer ${newToken}`);
          fetch(url, { ...options, headers: newHeaders })
          .then(async (res) => {
            if (!res.ok) {
              let data;
              try { data = await res.json(); } catch { data = { message: res.statusText }; }
              throw new ApiError(res.status, data);
            }
            if (res.status === 204) {
              return {} as T;
            }
            return res.json();
          })
          .then(resolve)
          .catch(reject);
      });
    });
  }

  if (!response.ok) {
    let data;
    try { data = await response.json(); } catch { data = { message: response.statusText }; }
    throw new ApiError(response.status, data);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}
