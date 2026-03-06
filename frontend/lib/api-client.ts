import { API_V1_BASE_URL } from "@/lib/env";
import { getAccessToken, getRefreshToken, setTokenPair, useAuthStore } from "@/store/auth-store";
import type {
  ApiErrorResponse,
  ChannelListResponse,
  ChannelMembership,
  ChannelResponse,
  ChannelStatsResponse,
  CursorPage,
  InviteListItem,
  InvitePreview,
  InviteResponse,
  JoinOutcomeResponse,
  LoginRequest,
  MeResponse,
  MembershipActionResponse,
  MessageListResponse,
  MessageResponse,
  PublishMessageRequest,
  ReactionSummaryResponse,
  RegisterRequest,
  SeenResponse,
  SessionResponse,
  SyncResponse,
  TokenPair,
  UploadCreateResponse,
} from "@/types/api";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown> | null;

  constructor(status: number, payload?: Partial<ApiErrorResponse>) {
    super(payload?.message ?? "Request failed");
    this.name = "ApiError";
    this.status = status;
    this.code = payload?.code ?? "UNKNOWN_ERROR";
    this.details = payload?.details;
  }
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
      useAuthStore.getState().clearAuth();
      return null;
    }

    const response = await fetch(`${API_V1_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      useAuthStore.getState().clearAuth();
      return null;
    }

    const tokenPair = (await response.json()) as TokenPair;
    setTokenPair(tokenPair);
    return tokenPair.access_token;
  })().finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  authenticated?: boolean;
  signal?: AbortSignal;
};

async function parseApiError(response: Response): Promise<ApiError> {
  let payload: ApiErrorResponse | undefined;
  try {
    payload = (await response.json()) as ApiErrorResponse;
  } catch {
    payload = undefined;
  }
  return new ApiError(response.status, payload);
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}, retried = false): Promise<T> {
  const token = getAccessToken();

  const headers: Record<string, string> = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers ?? {}),
  };

  if (options.authenticated !== false && token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_V1_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    cache: "no-store",
  });

  if (response.status === 401 && options.authenticated !== false && !retried) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return apiRequest<T>(path, options, true);
    }
  }

  if (!response.ok) {
    throw await parseApiError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  register: (payload: RegisterRequest) => apiRequest<{ id: string; username: string; email: string | null }>("/auth/register", { method: "POST", body: payload, authenticated: false }),
  login: (payload: LoginRequest) => apiRequest<TokenPair>("/auth/login", { method: "POST", body: payload, authenticated: false }),
  refresh: (refreshToken: string) => apiRequest<TokenPair>("/auth/refresh", { method: "POST", body: { refresh_token: refreshToken }, authenticated: false }),
  logout: (refreshToken: string) => apiRequest<{ status: "ok" }>("/auth/logout", { method: "POST", body: { refresh_token: refreshToken } }),
  me: () => apiRequest<MeResponse>("/me"),
  sessions: () => apiRequest<{ items: SessionResponse[] }>("/auth/sessions"),
  logoutAll: () => apiRequest<{ status: string; revoked_count: number }>("/auth/logout_all", { method: "POST" }),
  revokeSession: (sessionId: string) => apiRequest<{ status: "ok" }>(`/auth/sessions/${sessionId}`, { method: "DELETE" }),

  listChannels: (params?: {
    cursor?: string;
    q?: string;
    scope?: "my" | "discover";
    visibility?: "public" | "private";
    limit?: number;
  }) => {
    const query = new URLSearchParams(
      Object.entries({
        ...(params?.cursor ? { cursor: params.cursor } : {}),
        ...(params?.q ? { q: params.q } : {}),
        ...(params?.scope ? { scope: params.scope } : {}),
        ...(params?.visibility ? { visibility: params.visibility } : {}),
        ...(params?.limit ? { limit: String(params.limit) } : {}),
      }),
    );
    return apiRequest<ChannelListResponse>(`/channels${query.size > 0 ? `?${query.toString()}` : ""}`);
  },
  createChannel: (payload: Partial<ChannelResponse> & { name: string; visibility: "public" | "private"; join_mode: "open" | "invite_only" | "approval_required" }) =>
    apiRequest<ChannelResponse>("/channels", { method: "POST", body: payload }),
  getChannel: (channelId: string) => apiRequest<ChannelResponse>(`/channels/${channelId}`),
  patchChannel: (channelId: string, body: Partial<Pick<ChannelResponse, "name" | "description" | "avatar_url" | "visibility" | "join_mode">>) =>
    apiRequest<ChannelResponse>(`/channels/${channelId}`, { method: "PATCH", body }),
  deleteChannel: (channelId: string) => apiRequest<{ status: "ok" }>(`/channels/${channelId}`, { method: "DELETE" }),
  getChannelStats: (channelId: string) => apiRequest<ChannelStatsResponse>(`/channels/${channelId}/stats`),
  getMyMembership: (channelId: string) => apiRequest<ChannelMembership>(`/channels/${channelId}/my-membership`),
  joinChannel: (channelId: string, inviteToken?: string) =>
    apiRequest<JoinOutcomeResponse>(`/channels/${channelId}/join`, { method: "POST", body: inviteToken ? { invite_token: inviteToken } : {} }),
  leaveChannel: (channelId: string) => apiRequest<{ status: "ok" }>(`/channels/${channelId}/leave`, { method: "POST" }),
  members: (channelId: string, cursor?: string) =>
    apiRequest<CursorPage<{ user_id: string; username: string; email: string | null; role: "owner" | "admin" | "member" | "pending" | "none"; created_at: string; approved_at: string | null; updated_at: string | null; invited_by_user_id: string | null }>>(
      `/channels/${channelId}/members${cursor ? `?${new URLSearchParams({ cursor })}` : ""}`,
    ),
  requests: (channelId: string, cursor?: string) => apiRequest<CursorPage<{ user_id: string; username: string; email: string | null; role: "pending"; created_at: string; approved_at: string | null }>>(`/channels/${channelId}/requests${cursor ? `?${new URLSearchParams({ cursor })}` : ""}`),
  approveMember: (channelId: string, userId: string) => apiRequest<MembershipActionResponse>(`/channels/${channelId}/members/${userId}/approve`, { method: "POST" }),
  addMember: (channelId: string, userId: string) => apiRequest<MembershipActionResponse>(`/channels/${channelId}/members/${userId}/add`, { method: "POST" }),
  promoteMember: (channelId: string, userId: string) => apiRequest<MembershipActionResponse>(`/channels/${channelId}/members/${userId}/promote`, { method: "POST" }),
  demoteMember: (channelId: string, userId: string) => apiRequest<MembershipActionResponse>(`/channels/${channelId}/members/${userId}/demote`, { method: "POST" }),
  removeMember: (channelId: string, userId: string) => apiRequest<{ status: "ok" }>(`/channels/${channelId}/members/${userId}`, { method: "DELETE" }),

  createInvite: (channelId: string, payload: { invited_user_id?: string; invited_email?: string; is_generic?: boolean; expires_in_hours?: number }) =>
    apiRequest<InviteResponse>(`/channels/${channelId}/invite`, { method: "POST", body: payload }),
  listInvites: (channelId: string, cursor?: string) =>
    apiRequest<CursorPage<InviteListItem>>(`/channels/${channelId}/invites${cursor ? `?${new URLSearchParams({ cursor })}` : ""}`),
  revokeInvite: (channelId: string, inviteId: string) => apiRequest<{ status: "ok" }>(`/channels/${channelId}/invites/${inviteId}/revoke`, { method: "POST" }),
  invitePreview: (token: string) => apiRequest<InvitePreview>(`/invites/${token}`, { authenticated: false }),
  acceptInvite: (token: string) => apiRequest<MembershipActionResponse>(`/invites/${token}/accept`, { method: "POST" }),

  sendMessage: (channelId: string, payload: PublishMessageRequest) => apiRequest<MessageResponse>(`/channels/${channelId}/messages`, { method: "POST", body: payload }),
  listMessages: (channelId: string, params: { before_seq_id?: number; after_seq_id?: number; limit?: number; order?: "asc" | "desc" }) =>
    apiRequest<MessageListResponse>(`/channels/${channelId}/messages?${new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    )}`),
  aroundMessages: (channelId: string, seqId: number) => apiRequest<{ seq_id: number; items: MessageResponse[] }>(`/channels/${channelId}/messages/around?seq_id=${seqId}`),
  getMessage: (channelId: string, messageId: string) => apiRequest<MessageResponse>(`/channels/${channelId}/messages/${messageId}`),
  editMessage: (channelId: string, messageId: string, payload: { content_text?: string; content_json?: Record<string, unknown> }) =>
    apiRequest<MessageResponse>(`/channels/${channelId}/messages/${messageId}`, { method: "PATCH", body: payload }),
  deleteMessage: (channelId: string, messageId: string) => apiRequest<MessageResponse>(`/channels/${channelId}/messages/${messageId}`, { method: "DELETE" }),

  markSeen: (channelId: string, last_seen_seq_id: number) => apiRequest<SeenResponse>(`/channels/${channelId}/seen`, { method: "POST", body: { last_seen_seq_id } }),

  addReaction: (channelId: string, messageId: string, emoji: string) => apiRequest<ReactionSummaryResponse>(`/channels/${channelId}/messages/${messageId}/reactions`, { method: "POST", body: { emoji } }),
  removeReaction: (channelId: string, messageId: string, emoji: string) => apiRequest<ReactionSummaryResponse>(`/channels/${channelId}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`, { method: "DELETE" }),

  pinMessage: (channelId: string, messageId: string) => apiRequest<void>(`/channels/${channelId}/pins/${messageId}`, { method: "POST" }),
  unpinMessage: (channelId: string, messageId: string) => apiRequest<void>(`/channels/${channelId}/pins/${messageId}`, { method: "DELETE" }),
  listPins: (channelId: string) => apiRequest<{ items: MessageResponse[] }>(`/channels/${channelId}/pins`),

  createUpload: (payload: { filename: string; content_type: string; size_bytes: number; checksum?: string }) =>
    apiRequest<UploadCreateResponse>("/uploads", { method: "POST", body: payload }),
  completeUpload: (fileId: string, content: Blob) =>
    fetch(`${API_V1_BASE_URL}/uploads/${fileId}/content`, {
      method: "PUT",
      body: content,
      headers: { Authorization: `Bearer ${getAccessToken()}` },
    }).then(async (res) => {
      if (!res.ok) {
        throw await parseApiError(res);
      }
      return (await res.json()) as { file_id: string; public_url: string };
    }),

  sync: (payload: { channels: Array<{ channel_id: string; last_seen_seq_id: number | null }>; since?: string; limit?: number }) =>
    apiRequest<SyncResponse>("/sync", { method: "POST", body: payload }),

  channelEvents: (channelId: string, cursor?: string) =>
    apiRequest<{ items: Array<{ id: string; channel_id: string | null; actor_user_id: string | null; event_type: string; payload: Record<string, unknown>; created_at: string }>; next_cursor: string | null; has_more: boolean }>(
      `/channels/${channelId}/events${cursor ? `?${new URLSearchParams({ cursor })}` : ""}`,
    ),

  health: () => apiRequest<{ status: "ok"; db: string; redis: string; rabbitmq: string }>("/health", { authenticated: false }),
};

