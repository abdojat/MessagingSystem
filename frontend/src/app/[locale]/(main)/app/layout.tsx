import AppLayout from "@/components/features/chat/pages/app-layout";

interface MainAppLayoutProps {
  children: React.ReactNode;
}

export default function MainAppLayout({ children }: MainAppLayoutProps) {
  return <AppLayout>{children}</AppLayout>;
}
