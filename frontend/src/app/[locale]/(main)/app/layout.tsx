import AppLayout from "@/components/features/chat/pages/app-layout";

interface MainAppLayoutProps {
  children: React.ReactNode;
}

// Renders the main app layout; Next.js invokes it while routing and rendering the application.
export default function MainAppLayout({ children }: MainAppLayoutProps) {
  return <AppLayout>{children}</AppLayout>;
}
