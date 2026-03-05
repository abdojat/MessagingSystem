import { InviteClientPage } from "@/components/invites/invite-client-page";

type PageProps = {
  params: Promise<{ token: string }>;
};

export default async function InviteTokenPage({ params }: PageProps) {
  const { token } = await params;
  return <InviteClientPage token={token} />;
}
