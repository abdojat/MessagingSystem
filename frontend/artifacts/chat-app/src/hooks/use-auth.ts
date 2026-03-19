import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/apiClient';
import { getApiBaseUrl } from '../lib/runtimeConfig';
import { useAuthStore } from '../store/authStore';
import { LoginRequest, RegisterRequest, TokenPair, MeResponse, SessionResponse } from '../types/api';
import { useEffect } from 'react';

function redirectToHomeAndReload() {
  const homePath = import.meta.env.BASE_URL || '/';
  window.location.replace(homePath);
}

function completeClientLogout(queryClient: ReturnType<typeof useQueryClient>) {
  useAuthStore.getState().clearAuth();
  queryClient.clear();
}

export function useInitializeAuth() {
  const { setAuth, clearAuth, setInitializing } = useAuthStore();

  useEffect(() => {
    const init = async () => {
      const refreshToken = localStorage.getItem('chat_refresh_token');
      if (!refreshToken) {
        clearAuth();
        return;
      }

      try {
        const baseUrl = getApiBaseUrl();
        // Use refresh_token to get a new token pair
        const refreshRes = await fetch(`${baseUrl}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken })
        });

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
      } catch (e) {
        clearAuth();
      } finally {
        setInitializing(false);
      }
    };
    init();
  }, []);
}

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

export function useLogout() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const refreshToken = localStorage.getItem('chat_refresh_token');
      if (refreshToken) {
        try {
          await apiClient('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }) });
        } catch (e) { }
      }
      completeClientLogout(queryClient);
      redirectToHomeAndReload();
    }
  });
}

export function useSessions() {
  return useQuery({
    queryKey: ['/auth/sessions'],
    queryFn: () => apiClient<{items: SessionResponse[]}>('/auth/sessions').then(res => res.items)
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => apiClient(`/auth/sessions/${sessionId}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['/auth/sessions'] })
  });
}

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
