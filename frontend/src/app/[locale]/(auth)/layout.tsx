import { ChatClientRoot } from "@/components/features/chat/routes/chat-client-root";

interface AuthLayoutProps {
  children: React.ReactNode;
}

export default function AuthLayout({ children }: AuthLayoutProps) {
  return <ChatClientRoot>{children}</ChatClientRoot>;
}
