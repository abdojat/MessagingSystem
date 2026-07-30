import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import { getApiBaseUrl } from '@/services/api/runtime';
import { useAuthStore } from '../store/authStore';
import { LoginRequest, RegisterRequest, TokenPair, MeResponse, SessionResponse } from '../types/api';
import { useEffect } from 'react';

// Redirects to home and reload; React components use it to access or update application state.
function redirectToHomeAndReload() {
  const locale = window.location.pathname.split("/")[1];
  const homePath = locale ? `/${locale}` : "/";
  window.location.replace(homePath);
}

// Completes client logout; React components use it to access or update application state.
function completeClientLogout(queryClient: ReturnType<typeof useQueryClient>) {
  useAuthStore.getState().clearAuth();
  queryClient.clear();
}

// Provides initialize auth behavior; React components use it to access or update application state.
export function useInitializeAuth() {
  const { setAuth, clearAuth, setInitializing } = useAuthStore();

  useEffect(() => {
    // Restores the browser authentication session; React components use it to access or update application state.
    const init = async () => {
      const refreshToken = localStorage.getItem('chat_refresh_token');
      // Run this conditional step only when `!refreshToken` is true.
      if (!refreshToken) {
        clearAuth();
        return;
      }

      // Attempt this operation and recover from expected failures in the catch block below.
      try {
        const baseUrl = getApiBaseUrl();
        // Use refresh_token to get a new token pair
        const refreshRes = await fetch(`${baseUrl}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken })
        });

        // Run this conditional step only when `!refreshRes.ok` is true.
        if (!refreshRes.ok) {
          clearAuth();
          return;
        }

        const tokens: TokenPair = await refreshRes.json();
        // Set the access token in the store so the next /me call uses it
        useAuthStore.setState({ accessToken: tokens.access_token });
        localStorage.setItem('chat_refresh_token', tokens.refresh_token);

        const user = await apiClient<MeResponse>('/me');
        setAuth(user, tokens.access_token, tokens.refresh_token);
      // Recover from the attempted operation by applying this error-handling path.
      } catch (e) {
        clearAuth();
      // Always finalize local state after the attempted operation finishes.
      } finally {
        setInitializing(false);
      }
    };
    init();
  }, []);
}

// Provides login behavior; React components use it to access or update application state.
export function useLogin() {
  const { setAuth } = useAuthStore();
  return useMutation({
    mutationFn: async (data: LoginRequest) => {
      const tokens = await apiClient<TokenPair>('/auth/login', {
        method: 'POST',
        body: JSON.stringify(data)
      });
      // Temporarily set tokens to make the /me request
      useAuthStore.setState({ accessToken: tokens.access_token });
      const user = await apiClient<MeResponse>('/me');
      setAuth(user, tokens.access_token, tokens.refresh_token);
      return user;
    }
  });
}

// Provides register behavior; React components use it to access or update application state.
export function useRegister() {
  const { setAuth } = useAuthStore();
  return useMutation({
    mutationFn: async (data: RegisterRequest) => {
      // API might return user directly, but we need tokens. 
      // Assuming register logs in or we need to login after. Let's assume login after for safety.
      await apiClient('/auth/register', {
        method: 'POST',
        body: JSON.stringify(data)
      });
      const tokens = await apiClient<TokenPair>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username_or_email: data.username, password: data.password })
      });
      useAuthStore.setState({ accessToken: tokens.access_token });
      const user = await apiClient<MeResponse>('/me');
      setAuth(user, tokens.access_token, tokens.refresh_token);
      return user;
    }
  });
}

// Provides logout behavior; React components use it to access or update application state.
export function useLogout() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const refreshToken = localStorage.getItem('chat_refresh_token');
      // Run this conditional step only when `refreshToken` is true.
      if (refreshToken) {
        // Attempt this operation and recover from expected failures in the catch block below.
        try {
          await apiClient('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }) });
        // Recover from the attempted operation by applying this error-handling path.
        } catch (e) { }
      }
      completeClientLogout(queryClient);
      redirectToHomeAndReload();
    }
  });
}

// Provides sessions behavior; React components use it to access or update application state.
export function useSessions(enabled = true) {
  return useQuery({
    queryKey: ['/auth/sessions'],
    queryFn: () => apiClient<{items: SessionResponse[]}>('/auth/sessions').then(res => res.items),
    enabled,
  });
}

// Provides delete session behavior; React components use it to access or update application state.
export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => apiClient(`/auth/sessions/${sessionId}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['/auth/sessions'] })
  });
}

// Provides logout all behavior; React components use it to access or update application state.
export function useLogoutAll() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiClient('/auth/logout_all', { method: 'POST' }),
    onSuccess: () => {
      completeClientLogout(queryClient);
      redirectToHomeAndReload();
    }
  });
}
