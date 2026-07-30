import { ChatClientRoot } from "@/components/features/chat/routes/chat-client-root";

interface AuthLayoutProps {
  children: React.ReactNode;
}

// Renders the auth layout; Next.js invokes it while routing and rendering the application.
export default function AuthLayout({ children }: AuthLayoutProps) {
  return <ChatClientRoot>{children}</ChatClientRoot>;
}
