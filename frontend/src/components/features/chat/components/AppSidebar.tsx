"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, ChevronRight, Hash, LogOut, Plus, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useChannels } from "@/hooks/use-channels";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useLogout } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useAuthStore } from "@/store/authStore";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LanguageToggle } from "@/components/LanguageToggle";
import { AuthenticatedImage } from "@/components/shared/AuthenticatedImage";
import { CreateChannelDialog } from "./CreateChannelDialog";
import { ChannelResponse } from "@/types/api";
import { Skeleton } from "@/components/ui/skeleton";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { resolveApiMediaUrl } from "@/lib/mediaUrl";

function getChannelActivityAt(channel: ChannelResponse) {
  const timestamp = channel.last_message_at ?? channel.created_at ?? "";
  const parsed = timestamp ? Date.parse(timestamp) : 0;
  return Number.isNaN(parsed) ? 0 : parsed;
}

function sortChannelsByActivity(channels: ChannelResponse[], locale: string) {
  return [...channels].sort((left, right) => {
    const activityDiff = getChannelActivityAt(right) - getChannelActivityAt(left);
    if (activityDiff !== 0) {
      return activityDiff;
    }

    return left.name.localeCompare(right.name, locale);
  });
}

function ChannelListItem({
  channel,
  href,
  isActive,
}: {
  channel: ChannelResponse;
  href: string;
  isActive: boolean;
}) {
  const channelAvatarUrl = resolveApiMediaUrl(channel.avatar_url);

  return (
    <Link
      href={href}
      className={`flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 group ${
        isActive
          ? "bg-primary text-primary-foreground shadow-md shadow-primary/20"
          : "hover:bg-sidebar-accent text-sidebar-foreground/80 hover:text-sidebar-foreground"
      }`}
    >
      <div
        className={`flex items-center justify-center w-8 h-8 rounded-lg ${
          isActive
            ? "bg-primary-foreground/20 text-white"
            : "bg-sidebar-accent-foreground/10 text-sidebar-foreground/60 group-hover:text-sidebar-foreground"
        }`}
      >
        {channelAvatarUrl ? (
          <AuthenticatedImage src={channelAvatarUrl} alt={channel.name} className="w-full h-full rounded-lg object-cover" />
        ) : (
          <Hash className="w-4 h-4" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate text-sm">{channel.name}</div>
        {channel.last_message?.content_text && (
          <div className={`text-xs truncate ${isActive ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
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
  );
}

function SidebarSection({
  title,
  isOpen,
  onToggle,
  children,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="mb-3 flex w-full items-center justify-between px-2 text-xs font-semibold uppercase tracking-wider text-sidebar-foreground/50 transition-colors hover:text-sidebar-foreground"
        aria-expanded={isOpen}
      >
        <span>{title}</span>
        {isOpen ? (
          <ChevronDown className="h-4 w-4 transition-transform duration-200" />
        ) : (
          <ChevronRight className="h-4 w-4 transition-transform duration-200" />
        )}
      </button>
      <div
        className={`grid transition-[grid-template-rows,opacity] duration-250 ease-out ${
          isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="min-h-0 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}

function ChannelListSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="flex items-center gap-3 rounded-xl px-3 py-2">
          <Skeleton className="h-8 w-8 rounded-lg" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-36 max-w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("sidebar");
  const appT = useTranslations("app");
  const logout = useLogout();
  const user = useAuthStore(s => s.user);
  const userAvatarUrl = resolveApiMediaUrl(user?.avatar_url);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isMyChannelsOpen, setIsMyChannelsOpen] = useState(true);
  const [isChannelsOpen, setIsChannelsOpen] = useState(true);
  const [isDiscoverOpen, setIsDiscoverOpen] = useState(true);
  const debouncedSearchQuery = useDebouncedValue(searchQuery.trim(), 300);
  const isSearching = debouncedSearchQuery.length > 0;

  const {
    data: memberChannels = [],
    isLoading: isMemberChannelsLoading,
  } = useChannels({ scope: "my", q: debouncedSearchQuery });
  const {
    data: discoverChannels = [],
    isLoading: isDiscoverLoading,
  } = useChannels({ scope: "discover", q: debouncedSearchQuery, enabled: isSearching });

  const sortedMemberChannels = sortChannelsByActivity(memberChannels, locale);
  const myChannels = sortedMemberChannels.filter(channel => channel.my_role === "owner" || channel.my_role === "admin");
  const joinedChannels = sortedMemberChannels.filter(channel => channel.my_role !== "owner" && channel.my_role !== "admin");
  const sortedDiscoverChannels = sortChannelsByActivity(discoverChannels, locale);

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
            <h1 className="font-bold text-sidebar-foreground">{appT("name")}</h1>
          </div>
          <div className="flex items-center gap-1">
            <LanguageToggle className="text-sidebar-foreground hover:bg-sidebar-accent" />
            <ThemeToggle className="text-sidebar-foreground hover:bg-sidebar-accent" />
            <Button
              size="icon"
              variant="ghost"
              className="text-sidebar-foreground hover:bg-sidebar-accent"
              onClick={() => setIsCreateDialogOpen(true)}
              aria-label={t("createChannel")}
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
              placeholder={t("searchPlaceholder")}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="w-full bg-sidebar-accent/50 border border-sidebar-border rounded-xl pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 text-sidebar-foreground placeholder:text-muted-foreground transition-all"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-6">
          <SidebarSection title={t("sections.myChannels")} isOpen={isMyChannelsOpen} onToggle={() => setIsMyChannelsOpen(open => !open)}>
            <div className="space-y-1">
              {myChannels.map(channel => (
                <ChannelListItem
                  key={channel.id}
                  channel={channel}
                  href={localePath(`/app/channels/${channel.id}`)}
                  isActive={pathname === localePath(`/app/channels/${channel.id}`)}
                />
              ))}
              {isMemberChannelsLoading && <ChannelListSkeleton />}
              {!isMemberChannelsLoading && myChannels.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">
                  {isSearching ? t("empty.myChannelsSearch") : t("empty.myChannels")}
                </div>
              )}
            </div>
          </SidebarSection>

          <SidebarSection title={t("sections.channels")} isOpen={isChannelsOpen} onToggle={() => setIsChannelsOpen(open => !open)}>
            <div className="space-y-1">
              {joinedChannels.map(channel => (
                <ChannelListItem
                  key={channel.id}
                  channel={channel}
                  href={localePath(`/app/channels/${channel.id}`)}
                  isActive={pathname === localePath(`/app/channels/${channel.id}`)}
                />
              ))}
              {isMemberChannelsLoading && <ChannelListSkeleton />}
              {!isMemberChannelsLoading && joinedChannels.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">
                  {isSearching ? t("empty.joinedSearch") : t("empty.joined")}
                </div>
              )}
            </div>
          </SidebarSection>

          {isSearching ? (
            <SidebarSection title={t("sections.discover")} isOpen={isDiscoverOpen} onToggle={() => setIsDiscoverOpen(open => !open)}>
              <div className="space-y-1">
                {sortedDiscoverChannels.map(channel => (
                  <ChannelListItem
                    key={channel.id}
                    channel={channel}
                    href={localePath(`/app/channels/${channel.id}`)}
                    isActive={pathname === localePath(`/app/channels/${channel.id}`)}
                  />
                ))}
                {isDiscoverLoading && <ChannelListSkeleton />}
                {!isDiscoverLoading && sortedDiscoverChannels.length === 0 && (
                  <div className="px-3 py-2 text-sm text-muted-foreground">{t("empty.discoverSearch")}</div>
                )}
              </div>
            </SidebarSection>
          ) : null}

        </div>

        <div className="p-4 border-t border-sidebar-border bg-sidebar/50">
          <div className="flex items-center gap-3">
            <Link href={localePath("/app/profile")} className="flex min-w-0 flex-1 items-center gap-3 rounded-xl transition-colors hover:bg-sidebar-accent/70 px-2 py-1.5 -mx-2">
              <Avatar className="w-10 h-10 border-2 border-primary/20">
                <AvatarImage src={userAvatarUrl} />
                <AvatarFallback className="bg-sidebar-accent text-sidebar-foreground">{user?.username?.[0]?.toUpperCase() || "U"}</AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-sidebar-foreground truncate">{user?.display_name || user?.username}</div>
                <div className="text-xs text-muted-foreground truncate">@{user?.username}</div>
              </div>
            </Link>
            <Button size="icon" variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => logout.mutate()} aria-label={t("logout")}>
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
