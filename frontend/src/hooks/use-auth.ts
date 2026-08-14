import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, refreshAccessToken } from '@/services/api/client';
import { getApiBaseUrl } from '@/services/api/runtime';
import { browserLogoutRequest, type BrowserAccessTokenResponse } from '@/services/auth/browser-session';
import { useAuthStore } from '../store/authStore';
import {
  ChangePasswordRequest,
  LoginRequest,
  MeResponse,
  PasswordChangeResponse,
  RegisterRequest,
  SessionResponse,
} from '../types/api';
import { useEffect } from 'react';

function redirectToHomeAndReload() {
  const locale = window.location.pathname.split("/")[1];
  const homePath = locale ? `/${locale}` : "/";
  window.location.replace(homePath);
}

function redirectToLoginAndReload() {
  const locale = window.location.pathname.split("/")[1];
  const loginPath = locale ? `/${locale}/login` : "/login";
  window.location.replace(loginPath);
}

function completeClientLogout(queryClient: ReturnType<typeof useQueryClient>) {
  useAuthStore.getState().clearAuth();
  queryClient.clear();
}

export function useInitializeAuth() {
  const { setAuth, clearAuth, setInitializing } = useAuthStore();

  useEffect(() => {
    const init = async () => {
      try {
        const baseUrl = getApiBaseUrl();
        const accessToken = await refreshAccessToken(baseUrl);
        const user = await apiClient<MeResponse>('/me');
        setAuth(user, accessToken);
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
      const tokens = await apiClient<BrowserAccessTokenResponse>('/auth/browser/login', {
        method: 'POST',
        body: JSON.stringify(data)
      });
      useAuthStore.getState().setAccessToken(tokens.access_token);
      const user = await apiClient<MeResponse>('/me');
      setAuth(user, tokens.access_token);
      return user;
    }
  });
}

export function useRegister() {
  const { setAuth } = useAuthStore();
  return useMutation({
    mutationFn: async (data: RegisterRequest) => {
      await apiClient('/auth/register', {
        method: 'POST',
        body: JSON.stringify(data)
      });
      const tokens = await apiClient<BrowserAccessTokenResponse>('/auth/browser/login', {
        method: 'POST',
        body: JSON.stringify({ username_or_email: data.username, password: data.password })
      });
      useAuthStore.getState().setAccessToken(tokens.access_token);
      const user = await apiClient<MeResponse>('/me');
      setAuth(user, tokens.access_token);
      return user;
    }
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      try {
        await browserLogoutRequest(getApiBaseUrl());
      } catch (e) { }
      completeClientLogout(queryClient);
      redirectToHomeAndReload();
    }
  });
}

export function useSessions(enabled = true) {
  return useQuery({
    queryKey: ['/auth/sessions'],
    queryFn: () => apiClient<{items: SessionResponse[]}>('/auth/sessions').then(res => res.items),
    enabled,
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

export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ChangePasswordRequest) =>
      apiClient<PasswordChangeResponse>('/auth/password', {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      completeClientLogout(queryClient);
      redirectToLoginAndReload();
    },
  });
}
