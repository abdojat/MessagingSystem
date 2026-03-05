import { AppShell } from "@/components/layout/app-shell";
import { ChannelChat } from "@/components/chat/channel-chat";

type PageProps = {
  params: Promise<{ channel_id: string }>;
};

export default async function ChannelPage({ params }: PageProps) {
  const { channel_id } = await params;
  return (
    <AppShell selectedChannelId={channel_id}>
      <ChannelChat channelId={channel_id} />
    </AppShell>
  );
}
