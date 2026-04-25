"use client";

import { useParams, useRouter } from "next/navigation";
import { useChannel, useJoinChannel } from "@/hooks/use-channels";
import { useMarkSeen, useMessages, useSendMessage } from "@/hooks/use-messages";
import { Hash, Settings, Paperclip, Send, SmilePlus, Reply, MoreVertical, X, ChevronDown, ChevronRight } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useAuthStore } from "@/store/authStore";
import { Skeleton } from "@/components/ui/skeleton";
import type { MessageResponse } from "@/types/api";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { resolveApiMediaUrl } from "@/lib/mediaUrl";

function ChannelViewSkeleton() {
  return (
    <div className="flex-1 flex flex-col h-full bg-background relative z-0">
      <header className="h-16 border-b border-border bg-background/80 backdrop-blur-md flex items-center justify-between px-6 flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-56" />
          </div>
        </div>
        <Skeleton className="h-10 w-10 rounded-xl" />
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-gradient-to-b from-background to-background/50">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="flex gap-4">
            <Skeleton className="h-10 w-10 rounded-full flex-shrink-0" />
            <div className="flex-1 space-y-3">
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
              <Skeleton className={`h-14 rounded-2xl ${index % 2 === 0 ? "w-80 max-w-full" : "w-64 max-w-full"}`} />
            </div>
          </div>
        ))}
      </div>

      <div className="p-4 bg-background border-t border-border flex-shrink-0">
        <div className="max-w-4xl mx-auto rounded-2xl border border-border/50 p-2 flex items-end gap-2">
          <Skeleton className="h-10 w-10 rounded-xl flex-shrink-0" />
          <Skeleton className="h-12 flex-1 rounded-xl" />
          <Skeleton className="h-10 w-10 rounded-xl flex-shrink-0" />
        </div>
      </div>
    </div>
  );
}

const MAX_REPLY_INDENT_DEPTH = 4;
const MAX_REPLY_CHAIN_DEPTH = 12;

function getMessageSnippet(message: MessageResponse | undefined): string {
  if (!message) return "Original message is not loaded in this view.";
  if (message.deleted_at) return "Original message was deleted.";
  if (message.content_type === "text") {
    const text = (message.content_text || "").trim();
    if (!text) return "Empty message";
    return text.length > 90 ? `${text.slice(0, 90)}...` : text;
  }
  if (message.attachments && message.attachments.length > 0) {
    return `[${message.attachments.length} attachment${message.attachments.length > 1 ? "s" : ""}]`;
  }
  return "Structured message";
}

