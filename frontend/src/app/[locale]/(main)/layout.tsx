import { ChatClientRoot } from "@/components/features/chat/routes/chat-client-root";

interface MainLayoutProps {
  children: React.ReactNode;
}

// Renders the main layout; Next.js invokes it while routing and rendering the application.
export default function MainLayout({ children }: MainLayoutProps) {
  return <ChatClientRoot>{children}</ChatClientRoot>;
}
