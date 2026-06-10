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

export interface AdminPermissions {
  can_publish: boolean;
  can_invite: boolean;
  can_approve: boolean;
  can_manage_members: boolean;
  can_edit_channel: boolean;
}

export type MembershipRole = "owner" | "admin" | "member" | "pending" | "none";

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
  sender_username?: string;
  sender_display_name?: string | null;
  sender_avatar_url?: string | null;
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

export interface ReactionSummaryResponse {
  counts: Record<string, number>;
  my_reaction: string[];
}

export interface ChannelResponse {
  channel_slug?: string;
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
  my_role: MembershipRole;
  permissions: ChannelPermissions;
  created_at?: string;
  updated_at?: string;
  deleted_at?: string | null;
}

export interface ChannelPatchRequest {
  name?: string;
  description?: string | null;
  avatar_url?: string | null;
  visibility?: "public" | "private";
  join_mode?: "open" | "approval_required" | "invite_only";
}

export interface ChannelMembershipItem {
  user_id: string;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
  email?: string | null;
  role: MembershipRole;
  created_at: string;
  approved_at?: string | null;
  updated_at?: string | null;
  invited_by_user_id?: string | null;
  admin_permissions?: AdminPermissions | null;
}

export interface AdminPermissionsUpdateRequest {
  can_publish?: boolean;
  can_invite?: boolean;
  can_approve?: boolean;
  can_manage_members?: boolean;
  can_edit_channel?: boolean;
}

export interface AdminPermissionsUpdateResponse {
  channel_id: string;
  user_id: string;
  role: MembershipRole;
  admin_permissions: AdminPermissions;
}

export interface ChannelMembershipListResponse {
  items: ChannelMembershipItem[];
  next_cursor?: string | null;
  has_more: boolean;
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

export interface EventResponse {
  id: string;
  channel_id?: string | null;
  actor_user_id?: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  previous_hash?: string | null;
  event_hash?: string | null;
  hash_algorithm?: string | null;
  integrity_version?: number | null;
  integrity_scope?: string | null;
}

export interface EventListResponse {
  items: EventResponse[];
  next_cursor?: string | null;
  has_more: boolean;
}

export interface EventIntegrityResponse {
  scope: string;
  valid: boolean;
  checked_events: number;
  broken_event_id?: string | null;
  reason?: string | null;
  expected_hash?: string | null;
  actual_hash?: string | null;
  previous_event_id?: string | null;
  last_valid_hash?: string | null;
  first_event_id?: string | null;
  last_event_id?: string | null;
  hash_algorithm: string;
  integrity_version: number;
}

export type DeliveryStatus =
  | "pending"
  | "publishing"
  | "published"
  | "retry_scheduled"
  | "failed"
  | "dead_lettered";

export interface DeliveryStatsResponse {
  pending: number;
  publishing: number;
  published: number;
  retry_scheduled: number;
  failed: number;
  dead_lettered: number;
}

export interface DeliveryItemResponse {
  id: string;
  channel_id: string;
  channel_slug?: string | null;
  message_id?: string | null;
  event_type?: string | null;
  payload_type?: string | null;
  routing_key: string;
  status: DeliveryStatus | string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at?: string | null;
  published_at?: string | null;
  dead_lettered_at?: string | null;
}

export interface DeliveryListResponse {
  items: DeliveryItemResponse[];
}

export interface DeliveryRetryResponse {
  status: string;
  retried_count: number;
  items: DeliveryItemResponse[];
}
