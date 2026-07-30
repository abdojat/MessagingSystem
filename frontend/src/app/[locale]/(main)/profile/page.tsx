import { redirect } from "next/navigation";

interface LegacyProfilePageProps {
  params: Promise<{ locale: string }>;
}

// Renders the legacy profile page; Next.js invokes it while routing and rendering the application.
export default async function LegacyProfilePage({ params }: LegacyProfilePageProps) {
  const { locale } = await params;
  redirect(`/${locale}/app/profile`);
}