export default function ChannelView() {
  const params = useParams<{ channelId?: string | string[] }>();
  const channelId = Array.isArray(params?.channelId) ? params.channelId[0] : params?.channelId;
  const router = useRouter();
  const localePath = useLocalePath();
  const {
    data: channel,
    isLoading: isChannelLoading,
    isError: isChannelError,
    refetch: refetchChannel,
  } = useChannel(channelId || '');
  const { data: messages = [], isLoading: isMessagesLoading } = useMessages(channelId || '');
  const joinChannel = useJoinChannel();
  const sendMessage = useSendMessage();
  const markSeen = useMarkSeen();
  
  const [content, setContent] = useState("");
  const [replyingTo, setReplyingTo] = useState<MessageResponse | null>(null);
  const [collapsedReplyRoots, setCollapsedReplyRoots] = useState<Set<string>>(new Set());
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const lastMarkedSeenSeqRef = useRef<number | null>(null);
  const user = useAuthStore(s => s.user);
  const isMember = ['owner', 'admin', 'member'].includes(channel?.my_role || '');
  const canCompose = ['owner', 'admin'].includes(channel?.my_role || '');
  const canReplyAsMember = isMember && !canCompose;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    setReplyingTo(null);
    setCollapsedReplyRoots(new Set());
  }, [channelId]);

  useEffect(() => {
    if (!channelId || !isMember || messages.length === 0) return;

    const latestMessage = messages[messages.length - 1];
    const latestSeqId = latestMessage?.seq_id;
    const currentSeenSeqId = channel?.my_last_seen_seq_id ?? 0;

    if (!latestSeqId || latestSeqId <= currentSeenSeqId || lastMarkedSeenSeqRef.current === latestSeqId) {
      return;
    }

    const container = scrollContainerRef.current;
    const isNearBottom = !container || container.scrollHeight - container.scrollTop - container.clientHeight < 80;

    if (!isNearBottom) return;

    lastMarkedSeenSeqRef.current = latestSeqId;
    markSeen.mutate(
      { channelId, lastSeenSeqId: latestSeqId },
      {
        onError: () => {
          if (lastMarkedSeenSeqRef.current === latestSeqId) {
            lastMarkedSeenSeqRef.current = null;
          }
        },
      }
    );
  }, [channel?.my_last_seen_seq_id, channelId, isMember, markSeen, messages]);

  if (isChannelLoading) return <ChannelViewSkeleton />;
  if (isChannelError && !channel) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-6">
        <div className="text-muted-foreground">We couldn't open this channel right now.</div>
        <Button onClick={() => refetchChannel()} className="rounded-full px-6">
          Try again
        </Button>
      </div>
    );
  }
  if (!channel) return <div className="flex-1 flex items-center justify-center text-muted-foreground">Channel not found</div>;

  const channelAvatarUrl = resolveApiMediaUrl(channel.avatar_url);
  const userAvatarUrl = resolveApiMediaUrl(user?.avatar_url);

  const handleSend = (e?: React.FormEvent) => {
    e?.preventDefault();
    const currentReplyTarget = replyingTo ? messages.find((item) => item.id === replyingTo.id) ?? replyingTo : null;
    const canReplyToTarget = currentReplyTarget && !currentReplyTarget.deleted_at;
    const canSend = canCompose || (canReplyAsMember && !!canReplyToTarget);
    if (!canSend || !content.trim() || !channelId) return;
    sendMessage.mutate({
      channelId,
      content_text: content,
      reply_to_message_id: canReplyToTarget ? currentReplyTarget.id : undefined,
      reply_to_seq_id: canReplyToTarget ? currentReplyTarget.seq_id : undefined,
    });
    setContent("");
    setReplyingTo(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const messageById = new Map(messages.map((message) => [message.id, message]));
  const replyChildrenById = new Map<string, MessageResponse[]>();
  for (const message of messages) {
    const parentId = message.reply_to_message_id;
    if (!parentId) continue;
    const children = replyChildrenById.get(parentId);
    if (children) {
      children.push(message);
    } else {
      replyChildrenById.set(parentId, [message]);
    }
  }

  const resolveSenderLabel = (message: MessageResponse | undefined) => {
    if (!message) return "Message";
    if (message.sender_user_id === user?.id) return "You";
    return `Member ${message.sender_user_id.slice(0, 8)}`;
  };

  const getReplyDepth = (message: MessageResponse): number => {
    let depth = 0;
    let parentId = message.reply_to_message_id ?? null;
    const visited = new Set<string>();
    while (parentId && depth < MAX_REPLY_CHAIN_DEPTH && !visited.has(parentId)) {
      visited.add(parentId);
      const parent = messageById.get(parentId);
      if (!parent) break;
      depth += 1;
      parentId = parent.reply_to_message_id ?? null;
    }
    return depth;
  };

  const getDescendantReplyCount = (messageId: string): number => {
    let count = 0;
    const visited = new Set<string>();
    const stack = [...(replyChildrenById.get(messageId) ?? [])];

    while (stack.length > 0) {
      const current = stack.pop();
      if (!current || visited.has(current.id)) continue;
      visited.add(current.id);
      count += 1;
      const children = replyChildrenById.get(current.id);
      if (children && children.length > 0) {
        stack.push(...children);
      }
    }
    return count;
  };

  const isHiddenByCollapsedAncestor = (message: MessageResponse): boolean => {
    let parentId = message.reply_to_message_id ?? null;
    const visited = new Set<string>();

    while (parentId && !visited.has(parentId)) {
      if (collapsedReplyRoots.has(parentId)) return true;
      visited.add(parentId);
      const parent = messageById.get(parentId);
      if (!parent) break;
      parentId = parent.reply_to_message_id ?? null;
    }
    return false;
  };

  const jumpToMessage = (messageId: string | null | undefined) => {
    if (!messageId) return;
    setCollapsedReplyRoots((current) => {
      if (current.size === 0) return current;
      const next = new Set(current);
      let changed = false;
      let cursorId: string | null = messageId;
      const visited = new Set<string>();
      while (cursorId && !visited.has(cursorId)) {
        visited.add(cursorId);
        const message = messageById.get(cursorId);
        const parentId = message?.reply_to_message_id ?? null;
        if (!parentId) break;
        if (next.delete(parentId)) {
          changed = true;
        }
        cursorId = parentId;
      }
      return changed ? next : current;
    });
    const node = messageRefs.current[messageId];
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const activeReplyTarget = replyingTo ? messageById.get(replyingTo.id) ?? replyingTo : null;
  const visibleMessages = messages.filter((message) => !isHiddenByCollapsedAncestor(message));

  return (
    <div className="flex-1 flex flex-col h-full bg-background relative z-0">
      {/* Header */}
      <header className="h-16 border-b border-border bg-background/80 backdrop-blur-md flex items-center justify-between px-6 flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
            {channelAvatarUrl ? <img src={channelAvatarUrl} className="w-full h-full rounded-xl object-cover" /> : <Hash className="w-5 h-5" />}
          </div>
          <div>
            <h2 className="font-bold text-foreground leading-tight">{channel.name}</h2>
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <span>{channel.member_count || 0} members</span>
              {channel.description && (
                <>
                  <span>•</span>
                  <span className="truncate max-w-[200px]">{channel.description}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="icon"
            variant="ghost"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => router.push(localePath(`/app/channels/${channel.id}/details`))}
            aria-label="Open channel details"
          >
            <Settings className="w-5 h-5" />
          </Button>
        </div>
      </header>

      {/* Messages Area */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-6 space-y-6 bg-gradient-to-b from-background to-background/50">
        {!isMember ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="w-20 h-20 rounded-2xl bg-secondary flex items-center justify-center mb-6 shadow-inner">
              <Hash className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-2xl font-bold text-foreground mb-2">You are not in this channel</h3>
            <p className="text-muted-foreground mb-8 max-w-md">Join {channel.name} to see history and start messaging with the team.</p>
            <Button 
              size="lg" 
              onClick={() => joinChannel.mutate(channelId!)}
              disabled={joinChannel.isPending}
              className="bg-primary text-primary-foreground font-semibold px-8 rounded-full shadow-lg shadow-primary/20 hover:-translate-y-0.5 transition-transform"
            >
              {joinChannel.isPending ? "Joining..." : "Join Channel"}
            </Button>
          </div>
        ) : (
          <>
            {isMessagesLoading ? (
              <div className="space-y-6">
                {Array.from({ length: 5 }).map((_, index) => (
                  <div key={index} className="flex gap-4">
                    <Skeleton className="h-10 w-10 rounded-full flex-shrink-0" />
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-2">
                        <Skeleton className="h-3 w-24" />
                        <Skeleton className="h-3 w-14" />
                      </div>
                      <Skeleton className={`h-14 rounded-2xl ${index % 2 === 0 ? "w-72 max-w-full" : "w-56 max-w-full"}`} />
                    </div>
                  </div>
                ))}
              </div>
            ) : messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center pb-20">
                <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                  <Hash className="w-8 h-8 text-primary" />
                </div>
                <h3 className="text-xl font-bold text-foreground mb-1">Welcome to {channel.name}!</h3>
                <p className="text-muted-foreground text-sm">This is the start of the channel history.</p>
              </div>
            ) : (
              visibleMessages.map((msg, i) => {
                const isMe = msg.sender_user_id === user?.id;
                const prevMsg = visibleMessages[i - 1];
                const showHeader = !prevMsg || prevMsg.sender_user_id !== msg.sender_user_id || new Date(msg.created_at).getTime() - new Date(prevMsg.created_at).getTime() > 300000;
                const repliedMessage = msg.reply_to_message_id ? messageById.get(msg.reply_to_message_id) : undefined;
                const replyDepth = Math.min(getReplyDepth(msg), MAX_REPLY_INDENT_DEPTH);
                const replyIndent = replyDepth > 0 ? { marginLeft: `${replyDepth * 20}px` } : undefined;
                const nestedReplyCount = getDescendantReplyCount(msg.id);
                const canCollapseReplies = nestedReplyCount > 0;
                const isRepliesCollapsed = collapsedReplyRoots.has(msg.id);

                return (
                  <div
                    key={msg.id}
                    ref={(node) => {
                      messageRefs.current[msg.id] = node;
                    }}
                    className={`flex gap-4 group ${!showHeader ? 'mt-1' : 'mt-6'}`}
                    style={replyIndent}
                  >
                    {showHeader ? (
                      <Avatar className="w-10 h-10 border border-border shadow-sm flex-shrink-0">
                        <AvatarImage src={isMe ? userAvatarUrl : undefined} />
                        <AvatarFallback>{isMe ? user?.username?.[0]?.toUpperCase() : '#'}</AvatarFallback>
                      </Avatar>
                    ) : (
                      <div className="w-10 flex-shrink-0" />
                    )}
                    
                    <div className="flex-1 min-w-0">
                      {canCollapseReplies && (
                        <button
                          type="button"
                          className="mb-1 inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                          onClick={() =>
                            setCollapsedReplyRoots((current) => {
                              const next = new Set(current);
                              if (next.has(msg.id)) {
                                next.delete(msg.id);
                              } else {
                                next.add(msg.id);
                              }
                              return next;
                            })
                          }
                          aria-expanded={!isRepliesCollapsed}
                          aria-label={`${isRepliesCollapsed ? "Show" : "Hide"} replies for message #${msg.seq_id}`}
                        >
                          {isRepliesCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          <span>{isRepliesCollapsed ? "Show" : "Hide"} {nestedReplyCount} repl{nestedReplyCount === 1 ? "y" : "ies"}</span>
                        </button>
                      )}
                      {showHeader && (
                        <div className="flex items-baseline gap-2 mb-1">
                          <span className="font-semibold text-foreground text-sm">
                            {isMe ? (user?.display_name || user?.username || 'You') : `Member ${msg.sender_user_id.slice(0, 8)}`}
                          </span>
                          <span className="text-[11px] text-muted-foreground">{format(new Date(msg.created_at), 'h:mm a')}</span>
                        </div>
                      )}
                      <div className="relative inline-block max-w-[85%] group-hover:bg-accent/50 rounded-lg -mx-2 px-2 py-1 transition-colors">
                        {msg.reply_to_message_id && (
                          <button
                            type="button"
                            onClick={() => jumpToMessage(msg.reply_to_message_id)}
                            className="mb-2 block w-full text-left rounded-md border border-border/60 bg-background/80 px-2 py-1 hover:bg-background transition-colors"
                          >
                            <div className="text-[11px] font-semibold text-primary">
                              Replying to {resolveSenderLabel(repliedMessage)}
                              {msg.reply_to_seq_id ? ` (#${msg.reply_to_seq_id})` : ""}
                            </div>
                            <div className="text-xs text-muted-foreground truncate">{getMessageSnippet(repliedMessage)}</div>
                          </button>
                        )}
                        <div className="text-sm text-foreground/90 whitespace-pre-wrap break-words leading-relaxed">
                          {msg.deleted_at
                            ? "Message deleted"
                            : msg.content_type === "text"
                              ? msg.content_text
                              : JSON.stringify(msg.content_json ?? {}, null, 2)}
                        </div>
                        
                        {/* Hover Actions */}
                        <div className="absolute -top-3 right-0 opacity-0 group-hover:opacity-100 transition-opacity bg-card border border-border rounded-lg shadow-lg flex items-center p-0.5 z-10 translate-x-2">
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-foreground">
                            <SmilePlus className="w-4 h-4" />
                          </Button>
                          {(canCompose || canReplyAsMember) && !msg.deleted_at && (
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-7 w-7 text-muted-foreground hover:text-foreground"
                              onClick={() => setReplyingTo(msg)}
                              aria-label={`Reply to message #${msg.seq_id}`}
                            >
                              <Reply className="w-4 h-4" />
                            </Button>
                          )}
                          {isMe && (
                            <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-foreground">
                              <MoreVertical className="w-4 h-4" />
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Compose Box */}
      {(canCompose || (canReplyAsMember && !!activeReplyTarget)) && (
        <div className="p-4 bg-background border-t border-border flex-shrink-0">
          <div className="max-w-4xl mx-auto bg-secondary rounded-2xl border border-border/50 shadow-sm focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary/30 transition-all p-2 relative">
            {activeReplyTarget && (
              <div className="mb-2 rounded-xl border border-border/60 bg-background/80 px-3 py-2 flex items-start justify-between gap-3">
                <button
                  type="button"
                  className="min-w-0 text-left"
                  onClick={() => jumpToMessage(activeReplyTarget.id)}
                >
                  <div className="text-[11px] font-semibold text-primary">
                    Replying to {resolveSenderLabel(activeReplyTarget)} (#{activeReplyTarget.seq_id})
                  </div>
                  <div className="text-xs text-muted-foreground truncate">{getMessageSnippet(activeReplyTarget)}</div>
                </button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground"
                  onClick={() => setReplyingTo(null)}
                  aria-label="Cancel reply"
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
            )}
            <div className="flex items-end gap-2">
              <Button size="icon" variant="ghost" className="h-10 w-10 text-muted-foreground hover:bg-background rounded-xl flex-shrink-0 mb-1">
                <Paperclip className="w-5 h-5" />
              </Button>
              
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={canCompose ? `Message ${channel.name}...` : "Write a reply..."}
                className="flex-1 bg-transparent border-none focus:ring-0 resize-none max-h-48 min-h-[44px] py-3 text-sm text-foreground placeholder:text-muted-foreground"
                rows={1}
              />

              <Button 
                size="icon" 
                className={`h-10 w-10 rounded-xl flex-shrink-0 mb-1 transition-all ${content.trim() ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20 hover:scale-105' : 'bg-muted text-muted-foreground'}`}
                onClick={handleSend}
                disabled={!content.trim() || sendMessage.isPending || (canReplyAsMember && !activeReplyTarget)}
              >
                <Send className="w-4 h-4 translate-x-0.5 -translate-y-0.5" />
              </Button>
            </div>
          </div>
          <div className="text-center mt-2 text-[10px] text-muted-foreground/60">
            <strong>Enter</strong> to send, <strong>Shift + Enter</strong> for new line
          </div>
        </div>
      )}
    </div>
  );
}
