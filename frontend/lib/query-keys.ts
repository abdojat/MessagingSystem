export const queryKeys = {
  me: ["me"] as const,
  sessions: ["sessions"] as const,
  channels: (params?: string) => ["channels", params ?? "default"] as const,
  channel: (channelId: string) => ["channel", channelId] as const,
  channelMembers: (channelId: string, cursor: string) => ["channel-members", channelId, cursor] as const,
  channelRequests: (channelId: string, cursor: string) => ["channel-requests", channelId, cursor] as const,
  channelInvites: (channelId: string, cursor: string) => ["channel-invites", channelId, cursor] as const,
  channelMyMembership: (channelId: string) => ["channel-my-membership", channelId] as const,
  messages: (channelId: string) => ["messages", channelId] as const,
  pins: (channelId: string) => ["pins", channelId] as const,
  invite: (token: string) => ["invite", token] as const,
};

