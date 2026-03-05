export type ApiErrorResponse = {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type RegisterRequest = {
  username: string;
  email?: string;
  password: string;
};

export type LoginRequest = {
  username_or_email: string;
  password: string;
};

export type SessionResponse = {
  id: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  user_agent: string | null;
  ip: string | null;
};

export type MeResponse = {
  id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  bio: string | null;
  created_at: string;
  updated_at: string | null;
};

export type ChannelRole = "owner" | "admin" | "member" | "pending" | "none";

export type ChannelPermissions = {
  can_publish: boolean;
  can_invite: boolean;
  can_approve: boolean;
  can_manage_members: boolean;
  can_edit_channel: boolean;
  can_delete_channel: boolean;
};

export type MessageResponse = {
  id: string;
  channel_id: string;
  sender_user_id: string;
  seq_id: number;
  content_type: "text" | "json";
  content_text: string | null;
  content_json: Record<string, unknown> | null;
  reply_to_message_id: string | null;
  reply_to_seq_id: number | null;
  attachments: Array<Record<string, unknown>> | null;
  is_pinned: boolean;
  client_msg_id: string | null;
  created_at: string;
  updated_at: string | null;
  edited_at: string | null;
  deleted_at: string | null;
  reactions_summary: {
    counts: Record<string, number>;
    my_reaction: string[];
  };
};

export type ChannelResponse = {
  id: string;
  owner_user_id: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  visibility: "public" | "private";
  join_mode: "open" | "invite_only" | "approval_required";
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  member_count: number;
  pending_count: number;
  last_message: MessageResponse | null;
  last_message_at: string | null;
  my_last_seen_seq_id: number | null;
  unread_count: number;
  my_role: ChannelRole;
  permissions: ChannelPermissions;
};

export type ChannelListResponse = {
  items: ChannelResponse[];
  next_cursor: string | null;
  has_more: boolean;
};

export type ChannelStatsResponse = {
  channel_id: string;
  member_count: number;
  pending_count: number;
  message_count: number;
  last_message_at: string | null;
};

export type ChannelMembership = {
  channel_id: string;
  user_id: string;
  role: ChannelRole;
  created_at: string | null;
  approved_at: string | null;
};

export type ChannelMemberItem = {
  user_id: string;
  username: string;
  email: string | null;
  role: ChannelRole;
  created_at: string;
  approved_at: string | null;
  updated_at: string | null;
  invited_by_user_id: string | null;
};

export type CursorPage<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
};

export type InviteResponse = {
  id: string;
  token: string;
  channel_id: string;
  expires_at: string;
};

export type InviteListItem = {
  id: string;
  channel_id: string;
  invited_user_id: string | null;
  invited_email: string | null;
  is_generic: boolean;
  masked_token: string;
  token_masked: string | null;
  created_by_user_id: string;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
};

export type InvitePreview = {
  is_valid: boolean;
  reason: string | null;
  channel: {
    id: string;
    name: string;
    visibility: "public" | "private";
  } | null;
  expires_at: string | null;
  invited_email: string | null;
  invited_user_id: string | null;
};

export type MembershipActionResponse = {
  channel_id: string;
  user_id: string;
  role: ChannelRole;
};

export type JoinOutcomeResponse = {
  status: "joined" | "pending" | "requires_invite" | "already_member";
  role: ChannelRole;
  message: string;
  channel: ChannelResponse | null;
};

export type PublishMessageRequest = {
  content_text?: string;
  content_json?: Record<string, unknown>;
  reply_to_message_id?: string;
  reply_to_seq_id?: number;
  attachments?: Array<Record<string, unknown>>;
  client_msg_id?: string;
};

export type MessageListResponse = {
  items: MessageResponse[];
  next_before_seq_id: number | null;
  next_after_seq_id: number | null;
  has_more: boolean;
  order: "asc" | "desc";
};

export type ReactionSummaryResponse = {
  counts: Record<string, number>;
  my_reaction: string[];
};

export type SeenResponse = {
  channel_id: string;
  user_id: string;
  last_seen_seq_id: number | null;
  last_seen_message_id: string | null;
  last_seen_at: string | null;
  unread_count: number | null;
};

export type UploadCreateResponse = {
  file_id: string;
  upload_url: string;
  method: "PUT";
  headers: Record<string, string>;
  public_url: string | null;
};

export type SyncResponse = {
  server_time: string;
  channel_updates: Array<{
    channel_id: string;
    patch: Record<string, unknown>;
    updated_at: string;
  }>;
  membership_updates: Array<{
    channel_id: string;
    user_id: string;
    new_role: ChannelRole;
    reason: string;
    updated_at: string;
  }>;
  messages: MessageResponse[];
};

export type WsEnvelope =
  | { type: "hello"; user_id: string; server_time: string }
  | { type: "history"; channel_id: string; items: MessageResponse[]; is_truncated: boolean }
  | { type: "message"; channel_id: string; message: MessageResponse }
  | { type: "membership_update"; channel_id: string; user_id: string; new_role: ChannelRole; reason: string }
  | {
      type: "channel_updated";
      channel_id: string;
      patch: { name?: string; visibility?: "public" | "private"; join_mode?: "open" | "invite_only" | "approval_required" };
    }
  | { type: "sync"; states: Array<{ channel_id: string; last_seen_seq_id: number | null; last_seen_at: string | null }> }
  | { type: "seen"; channel_id: string; last_seen_seq_id: number; last_seen_at?: string | null }
  | { type: "error"; code?: string; message?: string; details?: Record<string, unknown> };

