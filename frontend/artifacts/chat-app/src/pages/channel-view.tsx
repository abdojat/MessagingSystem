import { useLocation, useParams } from "wouter";
import { useChannel, useJoinChannel } from "../hooks/use-channels";
import { useMarkSeen, useMessages, useSendMessage } from "../hooks/use-messages";
import { Hash, Settings, Paperclip, Send, SmilePlus, Reply, MoreVertical } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { format } from "date-fns";
import { Button } from "../components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "../components/ui/avatar";
import { useAuthStore } from "../store/authStore";

export default function ChannelView() {
  const { channelId } = useParams();
  const [, setLocation] = useLocation();
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
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastMarkedSeenSeqRef = useRef<number | null>(null);
  const user = useAuthStore(s => s.user);
  const isMember = ['owner', 'admin', 'member'].includes(channel?.my_role || '');
  const canCompose = ['owner', 'admin'].includes(channel?.my_role || '');

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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

  if (isChannelLoading) return <div className="flex-1 flex items-center justify-center"><div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" /></div>;
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

  const handleSend = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!canCompose || !content.trim() || !channelId) return;
    sendMessage.mutate({ channelId, content_text: content });
    setContent("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-background relative z-0">
      {/* Header */}
      <header className="h-16 border-b border-border bg-background/80 backdrop-blur-md flex items-center justify-between px-6 flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
            {channel.avatar_url ? <img src={channel.avatar_url} className="w-full h-full rounded-xl object-cover" /> : <Hash className="w-5 h-5" />}
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
            onClick={() => setLocation(`/app/channels/${channel.id}/details`)}
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
              <div className="text-center text-muted-foreground py-10">Loading messages...</div>
            ) : messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center pb-20">
                <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                  <Hash className="w-8 h-8 text-primary" />
                </div>
                <h3 className="text-xl font-bold text-foreground mb-1">Welcome to {channel.name}!</h3>
                <p className="text-muted-foreground text-sm">This is the start of the channel history.</p>
              </div>
            ) : (
              messages.map((msg, i) => {
                const isMe = msg.sender_user_id === user?.id;
                const prevMsg = messages[i - 1];
                const showHeader = !prevMsg || prevMsg.sender_user_id !== msg.sender_user_id || new Date(msg.created_at).getTime() - new Date(prevMsg.created_at).getTime() > 300000;

                return (
                  <div key={msg.id} className={`flex gap-4 group ${!showHeader ? 'mt-1' : 'mt-6'}`}>
                    {showHeader ? (
                      <Avatar className="w-10 h-10 border border-border shadow-sm flex-shrink-0">
                        <AvatarImage src={isMe ? user?.avatar_url || undefined : undefined} />
                        <AvatarFallback>{isMe ? user?.username?.[0]?.toUpperCase() : '#'}</AvatarFallback>
                      </Avatar>
                    ) : (
                      <div className="w-10 flex-shrink-0" />
                    )}
                    
                    <div className="flex-1 min-w-0">
                      {showHeader && (
                        <div className="flex items-baseline gap-2 mb-1">
                          <span className="font-semibold text-foreground text-sm">
                            {isMe ? (user?.display_name || user?.username || 'You') : `Member ${msg.sender_user_id.slice(0, 8)}`}
                          </span>
                          <span className="text-[11px] text-muted-foreground">{format(new Date(msg.created_at), 'h:mm a')}</span>
                        </div>
                      )}
                      <div className="relative inline-block max-w-[85%] group-hover:bg-accent/50 rounded-lg -mx-2 px-2 py-1 transition-colors">
                        <div className="text-sm text-foreground/90 whitespace-pre-wrap break-words leading-relaxed">
                          {msg.content_text}
                        </div>
                        
                        {/* Hover Actions */}
                        <div className="absolute -top-3 right-0 opacity-0 group-hover:opacity-100 transition-opacity bg-card border border-border rounded-lg shadow-lg flex items-center p-0.5 z-10 translate-x-2">
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-foreground">
                            <SmilePlus className="w-4 h-4" />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-foreground">
                            <Reply className="w-4 h-4" />
                          </Button>
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
      {canCompose && (
        <div className="p-4 bg-background border-t border-border flex-shrink-0">
          <div className="max-w-4xl mx-auto bg-secondary rounded-2xl border border-border/50 shadow-sm focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary/30 transition-all p-2 flex items-end gap-2 relative">
            <Button size="icon" variant="ghost" className="h-10 w-10 text-muted-foreground hover:bg-background rounded-xl flex-shrink-0 mb-1">
              <Paperclip className="w-5 h-5" />
            </Button>
            
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Message ${channel.name}...`}
              className="flex-1 bg-transparent border-none focus:ring-0 resize-none max-h-48 min-h-[44px] py-3 text-sm text-foreground placeholder:text-muted-foreground"
              rows={1}
            />

            <Button 
              size="icon" 
              className={`h-10 w-10 rounded-xl flex-shrink-0 mb-1 transition-all ${content.trim() ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20 hover:scale-105' : 'bg-muted text-muted-foreground'}`}
              onClick={handleSend}
              disabled={!content.trim() || sendMessage.isPending}
            >
              <Send className="w-4 h-4 translate-x-0.5 -translate-y-0.5" />
            </Button>
          </div>
          <div className="text-center mt-2 text-[10px] text-muted-foreground/60">
            <strong>Enter</strong> to send, <strong>Shift + Enter</strong> for new line
          </div>
        </div>
      )}
    </div>
  );
}
