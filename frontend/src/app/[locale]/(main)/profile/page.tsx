import { redirect } from "next/navigation";

interface LegacyProfilePageProps {
  params: Promise<{ locale: string }>;
}

export default async function LegacyProfilePage({ params }: LegacyProfilePageProps) {
  const { locale } = await params;
  redirect(`/${locale}/app/profile`);
}
