import { useState } from "react";
import { Link, useLocation } from "wouter";
import { Hash, Plus, Settings, Search, LogOut } from "lucide-react";
import { useChannels } from "../hooks/use-channels";
import { useLogout } from "../hooks/use-auth";
import { Button } from "./ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "./ui/avatar";
import { useAuthStore } from "../store/authStore";
import { ThemeToggle } from "./ThemeToggle";
import { CreateChannelDialog } from "./CreateChannelDialog";

export function AppSidebar() {
  const { data: channels = [] } = useChannels();
  const [location] = useLocation();
  const logout = useLogout();
  const user = useAuthStore(s => s.user);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);

  const myChannels = channels.filter(c => ['owner', 'admin', 'member'].includes(c.my_role || 'none'));
  const discoverChannels = channels.filter(c => !['owner', 'admin', 'member'].includes(c.my_role || 'none'));

  return (
    <>
      <CreateChannelDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
      />

      <div className="w-72 h-screen flex flex-col bg-sidebar border-r border-sidebar-border shadow-2xl z-10 flex-shrink-0">
        <div className="p-4 border-b border-sidebar-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-primary flex items-center justify-center text-primary-foreground font-bold shadow-lg shadow-primary/20">
              C
            </div>
            <h1 className="font-bold text-sidebar-foreground">ChatCore</h1>
          </div>
          <div className="flex items-center gap-1">
            <ThemeToggle className="text-sidebar-foreground hover:bg-sidebar-accent" />
            <Button
              size="icon"
              variant="ghost"
              className="text-sidebar-foreground hover:bg-sidebar-accent"
              onClick={() => setIsCreateDialogOpen(true)}
              aria-label="Create channel"
            >
              <Plus className="w-5 h-5" />
            </Button>
          </div>
        </div>

        <div className="p-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input 
              type="text" 
              placeholder="Search channels..." 
              className="w-full bg-sidebar-accent/50 border border-sidebar-border rounded-xl pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 text-sidebar-foreground placeholder:text-muted-foreground transition-all"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-6">
          <div>
            <h3 className="text-xs font-semibold text-sidebar-foreground/50 uppercase tracking-wider mb-3 px-2">My Channels</h3>
            <div className="space-y-1">
              {myChannels.map(channel => (
                <Link key={channel.id} href={`/app/channels/${channel.id}`} className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 group ${location === `/app/channels/${channel.id}` ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20' : 'hover:bg-sidebar-accent text-sidebar-foreground/80 hover:text-sidebar-foreground'}`}>
                  <div className={`flex items-center justify-center w-8 h-8 rounded-lg ${location === `/app/channels/${channel.id}` ? 'bg-primary-foreground/20 text-white' : 'bg-sidebar-accent-foreground/10 text-sidebar-foreground/60 group-hover:text-sidebar-foreground'}`}>
                    {channel.avatar_url ? <img src={channel.avatar_url} className="w-full h-full rounded-lg object-cover" /> : <Hash className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate text-sm">{channel.name}</div>
                    {channel.last_message?.content_text && (
                      <div className={`text-xs truncate ${location === `/app/channels/${channel.id}` ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                        {channel.last_message.content_text}
                      </div>
                    )}
                  </div>
                  {channel.unread_count ? (
                    <div className="bg-destructive text-destructive-foreground text-[10px] font-bold px-2 py-0.5 rounded-full">
                      {channel.unread_count}
                    </div>
                  ) : null}
                </Link>
              ))}
              {myChannels.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">No channels yet</div>
              )}
            </div>
          </div>

          <div>
            <h3 className="text-xs font-semibold text-sidebar-foreground/50 uppercase tracking-wider mb-3 px-2">Discover</h3>
            <div className="space-y-1">
              {discoverChannels.map(channel => (
                <Link key={channel.id} href={`/app/channels/${channel.id}`} className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 hover:bg-sidebar-accent text-sidebar-foreground/80 hover:text-sidebar-foreground`}>
                  <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-sidebar-accent-foreground/10 text-sidebar-foreground/60">
                    <Hash className="w-4 h-4" />
                  </div>
                  <div className="font-medium truncate text-sm flex-1">{channel.name}</div>
                </Link>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-sidebar-border bg-sidebar/50">
          <div className="flex items-center gap-3">
            <Link href="/app/profile" className="flex min-w-0 flex-1 items-center gap-3 rounded-xl transition-colors hover:bg-sidebar-accent/70 px-2 py-1.5 -mx-2">
              <Avatar className="w-10 h-10 border-2 border-primary/20">
                <AvatarImage src={user?.avatar_url || undefined} />
                <AvatarFallback className="bg-sidebar-accent text-sidebar-foreground">{user?.username?.[0]?.toUpperCase() || "U"}</AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-sidebar-foreground truncate">{user?.display_name || user?.username}</div>
                <div className="text-xs text-muted-foreground truncate">@{user?.username}</div>
              </div>
            </Link>
            <Link href="/settings/sessions">
              <Button size="icon" variant="ghost" className="text-muted-foreground hover:text-sidebar-foreground">
                <Settings className="w-4 h-4" />
              </Button>
            </Link>
            <Button size="icon" variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => logout.mutate()}>
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
