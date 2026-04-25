export interface User {
  id: string;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
}

export interface MeResponse extends User {
  email?: string | null;
  bio?: string | null;
  created_at?: string;
  updated_at?: string | null;
}

export interface UpdateMeRequest {
  email?: string | null;
  display_name?: string | null;
  avatar_url?: string | null;
  bio?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RegisterRequest {
  username: string;
  email?: string | null;
  password: string;
}

export interface LoginRequest {
  username_or_email: string;
  password: string;
}

export interface ChannelPermissions {
  can_publish: boolean;
  can_invite: boolean;
  can_approve: boolean;
  can_manage_members: boolean;
  can_edit_channel: boolean;
  can_delete_channel: boolean;
}

export interface AttachmentItem {
  file_id: string;
  filename?: string;
  content_type?: string;
  public_url: string;
  size_bytes?: number;
}

export interface MessageResponse {
  id: string;
  channel_id: string;
  sender_user_id: string;
  seq_id: number;
  content_type: "text" | "json";
  content_text?: string | null;
  content_json?: Record<string, unknown> | null;
  reply_to_message_id?: string | null;
  reply_to_seq_id?: number | null;
  attachments?: AttachmentItem[] | null;
  is_pinned?: boolean;
  client_msg_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  edited_at?: string | null;
  deleted_at?: string | null;
  reactions_summary: {
    counts: Record<string, number>;
    my_reaction: string[];
  };
}

export interface ChannelResponse {
  id: string;
  owner_user_id: string;
  name: string;
  description?: string | null;
  avatar_url?: string | null;
  visibility: "public" | "private";
  join_mode: "open" | "approval_required" | "invite_only";
  member_count: number;
  pending_count: number;
  unread_count: number;
  my_last_seen_seq_id?: number | null;
  last_message?: MessageResponse | null;
  last_message_at?: string | null;
  my_role: "owner" | "admin" | "member" | "pending" | "none";
  permissions: ChannelPermissions;
  created_at?: string;
  updated_at?: string;
  deleted_at?: string | null;
}

export interface SessionResponse {
  id: string;
  created_at: string;
  expires_at: string;
  revoked_at?: string | null;
  user_agent?: string | null;
  ip?: string | null;
}

export interface InvitePreviewChannel {
  id: string;
  name: string;
  visibility: "public" | "private";
}

export interface InviteDetailsResponse {
  is_valid: boolean;
  reason?: string | null;
  channel?: InvitePreviewChannel | null;
  expires_at?: string | null;
  invited_email?: string | null;
  invited_user_id?: string | null;
}
